"""Intake and completeness — Phase 8, sections 7.4 and 7.5.

Intake classifies free text to one or more nodes, extracts parameters already
present and enumerates ambiguities. It **never silently picks** (7.4): any term
mapping to more than one construction is a required disambiguation question, and
unknown nodes go to a review queue rather than shipping an improvised schema.

Completeness runs **two independent judges** (7.5): a deterministic one (required
fields, invariants satisfiable, cross-field sums) and an AI one that may *request*
missing information but may **not approve**.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import LLMBoundary

_INTAKE_SCHEMA = {
    "type": "object",
    "required": ["candidates", "ambiguities", "unknown"],
    "properties": {
        "candidates": {"type": "array", "items": {
            "type": "object", "required": ["node", "confidence"],
            "properties": {"node": {"type": "string"}, "confidence": {"type": "number"}}}},
        "ambiguities": {"type": "array"},
        "unknown": {"type": "boolean"},
    },
}


@dataclass
class IntakeResult:
    candidates: list[dict]
    ambiguities: list[dict]
    unknown: bool
    review_queue: list[str] = field(default_factory=list)

    def needs_disambiguation(self) -> bool:
        return bool(self.ambiguities) or len([c for c in self.candidates if c["confidence"] >= 0.4]) > 1

    def resolved_node(self) -> str | None:
        strong = [c for c in self.candidates if c["confidence"] >= 0.7]
        if len(strong) == 1 and not self.ambiguities:
            return strong[0]["node"]
        return None


def classify(text: str, boundary: LLMBoundary, registry) -> IntakeResult:
    result = boundary.call(f"Classify this build request.\nUSER: {text}", "intake", _INTAKE_SCHEMA)
    review: list[str] = []
    if result["unknown"] or any(c["node"] == "unknown" for c in result["candidates"]):
        # AI may draft a candidate leaf, but may not ship it to a user (7.4).
        review.append(f"unknown request -> review queue: {text!r}")
    return IntakeResult(result["candidates"], result["ambiguities"], result["unknown"], review)


# --------------------------------------------------------------------------
# completeness gate — two judges
# --------------------------------------------------------------------------

@dataclass
class CompletenessVerdict:
    approved: bool
    missing_fields: list[str]
    reasons: list[str]
    judge: str


def deterministic_judge(node_id: str, answers: dict, registry) -> CompletenessVerdict:
    """Required fields present, invariants satisfiable, cross-field sums consistent."""
    from ..core.solver import solve
    schema = registry.schema(node_id)
    missing = [f for f in schema["required_fields"] if f not in answers]
    if missing:
        return CompletenessVerdict(False, missing, ["required fields absent"], "deterministic")
    reasons: list[str] = []
    try:
        solve({"node": node_id, **answers})   # invariants raise if unsatisfiable
    except Exception as exc:  # noqa: BLE001
        return CompletenessVerdict(False, [], [f"invariants unsatisfiable: {exc}"], "deterministic")
    return CompletenessVerdict(True, [], reasons or ["all checks pass"], "deterministic")


_AIJUDGE_SCHEMA = {
    "type": "object",
    "required": ["missing_fields", "reasons"],
    "properties": {
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
}


def ai_judge(node_id: str, answers: dict, boundary: LLMBoundary) -> CompletenessVerdict:
    """Scans for underspecification the schema cannot see. MAY REQUEST, NEVER APPROVE."""
    try:
        out = boundary.call(
            f"Review this spec for gaps.\nUSER: node={node_id} answers={answers}",
            "completeness", _AIJUDGE_SCHEMA)
        missing = out["missing_fields"]
        reasons = out["reasons"]
    except Exception:  # noqa: BLE001
        missing, reasons = [], ["ai judge produced no structured output"]
    # By construction the AI judge cannot approve: approved is always False; it only
    # returns control to elicitation with requests. Approval is the deterministic
    # judge's alone.
    return CompletenessVerdict(False, missing, reasons, "ai")


def completeness_gate(node_id: str, answers: dict, registry,
                      boundary: LLMBoundary | None = None) -> tuple[bool, list[CompletenessVerdict]]:
    """Both judges run. Approval requires the deterministic judge to pass; the AI
    judge can only add missing-field requests."""
    verdicts = [deterministic_judge(node_id, answers, registry)]
    if boundary is not None:
        verdicts.append(ai_judge(node_id, answers, boundary))
    det = verdicts[0]
    ai_requests = [m for v in verdicts[1:] for m in v.missing_fields]
    approved = det.approved and not ai_requests
    return approved, verdicts
