"""Answer sets — Phase 9, brief Part 8 / Law 3.

Answer sets are **append-only**. Revisions create new versions; nothing is
mutated. Hand-editing a value at the data layer is not possible by construction:
:class:`AnswerSet` exposes no setter, ``answers`` returns a copy, and the only way
to change a value is :meth:`revise`, which mints a new version.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AnswerVersion:
    version: int
    revision_letter: str
    answers: dict
    note: str

    def hash(self) -> str:
        blob = json.dumps(self.answers, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


class AnswerSet:
    """An append-only stack of answer versions."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self._versions: list[AnswerVersion] = [AnswerVersion(0, "A", {"node": node_id}, "created")]

    # ---- reads (always copies; no live handle to mutate) ----
    @property
    def current(self) -> AnswerVersion:
        return self._versions[-1]

    def answers(self) -> dict:
        return copy.deepcopy(self.current.answers)

    def history(self) -> list[AnswerVersion]:
        return list(self._versions)

    # ---- the only mutation path: append a new version ----
    def append_turn(self, new_answers: dict, note: str = "elicitation turn") -> AnswerVersion:
        """Add answers from a turn. Existing values are never overwritten silently;
        a changed value is only allowed through :meth:`revise`."""
        cur = self.current.answers
        conflict = [k for k, v in new_answers.items() if k in cur and cur[k] != v]
        if conflict:
            raise ValueError(
                f"append cannot overwrite existing answers {conflict}; use revise()")
        merged = {**cur, **new_answers}
        v = AnswerVersion(self.current.version + 1, self.current.revision_letter,
                          merged, note)
        self._versions.append(v)
        return v

    def revise(self, changes: dict, reason: str) -> AnswerVersion:
        """Change one or more values -> new version with an incremented revision letter."""
        merged = {**self.current.answers, **changes}
        letter = chr(ord(self.current.revision_letter) + 1)
        v = AnswerVersion(self.current.version + 1, letter, merged, reason)
        self._versions.append(v)
        return v
