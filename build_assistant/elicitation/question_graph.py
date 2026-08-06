"""Question graph — Phase 7, brief section 7.2.

Not a form. A graph traversal, because answers open questions that did not
previously exist. The UI contract is enforced *in code*, not by prompt guidance
(Lesson 10): at most 3 questions per turn, 2–4 mutually exclusive options each,
numeric fields as presets + a custom escape, and always an unsure path.

Ordering principle: **geometric impact before appearance** (section 7.2). Questions
that change the cut list come first, so a user can stop early and still hold a
buildable spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_QUESTIONS_PER_TURN = 3
MIN_OPTIONS = 2
MAX_OPTIONS = 4


class UIContractError(ValueError):
    """A question or batch violates the hard UI contract (Lesson 10)."""


@dataclass(frozen=True)
class Option:
    value: object
    label: str


@dataclass(frozen=True)
class Question:
    id: str
    field: str
    prompt: str
    type: str                       # choice | numeric
    options: tuple[Option, ...]
    required: bool
    downstream_impact: int          # higher = earlier (geometric before appearance)
    condition: object = None        # callable(answers) -> bool, or None
    opens: tuple[str, ...] = ()     # question ids unlocked by an answer
    explain_on_request: str = ""    # tradeoff text for "unsure"
    numeric_presets: tuple = ()      # presets for numeric fields
    unit: str = "in"

    def __post_init__(self):
        if self.type == "choice":
            n = len(self.options)
            if not (MIN_OPTIONS <= n <= MAX_OPTIONS):
                raise UIContractError(
                    f"question {self.id}: {n} options (must be {MIN_OPTIONS}–{MAX_OPTIONS})")
        if self.type == "numeric" and not self.numeric_presets:
            raise UIContractError(
                f"question {self.id}: numeric field needs presets + custom escape, "
                "never a bare input (Lesson 10)")


@dataclass
class Turn:
    """A batch of at most 3 questions plus an always-available unsure path."""

    questions: list[Question]

    def __post_init__(self):
        if len(self.questions) > MAX_QUESTIONS_PER_TURN:
            raise UIContractError(
                f"{len(self.questions)} questions in a turn (max {MAX_QUESTIONS_PER_TURN})")


class QuestionGraph:
    """Traverses a node's questions in geometric-impact order, honouring conditions."""

    def __init__(self, questions: list[Question]):
        self._by_id = {q.id: q for q in questions}
        self._questions = questions

    def _available(self, answers: dict) -> list[Question]:
        out = []
        for q in self._questions:
            if q.field in answers:
                continue
            if q.condition is not None and not q.condition(answers):
                continue
            out.append(q)
        # geometric impact before appearance; stable by id for determinism
        out.sort(key=lambda q: (-q.downstream_impact, q.id))
        return out

    def next_turn(self, answers: dict) -> Turn | None:
        """The next batch of <=3 questions, or None when nothing remains."""
        avail = self._available(answers)
        if not avail:
            return None
        return Turn(avail[:MAX_QUESTIONS_PER_TURN])

    def unanswered_required(self, answers: dict) -> list[str]:
        return [q.field for q in self._questions
                if q.required and q.field not in answers
                and (q.condition is None or q.condition(answers))]

    def is_complete(self, answers: dict) -> bool:
        return not self.unanswered_required(answers)
