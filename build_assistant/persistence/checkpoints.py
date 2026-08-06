"""Checkpoints and resume — Phase 9, brief Part 8.

Checkpoints are written after: job confirmation, rough dimensions, every turn of
configuration, the completeness gate, solve, geometry, document release, and every
build-step sign-off.

Resume replays the answer set into the schema to find the next unanswered field,
re-enters the correct loop position, and **restates what is already known** before
asking anything new.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

CHECKPOINT_STAGES = (
    "job_confirmed", "rough_dimensions", "configuration_turn", "completeness_gate",
    "solve", "geometry", "document_release", "build_step_signoff",
)


@dataclass
class Checkpoint:
    stage: str
    version: int
    revision_letter: str
    answers: dict
    payload: dict


class Checkpointer:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._log: list[Checkpoint] = []

    def write(self, stage: str, answer_set, payload: dict | None = None) -> Checkpoint:
        if stage not in CHECKPOINT_STAGES:
            raise ValueError(f"unknown checkpoint stage {stage!r}")
        cur = answer_set.current
        cp = Checkpoint(stage, cur.version, cur.revision_letter, dict(cur.answers), payload or {})
        self._log.append(cp)
        with open(self.path, "w") as fh:
            json.dump([_c2d(c) for c in self._log], fh, indent=2)
        return cp

    def log(self) -> list[Checkpoint]:
        return list(self._log)


def _c2d(c: Checkpoint) -> dict:
    return {"stage": c.stage, "version": c.version, "revision_letter": c.revision_letter,
            "answers": c.answers, "payload": c.payload}


def resume(path: str, registry):
    """Return (node_id, answers, next_fields, restated) from the latest checkpoint."""
    with open(path) as fh:
        log = json.load(fh)
    last = log[-1]
    answers = last["answers"]
    node_id = answers["node"]
    graph = registry.question_graph(node_id)
    next_turn = graph.next_turn(answers)
    next_fields = [q.field for q in next_turn.questions] if next_turn else []
    restated = {k: v for k, v in answers.items() if k != "node"}
    return node_id, answers, next_fields, restated
