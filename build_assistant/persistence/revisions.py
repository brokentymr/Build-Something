"""Revisions — Phase 9, brief Part 8 / Law 4.

A revision is a new answer-set version, a **full re-solve** (partial re-solve does
not exist — Law 4), a diff against the prior revision, an incremented revision
letter and a changelog. Corrections must be published, including corrections to
corrections (Lesson 13).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.solver import solve, solve_hash


@dataclass
class RevisionDiff:
    from_letter: str
    to_letter: str
    input_changes: dict            # field -> (old, new)
    scalar_changes: dict           # field_id -> (old, new)
    hash_before: str
    hash_after: str
    changelog: list[str] = field(default_factory=list)


def revise(answer_set, changes: dict, reason: str) -> RevisionDiff:
    """Apply changes as a new version and fully re-solve, diffing the result."""
    before_answers = answer_set.answers()
    geo_before = solve(before_answers)
    hb = solve_hash(geo_before)

    prior_letter = answer_set.current.revision_letter
    version = answer_set.revise(changes, reason)   # append-only, new letter
    after_answers = answer_set.answers()
    geo_after = solve(after_answers)               # FULL re-solve (Law 4)
    ha = solve_hash(geo_after)

    input_changes = {k: (before_answers.get(k), v) for k, v in changes.items()}
    scalar_changes = {}
    keys = set(geo_before.scalars) | set(geo_after.scalars)
    for k in sorted(keys):
        a = geo_before.scalars.get(k)
        b = geo_after.scalars.get(k)
        av = a.value if a else None
        bv = b.value if b else None
        if av != bv:
            scalar_changes[k] = (av, bv)

    changelog = [f"Rev {prior_letter} -> {version.revision_letter}: {reason}"]
    for k, (o, n) in input_changes.items():
        changelog.append(f"  input {k}: {o} -> {n}")
    for k, (o, n) in list(scalar_changes.items())[:12]:
        changelog.append(f"  derived {k}: {o} -> {n}")

    return RevisionDiff(prior_letter, version.revision_letter, input_changes,
                        scalar_changes, hb, ha, changelog)
