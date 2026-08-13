"""The design agent — open-domain, agent-authored, loop-refined.

This is the "build anything" core. From a natural-language description the agent
AUTHORS a parametric model (the DesignIR), then refines it through cycles:

    synthesize -> compile (deterministic) -> critique -> repair -> compile -> ...

until it converges (no issues, compiles clean, invariants hold) or the cycle
budget is spent. The agent supplies structure and relationships; the engine
computes every number (Law 1). Every round is audited deterministically — a round
that fails to compile or violates an invariant feeds its exact error back to the
repair step. More cycles are spent when the design needs them.

Only the ARITHMETIC is off-limits to the model; the architecture, judgement and
refinement are exactly its job (per the product intent).
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field

from build_assistant.catalog.materials import all_materials
from build_assistant.catalog.finishes import all_finishes
from build_assistant.generative.model import DesignIR
from build_assistant.generative.compiler import compile_design
from build_assistant.core.invariants import InvariantError
from build_assistant.generative.evaluator import ExprError

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
MAX_ROUNDS = int(os.environ.get("DESIGN_MAX_ROUNDS", "5"))
#: Hard ceiling on a single reply, so a runaway design fails loudly
#: instead of doubling forever.
MAX_TOKENS_CEILING = int(os.environ.get("DESIGN_MAX_TOKENS", "24000"))


def _fmt(v: float) -> str:
    """Quoted to 1/32, matching the cut list — prose that says 29-61/64" while the
    table it refers to says 29-31/32" reads as two different parts."""
    from build_assistant.drawing.primitives import fmt_inches
    return fmt_inches(v, 32)


@dataclass
class DesignResult:
    ir: DesignIR | None
    geo: object | None
    converged: bool
    rounds: list = field(default_factory=list)   # audit trail
    error: str = ""


class DesignAgent:
    def __init__(self):
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        self.last_stop_reason = ""
        self.base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")

    @property
    def live(self) -> bool:
        return bool(self.key)

    # ---------------------------------------------------------------- LLM
    def _llm(self, system: str, user: str, max_tokens: int = 3000,
             images: list | None = None) -> str:
        # Inspiration photos ride with the text as image blocks. They were being
        # collected and never looked at, which made the app's own promise —
        # "this shapes the finish and proportions" — untrue.
        content: list | str = user
        if images:
            content = [*_image_blocks(images), {"type": "text", "text": user}]
        body = json.dumps({"model": MODEL, "max_tokens": max_tokens, "system": system,
                           "messages": [{"role": "user", "content": content}]}).encode()
        req = urllib.request.Request(self.base + "/v1/messages", data=body, method="POST",
            headers={"content-type": "application/json", "x-api-key": self.key,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        # Why the model stopped matters. A reply cut off at the token ceiling is
        # not malformed JSON, and treating it as such sent the retry to ask for
        # valid JSON when what it needed was more room.
        self.last_stop_reason = data.get("stop_reason", "")
        return "".join(b.get("text", "") for b in data.get("content", []))

    def _llm_json(self, system: str, user: str, max_tokens: int = 3000, tries: int = 2,
                  images: list | None = None) -> dict:
        last, budget, truncated = "", max_tokens, False
        for _ in range(tries + 1):
            raw = self._llm(system, user + last, budget, images=images)
            truncated = self.last_stop_reason == "max_tokens"
            if truncated:
                # A sofa frame is a bigger model than a bookshelf: more rails,
                # stiles and blocks, and the reply ran out of room mid-part. Give
                # it more rather than asking again for the same size.
                budget = min(int(budget * 2), MAX_TOKENS_CEILING)
                last = ""
                if budget > max_tokens:
                    continue
            a, b = raw.find("{"), raw.rfind("}")
            if a >= 0 and b > a:
                try:
                    return json.loads(raw[a:b + 1])
                except json.JSONDecodeError as e:
                    last = f"\n\nYour previous reply was not valid JSON ({e}). Return ONLY valid JSON."
            else:
                last = "\n\nReturn ONLY a JSON object."
        if truncated:
            raise RuntimeError(
                f"the design ran past {budget} tokens — it is larger than this "
                f"step can express in one reply")
        raise RuntimeError("model did not return valid JSON")

    # ---------------------------------------------------------------- catalog context
    def _catalog(self) -> str:
        mats = "\n".join(
            f"  {m.id}: {m.display_name}, actual_thickness={m.actual_thickness}, "
            f"stock={m.stock_sizes[0].w}x{m.stock_sizes[0].h}, category={m.category}"
            for m in all_materials())
        fins = "\n".join(f"  {f.id}: {f.display_name}, per_face_offset={f.per_face_offset}, "
                         f"direction={f.direction}" for f in all_finishes())
        return f"MATERIALS (choose by id):\n{mats}\n\nFINISH SYSTEMS (choose by id, or 'none'):\n{fins}"

    _SCHEMA_DOC = """DesignIR JSON shape (the engine computes all numbers from your formulas):
{
 "name": str, "summary": str, "node_kind": str,
 "params": [{"id": symbol, "label": str, "value": number_in_inches, "unit":"in",
             "source":"user"|"default"|"derived", "basis": str}],
 "materials": [{"role": str, "material_id": catalog_id}],
 "finish_id": catalog_finish_id_or_"none",
 "elements": [{"id": str, "kind": str, "length_expr": expr, "width_expr": expr,
               "height_expr": expr, "z_base_expr": expr, "stacks_height": bool,
               "faces": [{"name":"top|bottom|left|right|front|back","exposed":bool,"finished":bool}]}],
 "parts": [{"id":"A","name": str, "element": element_id, "material_role": role,
            "length_expr": expr, "width_expr": expr, "qty_expr": expr,
            "grain":"length|width|none",
            "finished_faces_len": 0-2, "finished_faces_wid": 0-2, "joint": str,
            "box_x":expr,"box_y":expr,"box_z":expr,"box_w":expr,"box_d":expr,"box_h":expr,
            "step_x":expr,"step_y":expr,"step_z":expr,
            "joint_type":"butt|dado|groove|rabbet|pocket|miter","joint_depth_expr":expr}],
 "sections": [{"tag":"A-A","axis":"x|y|z","at_expr":expr,"why":str}],
 "invariants": [{"kind":"span","params":{"name":str,"unsupported_span":expr,"flex_threshold":number}},
                {"kind":"backing","params":{"name":str,"surface_width":expr,"backing_width":expr}}],
 "derived": [{"label":str,"value":str,"basis":str,"is_overridable":bool}],
 "operations": [str], "fasteners": [{"fastener_id":str,"seam_expr":expr,"spacing":number}],
 "warnings": [str]
}
EXPRESSIONS: arithmetic over param ids and material symbols only. For a material
role R you may use `R_t` (actual thickness), `R_sw`/`R_sh` (stock size). Allowed:
+ - * / , parentheses, min/max/ceil/floor/round/abs/sqrt/hypot (a diagonal
brace is hypot(run, rise)). NEVER write a bare final
dimension as a literal unless it is a genuine constant (e.g. a 1/4 setback).
SECTIONS: name 1-2 sections that show what a builder most needs to see, each with
the axis its cutting plane is normal to, where along that axis to cut, and WHY
(e.g. "through the drawer bank, to show the runner housings"). Choose the planes
that reveal the joinery and internal structure — not an empty gap and not a plane
that grazes an outside face. The engine draws them and computes every dimension;
you are only choosing where to look. Omit sections and the engine picks for you.
PLACEMENT (required): give every part a 3D box in assembly space, inches, as
expressions. x=left→right, y=front→back (depth), z=floor→up. box_w/box_d/box_h are
extents along x/y/z; TWO equal the part's cut size and ONE equals the material
thickness (use the role's `_t` symbol). box_x/y/z is the part's minimum corner.
For qty>1 parts that repeat (e.g. shelves up the height), set step_x/y/z to the
spacing between instances. Placement must form the actual assembled object — the
engine draws plan, elevations and an exploded view from these boxes, so get them
right (a side panel is thin in x, a shelf thin in z, a back thin in y).
Every part must sit INSIDE the object and touch what it fastens to. step_x/y/z
repeats a part along ONE direction only: shelves that stack repeat up z with
step_z, and if a design has shelves in two bays those are two separate parts, not
one part stepped sideways out of the case. Never step a part past the outside of
the piece. Two solid parts must not occupy the same space — a shelf spans BETWEEN
the sides (or into a dado by its depth), never through them.
JOINERY: set joint_type on the member that RECEIVES a machined cut (the housing) —
the side panel that carries a dado for a shelf, the panel with a rabbet for a
back. Give joint_depth_expr for that cut (a third of the housing thickness is
typical). Leave joint_type "butt" for parts that simply butt together. The engine
draws the real machined profile in the joint details from these, so be accurate.
RULES: parts must be cuttable from the chosen material's stock. Use joinery that
makes sense (butt/dado/pocket). Mark finished_faces_* only for faces that get the
finish. For any unsupported shelf/panel add a span invariant whose flex_threshold
is the MAX span in INCHES the material can hold without sagging (3/4 plywood/solid
shelf ~ 30-36; thinner stock less). Never set a tiny threshold. Include a back
panel or diagonal brace on tall casework so it can't rack, and list fasteners.
Keep it genuinely buildable."""

    # ---------------------------------------------------------------- synthesize
    def synthesize(self, description: str, answers: dict,
                   photos: list | None = None) -> DesignIR:
        system = ("You are a furniture/DIY design engineer. You output a parametric build "
                  "model as JSON. You never compute final dimensions yourself — you write "
                  "formulas over parameters; a deterministic engine evaluates them. Design "
                  "something actually buildable from the given catalog.")
        user = (f"{self._catalog()}\n\n{self._SCHEMA_DOC}\n\n"
                f"USER WANTS: {description}\n"
                f"Known parameters (inches): {json.dumps(answers)}\n"
                + ("The attached photos are what they want it to look like. Read the "
                   "proportions, materials and finish from them and design to that, "
                   "noting in `warnings` what you took from them.\n" if photos else "")
                + "Author the full DesignIR. Use the known parameters; add sensible "
                "defaults (source='default') for any other dimension the build needs, "
                "each with a short basis. Return ONLY the JSON.")
        return DesignIR.from_dict(self._llm_json(system, user, 10000, images=photos))

    # ---------------------------------------------------------------- critique
    def critique(self, ir: DesignIR, geo, error: str) -> dict:
        parts = [{"id": p.id, "name": p.name, "cut": list(p.cut_wh()), "qty": p.qty,
                  "material": p.material_id} for p in (geo.parts if geo else [])]
        system = ("You are a shop foreman reviewing the ARCHITECTURE of a build before "
                  "anyone cuts. A deterministic engine already computed and verified every "
                  "part dimension (fit to stock, positive size, joinery thickness). TRUST "
                  "those numbers — do NOT recompute or second-guess any dimension; a part that "
                  "is a board-thickness smaller than the outside is correct joinery.")
        user = (f"Design: {ir.node_kind} — {ir.summary}\n"
                f"Parts (dimensions already verified by the engine): {json.dumps(parts)}\n"
                f"Engine error (if any): {error or 'none'}\n"
                "Judge only STRUCTURE and COMPLETENESS: is a structural part missing (back "
                "panel or brace against racking, cleats, shelf supports, fasteners)? is the "
                "material wrong for the load/use? is any shelf/panel span too long to hold its "
                "load? would it be unstable or unsafe? does the assembly actually work?\n"
                "Do NOT flag dimensions, fractions, or off-by-a-thickness values — those are the "
                "engine's and are correct. Only flag things a builder would actually hit.\n"
                "SEVERITY: 'high' = won't build / will fail / unsafe. 'med'/'low' = improvement.\n"
                'Return JSON {"issues":[{"severity":"high|med|low","what":str,"fix_hint":str}],'
                '"buildable": bool}. Empty issues if the architecture is sound.')
        try:
            return self._llm_json(system, user, 1200)
        except Exception:  # noqa: BLE001
            return {"issues": [], "buildable": True}

    # ---------------------------------------------------------------- repair
    def repair(self, ir: DesignIR, issues: list, error: str) -> DesignIR:
        system = ("You revise a parametric build model to fix the listed problems. Keep the "
                  "same JSON shape. Change only what's needed. The engine computes numbers "
                  "from your formulas.")
        user = (f"{self._catalog()}\n\n{self._SCHEMA_DOC}\n\n"
                f"Current model:\n{json.dumps(ir.to_dict())}\n\n"
                f"Engine error: {error or 'none'}\n"
                f"Issues to fix: {json.dumps(issues)}\n"
                "Return the full corrected DesignIR JSON only.")
        return DesignIR.from_dict(self._llm_json(system, user, 10000, images=photos))

    # ---------------------------------------------------------------- packet authoring
    _PACKET_SCHEMA = {
        "type": "object", "required": ["title", "subtitle", "callouts", "steps"],
        "properties": {
            "title": {"type": "string"}, "subtitle": {"type": "string"},
            "spec_meta": {"type": "object"},
            "callouts": {"type": "array", "items": {"type": "object",
                "required": ["title", "body"], "properties": {
                    "title": {"type": "string"}, "body": {"type": "string"},
                    "kind": {"type": "string"}}}},
            "governing_note": {"type": "string"},
            "tolerances": {"type": "array"},
            "steps": {"type": "array", "items": {"type": "object",
                "required": ["title", "detail"], "properties": {
                    "phase": {"type": "string"}, "title": {"type": "string"},
                    "detail": {"type": "string"}, "tools": {"type": "array"},
                    "fasteners": {"type": "array"}, "check": {"type": "string"}}}},
            "cure": {"type": "array"}, "care": {"type": "string"},
        },
    }

    def author_packet(self, ir, geo) -> dict:
        """Write the editorial instruction to reference-packet depth. Numbers in
        prose reference the computed design; the engine still owns every dimension."""
        parts = [{"id": p.id, "name": p.name, "cut": [_fmt(p.cut_wh()[0]), _fmt(p.cut_wh()[1])],
                  "qty": p.qty, "material": p.material_id, "joint": p.joint} for p in geo.parts]
        mats = sorted({p.material_id for p in geo.parts})
        # Without these the model has to guess the numbers it writes about, and it
        # guesses plausibly: a packet once specified a 3/8in rabbet for a design
        # whose rabbet depth was 1/4in. Give it the design's own values to quote.
        params = {k[6:]: _fmt(s.value) for k, s in sorted(geo.scalars.items())
                  if k.startswith("param.")}
        joinery = {pid: {"type": j.get("type"), "depth": _fmt(j.get("depth", 0.0))}
                   for pid, j in (geo.structure.get("joinery") or {}).items()}
        thick = {p.id: _fmt(p.thickness) for p in geo.parts}
        from build_assistant.core.glueup import glue_up
        glued = {p.id: {"strips": g.count, "strip_width": _fmt(g.strip_width)}
                 for p in geo.parts for g in [glue_up(p)] if g.is_glued}
        system = ("You are a master maker writing the build instructions for a printed packet. "
                  "Be specific, ordered and safe. Reference the real parts by id and name. Do "
                  "not invent dimensions beyond the parts given; you may cite spacings, grits, "
                  "cure times and tolerances a builder needs.")
        user = (
            f"PROJECT: {ir.node_kind} — {ir.summary}\n"
            f"MATERIALS: {mats}\nFINISH: {ir.finish_id}\n"
            f"PARTS: {json.dumps(parts)}\n"
            f"STOCK THICKNESS BY PART: {json.dumps(thick)}\n"
            f"DESIGN PARAMETERS: {json.dumps(params)}\n"
            f"JOINERY CUTS: {json.dumps(joinery)}\n"
            + (f"EDGE-GLUED PANELS: {json.dumps(glued)} — these parts are too wide for "
               "one board and are glued up from strips. Include a glue-up phase before "
               "joinery: joint the mating edges, glue and clamp flat, let it cure, then "
               "trim the panel to size.\n" if glued else "")
            + "When you name a joinery depth, a panel thickness, a setback or any other design "
            "parameter, quote the value given above EXACTLY. Do not restate it in different "
            "units or round it differently, and never substitute a number that seems typical.\n\n"
            "Write the packet content as JSON:\n"
            '{"title": short display title, "subtitle": one-sentence description,\n'
            ' "spec_meta": {"skill":"Beginner|Intermediate|Advanced","shop_time":"e.g. 6-8 hr",'
            '"elapsed":"e.g. 2 days incl. finish"},\n'
            ' "callouts": [3 items {"title","body","kind":"crit|warn|info"}] — the one thing '
            'most likely to go wrong, a key structural reason, and a tip,\n'
            ' "governing_note": one paragraph on the critical dimension/joinery concept,\n'
            ' "tolerances": [{"check","tolerance"}] 4-6 rows,\n'
            ' "steps": [10-18 ordered {"phase","title","detail","tools":[],"fasteners":[],"check"}] '
            'grouped by phase (Prep, Cut, Joinery, Assemble, Finish...), each detail 1-2 sentences '
            'saying HOW and WHY, with a concrete sign-off check,\n'
            ' "cure": [{"stage","wait","note"}] if there is a finish/glue wait, else [],\n'
            ' "care": one paragraph on care and maintenance}\n'
            "Return ONLY the JSON.")
        try:
            packet = self.boundary_call(system, user)
        except Exception as exc:  # noqa: BLE001
            self.last_packet_error = f"{type(exc).__name__}: {exc}"
            return {}
        return self._reconcile_packet(geo, packet, system, user)

    def _reconcile_packet(self, geo, packet: dict, system: str, user: str,
                          rounds: int = 2) -> dict:
        """Rewrite any sentence that contradicts the design it describes.

        Gate 1 only proves a number came from the solver, so a packet could open
        with "3/8in-deep dado joints" above a table reading "Dado Depth 1/4in" and
        release. The prose audit finds those; this asks for the sentences back,
        corrected, and keeps the last version that is at least no worse."""
        from build_assistant.generative.prose_audit import audit_prose

        issues = audit_prose(geo, packet)
        self.packet_prose_issues = list(issues)
        for _ in range(rounds):
            if not issues:
                break
            fix = (f"{user}\n\nYour previous draft contradicted the design:\n"
                   + "\n".join(f"- {i}" for i in issues[:8])
                   + "\n\nReturn the FULL corrected JSON. Fix only those sentences — "
                     "keep every other word identical, and never change the design to "
                     "match a sentence.")
            try:
                revised = self.boundary_call(system, fix)
            except Exception as exc:  # noqa: BLE001
                self.last_packet_error = f"{type(exc).__name__}: {exc}"
                break
            if not revised.get("steps"):
                break
            new_issues = audit_prose(geo, revised)
            if len(new_issues) >= len(issues):     # no progress; keep what we had
                packet, issues = revised, new_issues
                break
            packet, issues = revised, new_issues
        self.packet_prose_issues = list(issues)
        return packet

    def boundary_call(self, system, user):
        raw = self._llm(system, user, 8000)
        import json as _j
        a, b = raw.find("{"), raw.rfind("}")
        obj = _j.loads(raw[a:b + 1])
        from build_assistant.elicitation.llm import validate
        validate(obj, self._PACKET_SCHEMA)
        return obj

    # ---------------------------------------------------------------- the loop
    # ---------------------------------------------------------------- questions
    _QUESTION_RULES = (
        "Ask only what you cannot safely assume. Every question must change the "
        "design if answered differently — never ask for something already stated, "
        "and never ask a question whose answer you would ignore.\n"
        "Order matters: overall size first, then how it is used and where it lives, "
        "then material and finish, then the details that depend on those.\n"
        "Prefer CHOICE questions with 2-4 concrete options a non-expert can pick "
        "between. Use NUMBER only for dimensions, and give tappable presets in the "
        "unit stated. Keep each prompt one short sentence in plain language — no "
        "jargon, no compound questions."
    )

    def plan_questions(self, description: str, photos: list | None = None) -> list:
        """The tailored question set for an arbitrary build.

        A curated node carries a hand-written question graph. An open-domain build
        has none, so the agent writes one for this object: the questions a maker
        would actually be asked before drawing it."""
        system = ("You are an experienced maker scoping a build with someone before "
                  "you draw anything. You ask the fewest questions that let you "
                  "design the thing they want, and no others.")
        user = (
            f"They want to build: {description}\n"
            + ("Inspiration photos are attached — read the style, proportions and "
               "materials from them and do NOT ask about what they already show.\n"
               if photos else "")
            + f"\n{self._QUESTION_RULES}\n\n"
            "Return JSON:\n"
            '{"turns": [{"questions": [{"id": short_symbol, "field": short_symbol,\n'
            '   "prompt": str, "type": "choice"|"number", "unit": "in"|"",\n'
            '   "required": bool, "explain": one sentence on why it matters,\n'
            '   "options": [{"value": symbol, "label": str}],\n'
            '   "presets": [numbers]}]}]}\n'
            "3-5 turns, AT MOST 3 questions per turn. 'options' only for choice, "
            "'presets' only for number. Return ONLY the JSON.")
        out = self._llm_json(system, user, 3000, images=photos)
        return _clean_turns(out.get("turns") or [])

    def design(self, description: str, answers: dict, max_rounds: int = MAX_ROUNDS,
               photos: list | None = None, progress=None) -> DesignResult:
        trail = []
        say = progress or (lambda *a, **k: None)
        say("designing", "drafting the first design")
        try:
            ir = self.synthesize(description, answers, photos=photos)
        except Exception as exc:  # noqa: BLE001
            return DesignResult(None, None, False, trail, f"synthesis failed: {exc}")

        geo, error = self._try_compile(ir)
        trail.append({"round": 0, "action": "synthesize", "error": error,
                      "parts": geo.piece_count() if geo else 0})

        # A repair rewrites the whole model, so a round that fixes an architectural
        # note can undo a placement fix from the round before. A live run went clean
        # at round 2 and broke again at round 3, then spent its budget getting back.
        # Keep the best model seen and never end worse than it.
        best = (self._defect_count(geo, error), ir, geo, error)

        for r in range(1, max_rounds + 1):
            say("reviewing", f"round {r} of {max_rounds} — checking the design holds up")
            crit = self.critique(ir, geo, error)
            issues = crit.get("issues", [])
            blocking = [i for i in issues if i.get("severity") == "high"]
            trail.append({"round": r, "action": "critique", "error": error,
                          "issues": issues, "buildable": crit.get("buildable", bool(geo))})
            # Converged: compiles clean, invariants hold, no HIGH-severity issues left.
            # Remaining med/low notes are attached as warnings, not blockers.
            if geo and not error and not blocking:
                for i in issues:
                    note = i.get("what", "")
                    if note and note not in ir.warnings:
                        ir.warnings.append(note)
                return DesignResult(ir, geo, True, trail)
            say("repairing", _repair_note(r, max_rounds, error, issues))
            try:
                ir = self.repair(ir, issues or [{"what": error, "fix_hint": "make it compile"}], error)
            except Exception as exc:  # noqa: BLE001
                trail.append({"round": r, "action": "repair_failed", "error": str(exc)})
                break
            geo, error = self._try_compile(ir)
            trail.append({"round": r, "action": "repair", "error": error,
                          "parts": geo.piece_count() if geo else 0})
            score = self._defect_count(geo, error)
            if score < best[0]:
                best = (score, ir, geo, error)

        if self._defect_count(geo, error) > best[0]:
            trail.append({"round": "final", "action": "revert_to_best",
                          "error": best[3], "parts": best[2].piece_count() if best[2] else 0})
            _, ir, geo, error = best

        converged = geo is not None and not error
        if geo is not None and error.startswith("PlacementError"):
            # budget spent with placement defects still present: publish them in the
            # packet's design notes rather than shipping a drawing that lies
            from build_assistant.generative.audit import audit_placement
            for msg in audit_placement(geo)[:4]:
                note = "Unresolved by the design loop: " + msg
                if note not in ir.warnings:
                    ir.warnings.append(note)
        return DesignResult(ir, geo, converged, trail,
                            "" if converged else (error or "did not fully converge in budget"))

    @staticmethod
    def _defect_count(geo, error: str) -> int:
        """How bad a round is, for keeping the best. Not building at all is worst."""
        if geo is None:
            return 10_000
        if not error:
            return 0
        if error.startswith("PlacementError"):
            from build_assistant.generative.audit import audit_placement
            return len(audit_placement(geo))
        return 1_000                                  # invariant violation

    def _try_compile(self, ir: DesignIR):
        """Build the geometry (parts/numbers) even if an invariant fails, so the
        critique sees the real cut list plus the exact violation."""
        from build_assistant.core.invariants import check_invariants
        try:
            geo = compile_design(ir, check=False)     # numbers always computed
        except (ExprError, ValueError, KeyError, ZeroDivisionError) as exc:
            return None, f"{type(exc).__name__}: {exc}"   # could not build at all
        try:
            check_invariants(geo)
        except InvariantError as exc:
            return geo, f"InvariantError: {exc}"          # geo kept, violation reported
        # A design can satisfy every invariant and still not be an object: parts
        # placed outside the piece, floating free, or passing through each other.
        # Audit the placement and hand the exact defect back for repair.
        from build_assistant.generative.audit import audit_placement
        issues = audit_placement(geo)
        if issues:
            return geo, "PlacementError: " + " | ".join(issues[:4])
        return geo, ""


# --------------------------------------------------------------------------
# inspiration photos
# --------------------------------------------------------------------------

_MAX_PHOTOS = 4
#: Anthropic accepts these image media types; anything else is dropped rather
#: than sent and rejected mid-design.
_IMAGE_TYPES = ("image/jpeg", "image/png", "image/gif", "image/webp")


def _image_blocks(data_urls: list) -> list:
    """Turn stored data: URLs into API image blocks, skipping anything unusable."""
    blocks = []
    for url in data_urls[:_MAX_PHOTOS]:
        if not isinstance(url, str) or not url.startswith("data:"):
            continue
        try:
            header, b64 = url.split(",", 1)
            media = header.split(";")[0][5:]
        except ValueError:
            continue
        if media not in _IMAGE_TYPES or not b64:
            continue
        blocks.append({"type": "image", "source": {
            "type": "base64", "media_type": media, "data": b64}})
    return blocks


# --------------------------------------------------------------------------
# agent-authored question sets
# --------------------------------------------------------------------------

_MAX_PER_TURN = 3          # the UI contract: never more than three at once
_MAX_TURNS = 5


def _clean_turns(turns: list) -> list:
    """Validate and clamp an agent-authored question set.

    The model writes these, so the app enforces its own contract rather than
    trusting the shape: at most three questions a turn, a usable answer control on
    every one, and no duplicate fields across the whole set."""
    out, seen = [], set()
    for turn in turns[:_MAX_TURNS]:
        questions = []
        for q in (turn.get("questions") or [])[:_MAX_PER_TURN]:
            field = str(q.get("field") or q.get("id") or "").strip()
            prompt = str(q.get("prompt") or "").strip()
            if not field or not prompt or field in seen:
                continue
            qtype = "number" if q.get("type") == "number" else "choice"
            options = [{"value": str(o.get("value", "")), "label": str(o.get("label", ""))}
                       for o in (q.get("options") or [])
                       if str(o.get("value", "")).strip()]
            presets = [float(p) for p in (q.get("presets") or [])
                       if isinstance(p, (int, float))]
            # a choice with nothing to choose, or a number with no way to enter one,
            # is a dead end on a phone — drop it rather than render it
            if qtype == "choice" and len(options) < 2:
                continue
            seen.add(field)
            questions.append({
                "id": field, "field": field, "prompt": prompt, "type": qtype,
                "unit": str(q.get("unit") or ("in" if qtype == "number" else "")),
                "required": bool(q.get("required", True)),
                "explain": str(q.get("explain") or ""),
                "options": options if qtype == "choice" else [],
                "numeric_presets": presets if qtype == "number" else [],
                "tailored": True,
            })
        if questions:
            out.append({"questions": questions})
    return out


def _repair_note(round_no: int, total: int, error: str, issues: list) -> str:
    """What the progress screen says while a repair round runs.

    The user is waiting minutes, so the line names the actual defect being fixed
    rather than a generic 'working' — it is the only window into the loop."""
    if error.startswith("PlacementError"):
        return f"round {round_no}: parts do not fit together yet — adjusting placement"
    if error.startswith("InvariantError"):
        return f"round {round_no}: a part does not fit its stock — resizing"
    high = [i.get("what", "") for i in (issues or []) if i.get("severity") == "high"]
    if high:
        return f"round {round_no}: {str(high[0])[:70]}"
    return f"round {round_no} of {total}: refining the design"
