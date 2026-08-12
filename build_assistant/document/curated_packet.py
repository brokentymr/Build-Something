"""Curated nodes as input to the one document pipeline.

There used to be two packet builders. The curated one hardcoded this node's
narrative and its own figures; the generic one worked for any object and carried
every editorial and drawing improvement. Two builders meant two quality bars, and
the one the app shipped was the older of them — it printed raw operation ids in a
reader-facing column and had no sections or joint details at all.

So a curated node now supplies the same thing the design agent supplies: a packet
of authored content. Its node-specific writing — the allowance layer, the plinth
reading two heights, the QC checklist, the troubleshooting table — travels as
extra sections rather than as a second pipeline. One assembly path, one quality
bar, and anything fixed for one generation is fixed for every generation.
"""

from __future__ import annotations

from ..core.model import Geometry
from ..nesting.plan import NestingPlan
from ..build_mode.sequence import build_sequence
from .content import (
    _allowance_prose, _stage_prose, _qc_table, _troubleshooting_table,
    _care_prose, _tool_table, _cure_table, _correction_table, _derived_table,
    _cover_callouts, _spec_table, _h,
)


def _text(html: str) -> str:
    """Strip tags from a curated prose block so it can ride in the packet."""
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def curated_packet(geo: Geometry, plan: NestingPlan) -> dict:
    """The authored half of a curated node's packet, in the agent's schema.

    Node-specific writing is exactly that — specific. A node with none of its own
    still gets the sequence, the callouts and the care notes, which are derived
    from its geometry, and the rest of the packet comes from the shared pipeline."""
    if geo.node == "coffee_table":
        return _coffee_table_packet(geo, plan)
    return {"steps": _steps(geo, plan), "care": _text(_care_prose()),
            "extra_sections": [
                {"title": "Tool and bit schedule", "html": _tool_table(geo)},
                {"title": "Cure schedule", "kicker": "mostly waiting",
                 "html": _cure_table()},
            ]}


def _steps(geo: Geometry, plan: NestingPlan) -> list[dict]:
    """Phased steps, when this node has a sequence recipe.

    build_sequence is written against the coffee table's scalars, so any other node
    has no sequence at all — which used to crash document generation outright. An
    empty sequence produces a packet without a build order, which is honest and
    releasable, rather than a stack trace."""
    steps = []
    try:
        sequence = build_sequence(geo, plan)
    except (KeyError, AttributeError):
        return []
    for st in sequence:
        steps.append({
            "phase": st.phase, "title": st.title, "detail": st.detail,
            "tools": list(st.tools), "fasteners": list(st.fasteners),
            "check": st.sign_off,
            **({"tolerance": st.tolerance} if st.tolerance else {}),
        })
    return steps


def _coffee_table_packet(geo: Geometry, plan: NestingPlan) -> dict:
    steps = _steps(geo, plan)

    callouts = []
    for block in _cover_callouts(geo).split('<div class="callout')[1:]:
        title = _between(block, '<span class="ct">', "</span>")
        body = _between(block, "<p>", "</p>")
        if title and body:
            callouts.append({"title": title, "body": body, "kind": "crit"})

    return {
        "title": "Micro-cement coffee table",
        "subtitle": "Torsion-box slab on a recessed plinth, coated as one monolith.",
        "spec_meta": {"skill": "Intermediate", "shop_time": "10-14 hr",
                      "elapsed": "6 days incl. cure"},
        "callouts": callouts,
        "governing_note": _text(_allowance_prose(geo)),
        "steps": steps,
        "care": _text(_care_prose()),
        # Node-specific sections the generic packet has no slot for. Each is
        # rendered verbatim after the build sequence, in this order.
        "extra_sections": [
            {"title": "Derived specification", "kicker": "computed, not asked",
             "where": "spec", "kind": "table", "html": _spec_table(geo)},
            {"title": "The allowance layer", "kicker": "why cut is not finished",
             "html": _allowance_prose(geo)},
            {"title": "Critical detail — the plinth reads two heights",
             "kicker": "as cut vs as finished", "html": _stage_prose(geo)},
            {"title": "Tool and bit schedule", "html": _tool_table(geo)},
            {"title": "Cure schedule", "kicker": "mostly waiting", "html": _cure_table()},
            {"title": "Final QC checklist", "html": _qc_table(geo)},
            {"title": "Troubleshooting", "html": _troubleshooting_table()},
            {"title": "Derived, not asked", "html": _derived_table(geo)},
            {"title": "Correction log", "html": _correction_table()},
        ],
    }


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i + len(start):j].strip() if j > 0 else ""
