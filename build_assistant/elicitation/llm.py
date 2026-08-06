"""LLM boundary — Phase 8, section 7.6.

Every model call returns JSON validated against a schema before use. Invalid output
is rejected and retried, never coerced, never loosely parsed. A call that cannot
produce valid structured output after retries fails loudly.

The model classifies intent, phrases questions and decomposes free text. It never
emits a number that reaches a user (Law 1) — numeric extraction here only *echoes
back* values the user literally typed, tagged for confirmation, and is re-validated
against the schema before it can enter an answer set.

``ModelClient`` is injectable. :class:`DeterministicStubClient` implements the
contract with rule-based logic so the whole pipeline runs and is tested offline;
a real client swaps in without changing any caller.
"""

from __future__ import annotations

import json
from typing import Protocol


class LLMBoundaryError(RuntimeError):
    """A model call failed to produce schema-valid JSON after retries."""


class ModelClient(Protocol):
    def complete(self, prompt: str, purpose: str) -> str:  # returns raw text
        ...


# --------------------------------------------------------------------------
# minimal JSON-schema validation (types / required / enum) — stdlib only
# --------------------------------------------------------------------------

def validate(obj, schema: dict, path: str = "$") -> None:
    t = schema.get("type")
    if t == "object":
        if not isinstance(obj, dict):
            raise LLMBoundaryError(f"{path}: expected object")
        for req in schema.get("required", []):
            if req not in obj:
                raise LLMBoundaryError(f"{path}: missing required {req!r}")
        props = schema.get("properties", {})
        for k, v in obj.items():
            if k in props:
                validate(v, props[k], f"{path}.{k}")
    elif t == "array":
        if not isinstance(obj, list):
            raise LLMBoundaryError(f"{path}: expected array")
        item_schema = schema.get("items")
        if item_schema:
            for i, it in enumerate(obj):
                validate(it, item_schema, f"{path}[{i}]")
    elif t == "number":
        if not isinstance(obj, (int, float)) or isinstance(obj, bool):
            raise LLMBoundaryError(f"{path}: expected number")
    elif t == "string":
        if not isinstance(obj, str):
            raise LLMBoundaryError(f"{path}: expected string")
        if "enum" in schema and obj not in schema["enum"]:
            raise LLMBoundaryError(f"{path}: {obj!r} not in enum")
    elif t == "boolean":
        if not isinstance(obj, bool):
            raise LLMBoundaryError(f"{path}: expected boolean")


class LLMBoundary:
    """Wraps a ModelClient with strict JSON parsing, validation and retries."""

    def __init__(self, client: ModelClient, retries: int = 2):
        self.client = client
        self.retries = retries

    def call(self, prompt: str, purpose: str, schema: dict) -> dict:
        last = None
        for _ in range(self.retries + 1):
            raw = self.client.complete(prompt, purpose)
            try:
                obj = json.loads(raw)
                validate(obj, schema)
                return obj
            except (json.JSONDecodeError, LLMBoundaryError) as exc:
                last = exc
        raise LLMBoundaryError(f"{purpose}: no schema-valid output after "
                               f"{self.retries + 1} attempts ({last})")


# --------------------------------------------------------------------------
# deterministic stub client — rule-based, offline, no numbers invented
# --------------------------------------------------------------------------

# Terms that map to more than one construction MUST be disambiguated (7.4).
_AMBIGUOUS_TERMS = {
    "micro concrete": [
        {"construction": "troweled_overlay", "note": "2–3 mm troweled microcement over a board substrate"},
        {"construction": "cast_slab", "note": "1.25–1.5 in cast concrete slab"},
    ],
    "microcement": [
        {"construction": "troweled_overlay", "note": "2–3 mm troweled overlay"},
        {"construction": "cast_slab", "note": "cast slab (heavier, different base load)"},
    ],
}


class DeterministicStubClient:
    """Rule-based stand-in for a language model. Returns schema-shaped JSON.

    It classifies by keyword, extracts only numbers the text literally contains,
    and flags ambiguous terms. It never computes a dimension.
    """

    def __init__(self, registry):
        self.registry = registry

    def complete(self, prompt: str, purpose: str) -> str:
        text = _extract_user_text(prompt).lower()
        if purpose == "intake":
            return json.dumps(self._intake(text))
        if purpose == "decompose":
            return json.dumps(self._decompose(text))
        raise ValueError(f"stub client has no rule for purpose {purpose!r}")

    def _intake(self, text: str) -> dict:
        candidates = []
        for leaf in self.registry.all_leaves():
            hits = self.registry.resolve_aliases(leaf) + [leaf]
            score = sum(1 for h in hits if h.replace("_", " ") in text or h in text)
            if score:
                candidates.append({"node": leaf, "confidence": min(0.99, 0.5 + 0.2 * score)})
        # folder-level phrases yield several candidate leaves (must decompose)
        if not candidates:
            for tid in ("living_room_furniture",):
                if any(a in text for a in ("living room", "table for my")):
                    for child in ("coffee_table", "floating_shelf"):
                        candidates.append({"node": child, "confidence": 0.4})
        ambiguities = []
        for term, constructions in _AMBIGUOUS_TERMS.items():
            if term in text:
                ambiguities.append({"term": term, "constructions": constructions})
        return {
            "candidates": candidates or [{"node": "unknown", "confidence": 0.0}],
            "ambiguities": ambiguities,
            "unknown": not candidates,
        }

    def _decompose(self, text: str) -> dict:
        """Decompose free text into schema fields it can see literally (7.3)."""
        fields = {}
        import re
        m = re.findall(r"(\d+(?:\.\d+)?)\s*(?:in|inch|\")?", text)
        # only structural keywords map words->fields; numbers stay as typed
        if "plinth" in text:
            fields["base_type"] = "plinth"
        if "matte" in text:
            fields["finish_sheen"] = "matte"
        if "microcement" in text or "micro concrete" in text:
            fields["finish_system"] = "microcement_over_cement_board"
        return {"fields": fields, "raw_numbers": m}


def _extract_user_text(prompt: str) -> str:
    marker = "USER:"
    return prompt.split(marker, 1)[1] if marker in prompt else prompt
