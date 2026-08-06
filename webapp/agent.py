"""The build agent — agentic loops around the deterministic engine.

"Measure thrice, cut once." The single cut is the released PDF; three audit passes
run before it, each able to loop back:

* **Measure 1 — decompose + self-audit.** Turn the user's natural-language
  description into schema fields, then run a second pass that checks the first for
  missed or wrong extractions. Every extracted value is validated against the
  schema deterministically; a number the user did not state can never enter
  (Law 1 — the model echoes stated values with their units, code does the unit
  math).
* **Measure 2 — completeness (two judges).** Before solving, the deterministic
  judge (required fields + invariants satisfiable) and the AI judge (gaps the
  schema can't see) must agree; the AI judge may request but never approve.
* **Measure 3 — release gates.** Before delivery, provenance + overflow + visual
  gates must all pass (Law 5).

Only the schema owns the field set and invariants. The model decomposes into,
prefills, orders, phrases and audits within that guarded set — it never invents a
dimensioned field with no invariant behind it (§7.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field

from build_assistant.elicitation.llm import LLMBoundary, LLMBoundaryError
from build_assistant.elicitation.intake import completeness_gate

_UNIT_TO_IN = {"in": 1.0, '"': 1.0, "inch": 1.0, "inches": 1.0,
               "ft": 12.0, "foot": 12.0, "feet": 12.0, "'": 12.0,
               "cm": 1 / 2.54, "mm": 1 / 25.4, "m": 39.3701}


@dataclass
class IntakeReport:
    node: str | None
    extracted: dict                 # field -> converted value (prefilled)
    extracted_display: list         # [{field,label,value,source}] for the UI
    ambiguities: list
    unknown: bool
    audit_notes: list
    confidence: float


class BuildAgent:
    def __init__(self, boundary: LLMBoundary, registry):
        self.boundary = boundary
        self.reg = registry

    # ---- field metadata from the schema (the guarded set) ----
    def _field_meta(self, node: str) -> dict:
        meta = {}
        for q in self.reg.questions(node):
            meta[q.field] = {
                "type": q.type, "unit": q.unit, "required": q.required,
                "options": [{"value": str(o.value), "label": o.label} for o in q.options],
                "prompt": q.prompt,
            }
        return meta

    def _leaf_catalog(self) -> str:
        out = []
        for leaf in self.reg.all_leaves():
            out.append(f"{leaf}: {self.reg.schema(leaf)['display_name']}")
        return "; ".join(out)

    # =====================================================================
    # MEASURE 1 — decompose the description, then audit the decomposition
    # =====================================================================
    def intake(self, text: str, node_hint: str | None = None) -> IntakeReport:
        node, raw_fields, ambiguities, unknown, conf, notes = self._decompose(text, node_hint)
        if node and node in self.reg.all_leaves():
            # self-audit pass (measure twice): did we miss anything the user said?
            missed = self._audit_decomposition(text, node, raw_fields)
            raw_fields = self._merge(raw_fields, missed, notes)
            extracted, display = self._validate(node, raw_fields, text)
        else:
            extracted, display = {}, []
        return IntakeReport(node, extracted, display, ambiguities, unknown, notes, conf)

    _DECOMPOSE_SCHEMA = {
        "type": "object", "required": ["node", "confidence", "fields", "ambiguities", "unknown"],
        "properties": {
            "node": {"type": "string"}, "confidence": {"type": "number"},
            "unknown": {"type": "boolean"},
            "fields": {"type": "array", "items": {"type": "object",
                "required": ["field", "value"], "properties": {
                    "field": {"type": "string"}, "value": {}, "unit": {}}}},
            "ambiguities": {"type": "array"},
        },
    }

    _CLASSIFY_SCHEMA = {
        "type": "object", "required": ["node", "confidence", "unknown", "ambiguities"],
        "properties": {"node": {"type": "string"}, "confidence": {"type": "number"},
                       "unknown": {"type": "boolean"}, "ambiguities": {"type": "array"}},
    }
    _EXTRACT_SCHEMA = {
        "type": "object", "required": ["fields"],
        "properties": {"fields": {"type": "array", "items": {"type": "object",
            "required": ["field", "value"], "properties": {
                "field": {"type": "string"}, "value": {}, "unit": {}}}}},
    }

    def _decompose(self, text, node_hint):
        """Two reliable steps: classify the node, then extract WITH its field list.

        Passing the node's exact fields to the extractor is what makes extraction
        reliable — without it the model guesses field names."""
        try:
            node, ambiguities, unknown, conf = self._classify(text, node_hint)
            if not node:
                return (None, {}, ambiguities, unknown, conf, ["classified: unknown"])
            fields = self._extract(text, node)
            note = "decomposed via model" + (f"; {node} @ {conf:.2f}")
            return (node, fields, ambiguities, unknown, conf, [note])
        except Exception:  # noqa: BLE001
            return self._decompose_fallback(text, node_hint)

    def _classify(self, text, node_hint):
        if node_hint and node_hint in self.reg.all_leaves():
            return node_hint, [], False, 1.0
        prompt = (
            "Classify this build request to one buildable node. If a term maps to two "
            "different constructions (e.g. a troweled overlay vs a cast slab), list it "
            "under ambiguities and do NOT guess.\n"
            f"Buildable nodes: {self._leaf_catalog()}.\n"
            'Return JSON: {"node":"<id or unknown>","confidence":0..1,"unknown":false,'
            '"ambiguities":[{"term":"...","constructions":[{"construction":"...","note":"..."}]}]}\n'
            f"USER: {text}"
        )
        out = self.boundary.call(prompt, "classify", self._CLASSIFY_SCHEMA)
        node = out["node"] if out["node"] in self.reg.all_leaves() else None
        return node, out.get("ambiguities", []), out.get("unknown", node is None), \
            float(out.get("confidence", 0.5))

    def _extract(self, text, node):
        prompt = (
            "Extract KNOWN schema fields from this request. Extract a field ONLY if the "
            "user stated it; copy the value EXACTLY as stated with its unit; never infer, "
            "compute or invent a dimension; omit anything not stated. Map spatial words to "
            "fields (long->length, wide->length, deep->width/depth, tall->height, thick->"
            "thickness/edge).\n"
            f"{self._field_hint(node)}"
            'Return JSON: {"fields":[{"field","value","unit"}]}\n'
            f"USER: {text}"
        )
        out = self.boundary.call(prompt, "extract", self._EXTRACT_SCHEMA)
        return {f["field"]: (f["value"], f.get("unit", "")) for f in out["fields"]}

    def _field_hint(self, node):
        if not node or node not in self.reg.all_leaves():
            return ""
        meta = self._field_meta(node)
        lines = []
        for f, m in meta.items():
            opts = "|".join(o["value"] for o in m["options"]) if m["options"] else m["type"]
            lines.append(f"  {f} ({opts})")
        return f"Fields for {node}:\n" + "\n".join(lines) + "\n"

    def _decompose_fallback(self, text, node_hint):
        """Deterministic keyword decomposition (no key / model failure)."""
        t = text.lower()
        node = node_hint
        if not node:
            for leaf in self.reg.all_leaves():
                if leaf.replace("_", " ") in t:
                    node = leaf
                    break
            if not node and ("table" in t):
                node = "coffee_table"
            if not node and ("shelf" in t):
                node = "floating_shelf"
        fields = {}
        import re
        if node:
            meta = self._field_meta(node)
            # choice fields by option label/value keyword
            for f, m in meta.items():
                for o in m["options"]:
                    if o["value"].replace("_", " ") in t or o["label"].lower().split()[0] in t:
                        fields[f] = (o["value"], "")
                        break
            if "concrete" in t or "microcement" in t or "cement" in t:
                if "finish_system" in meta:
                    fields["finish_system"] = ("microcement_over_cement_board", "")
            if "plinth" in t and "base_type" in meta:
                fields["base_type"] = ("plinth", "")
            # numbers with units -> first numeric fields in impact order
            nums = re.findall(r'(\d+(?:\.\d+)?)\s*(ft|feet|foot|in|inch|inches|cm|mm|")?', t)
            nums = [(v, u) for v, u in nums if v]
        return (node, fields, [], node is None, 0.5 if node else 0.0, ["decomposed via keywords"])

    _AUDIT_SCHEMA = {
        "type": "object", "required": ["missed", "confident"],
        "properties": {
            "missed": {"type": "array", "items": {"type": "object",
                "required": ["field", "value"], "properties": {
                    "field": {"type": "string"}, "value": {}, "unit": {}}}},
            "confident": {"type": "boolean"},
        },
    }

    def _audit_decomposition(self, text, node, raw_fields):
        """Second pass: what did the first extraction miss? (measure twice)."""
        already = ", ".join(raw_fields.keys()) or "none"
        prompt = (
            "Audit a first-pass extraction for completeness. Here is the user's request "
            "and the fields already extracted. List ONLY fields the user clearly stated "
            "that are still missing — same rule: never invent a dimension, echo stated "
            "values with units.\n"
            f"{self._field_hint(node)}Already extracted: {already}.\n"
            'Return JSON: {"missed": [{"field","value","unit"}], "confident": true}\n'
            f"USER: {text}"
        )
        try:
            out = self.boundary.call(prompt, "audit", self._AUDIT_SCHEMA)
            return {m["field"]: (m["value"], m.get("unit", "")) for m in out["missed"]}
        except Exception:  # noqa: BLE001
            return {}

    def _merge(self, base, extra, notes):
        added = [k for k in extra if k not in base]
        if added:
            notes.append(f"audit recovered: {', '.join(added)}")
        return {**extra, **base}   # base (first pass) wins on conflict

    # ---- deterministic validation against the schema (the guard) ----
    def _validate(self, node, raw_fields, text):
        import re
        meta = self._field_meta(node)
        text_numbers = set(re.findall(r'\d+(?:\.\d+)?', text))
        extracted, display = {}, []
        for f, (val, unit) in raw_fields.items():
            if f not in meta:
                continue                       # never accept a non-schema field
            m = meta[f]
            if m["type"] == "numeric":
                # Law 1 hard guard: the stated number must literally appear in the
                # user's text, or we drop it and ask instead. No invented dimensions,
                # not from the model and not from the self-audit pass.
                stated = re.findall(r'\d+(?:\.\d+)?', str(val))
                if not stated or stated[0] not in text_numbers:
                    continue
                num = self._to_inches(val, unit)
                if num is None or num <= 0:
                    continue
                extracted[f] = round(num, 4)
                disp = f'{extracted[f]:g}{"in" if m["unit"]=="in" else ""}'
            else:
                match = self._match_option(val, m["options"])
                if match is None:
                    continue                   # invalid enum -> ask instead
                extracted[f] = match
                disp = next((o["label"] for o in m["options"] if o["value"] == match), match)
            display.append({"field": f, "label": _LABELS.get(f, f.replace("_", " ").title()),
                            "value": disp, "source": "from your description"})
        return extracted, display

    def _to_inches(self, val, unit):
        try:
            num = float(str(val).strip().rstrip('"').strip())
        except ValueError:
            import re
            mm = re.search(r'\d+(?:\.\d+)?', str(val))
            if not mm:
                return None
            num = float(mm.group())
        factor = _UNIT_TO_IN.get(str(unit).strip().lower(), 1.0)
        return num * factor

    def _match_option(self, val, options):
        v = str(val).strip().lower()
        for o in options:
            if v == o["value"].lower() or v == o["label"].lower():
                return o["value"]
        for o in options:
            if v in o["label"].lower() or o["value"].replace("_", " ").lower() in v:
                return o["value"]
        return None

    # =====================================================================
    # tailored questioning — AI phrases the remaining gaps in context
    # =====================================================================
    _TAILOR_SCHEMA = {
        "type": "object", "required": ["questions"],
        "properties": {"questions": {"type": "array", "items": {"type": "object",
            "required": ["id", "prompt"], "properties": {
                "id": {"type": "string"}, "prompt": {"type": "string"}}}}},
    }

    def tailor(self, node, text, turn_questions) -> dict:
        """Return {question_id: tailored_prompt}. Falls back to schema prompts."""
        if not text:
            return {}
        qs = [{"id": q.id, "field": q.field, "default": q.prompt} for q in turn_questions]
        prompt = (
            "Rephrase each question so it fits the user's described project. Keep the same "
            "meaning and the same answer options; only make the wording specific and "
            "natural. Do not add or remove questions, do not mention numbers.\n"
            f"User described: {text}\n"
            f"Questions: {json.dumps(qs)}\n"
            'Return JSON: {"questions": [{"id","prompt"}]}'
        )
        try:
            out = self.boundary.call(prompt, "tailor", self._TAILOR_SCHEMA)
            return {q["id"]: q["prompt"] for q in out["questions"]}
        except Exception:  # noqa: BLE001
            return {}

    # =====================================================================
    # MEASURE 2 — completeness audit (two judges)
    # =====================================================================
    def audit_ready(self, node, answers):
        approved, verdicts = completeness_gate(node, answers, self.reg, self.boundary)
        return approved, [{"judge": v.judge, "approved": v.approved,
                           "missing": v.missing_fields, "reasons": v.reasons} for v in verdicts]


_LABELS = {
    "overall_length": "Length", "overall_width": "Width", "overall_depth": "Depth",
    "overall_height": "Height", "overall_thickness": "Thickness",
    "slab_edge_thickness": "Top edge", "base_type": "Base", "finish_system": "Finish",
    "plinth_inset": "Reveal", "assembly": "Assembly", "finish_color": "Colour",
    "finish_sheen": "Sheen",
}
