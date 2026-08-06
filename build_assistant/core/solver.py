"""The solver — Phase 1. ``solve(answers, catalog, schema) -> geometry``.

Law 2: solve is a *pure function*. Same inputs, same output, same hash. No I/O,
no randomness, no model calls. This module imports only catalog data and pure
arithmetic; it performs no file, network, time or random access.

The engine is node-agnostic: it resolves the finish offset, invokes the node's
declarative recipe, applies the shared invariant checker, and computes a stable
content hash. Adding a leaf node requires a node module and joinery data only —
no change here (Definition of Done, final item).
"""

from __future__ import annotations

import hashlib
import json

from .model import Geometry
from .invariants import check_invariants

# Node registry — the only place engine learns about leaves.
_NODES: dict[str, object] = {}


def register_node(module) -> None:
    _NODES[module.NODE_ID] = module


def get_node(node_id: str):
    if node_id not in _NODES:
        raise KeyError(f"unregistered node: {node_id!r}")
    return _NODES[node_id]


def _validate_answers(node, answers: dict) -> None:
    missing = [f for f in node.SCHEMA["required_fields"] if f not in answers]
    if missing:
        raise ValueError(f"missing required fields for {node.NODE_ID}: {missing}")


def solve(answers: dict) -> Geometry:
    """Pure: (answers) -> Geometry. Raises on any invariant violation."""
    node = get_node(answers["node"])
    _validate_answers(node, answers)

    draft = node.build(answers)

    structure = dict(draft.structure)
    structure["joints"] = draft.joints
    structure["operations"] = draft.operations
    structure["skins"] = draft.skins

    geo = Geometry(
        node=draft.node,
        elements=draft.elements,
        parts=draft.parts,
        scalars=draft.scalars,
        derived_decisions=draft.derived_decisions,
        finish_id=draft.finish_id,
        per_face_offset=draft.per_face_offset,
        inputs=dict(answers),
        structure=structure,
    )

    # Law 5 / section 2.4: invariants are hard failures, checked before release.
    check_invariants(geo)
    return geo


def solve_hash(geo: Geometry) -> str:
    """Deterministic content hash over the numeric solve output (Phase 1 acceptance)."""
    payload = {
        "node": geo.node,
        "per_face_offset": geo.per_face_offset,
        "scalars": {k: v.value for k, v in sorted(geo.scalars.items())},
        "parts": [
            [p.id, p.name, p.material_id, p.qty,
             p.length.as_cut, p.length.as_assembled, p.length.as_finished,
             p.width.as_cut, p.width.as_assembled, p.width.as_finished, p.thickness]
            for p in geo.parts
        ],
        "elements": [
            [e.id, e.carcass_height.as_cut, e.carcass_height.as_finished,
             e.finished_height.as_cut, e.finished_height.as_finished]
            for e in geo.elements
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# Register bundled nodes on import.
def _bootstrap() -> None:
    from ..nodes import coffee_table
    register_node(coffee_table)


_bootstrap()
