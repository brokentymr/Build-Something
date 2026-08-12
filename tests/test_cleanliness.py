"""Editorial cleanliness of the finished packet.

The PDF is the product, so these are product requirements, not style preferences:
information must be scannable, addressed to a builder, and must earn the page
space it occupies.
"""

from __future__ import annotations

import re

from build_assistant.generative.model import DesignIR
from build_assistant.generative.compiler import compile_design
from build_assistant.generative.document import build_blocks_generic, _split_notes, _human
from build_assistant.nesting.plan import plan_nesting
from tests.test_details import _CASE


def _geo_with_notes(notes):
    spec = dict(_CASE)
    spec["warnings"] = notes
    return compile_design(DesignIR.from_dict(spec))


def test_notes_split_into_scannable_lines():
    blob = ["First thing must be done; second thing matters; Third thing too"]
    out = _split_notes(blob)
    assert len(out) >= 2, out
    assert all(len(o) > 3 for o in out)
    print(f"  [ok] semicolon blob splits into {len(out)} scannable notes")


def test_note_fragments_are_not_orphaned():
    """A lowercase clause is the tail of the previous note, not a note by itself."""
    out = _split_notes(["Use 3 lag screws into studs; total capacity 300+ lbs"])
    assert len(out) == 1, out
    assert "total capacity" in out[0]
    print("  [ok] continuation clauses rejoin instead of orphaning")


def test_internal_part_ids_never_reach_the_page():
    geo = compile_design(DesignIR.from_dict(_CASE))
    plan = plan_nesting(geo)
    packet = {
        "title": "T", "subtitle": "s",
        "callouts": [{"title": "About A", "body": "The A must seat fully."}],
        "governing_note": "A carries the load.",
        "steps": [{"phase": "Cut", "title": "Cut A", "detail": "Cut A to size.",
                   "check": "A is square"}],
        "care": "Wipe A clean.",
    }
    html = "".join(b.html for b in build_blocks_generic(geo, plan, packet))
    text = re.sub(r"<[^>]+>", " ", html)
    ids = {p.id for p in geo.parts if "_" in p.id or len(p.id) > 3}
    for pid in ids:
        assert pid not in text, f"internal id {pid!r} leaked into the page"
    print("  [ok] internal part ids never reach reader-facing text")


def test_human_swaps_ids_for_names():
    geo = compile_design(DesignIR.from_dict({
        **_CASE,
        "parts": [{**_CASE["parts"][0], "id": "side_left", "name": "Left side panel"}],
    }))
    out = _human("The side_left carries the load", geo)
    assert "side_left" not in out and "left side panel" in out
    print("  [ok] agent prose reads in part names, not symbols")


def test_cut_list_quotes_shop_practical_fractions():
    """Nobody can cut 61/64 — the cut list quotes to 1/32, inside the tolerance."""
    geo = compile_design(DesignIR.from_dict(_CASE))
    plan = plan_nesting(geo)
    html = "".join(b.html for b in build_blocks_generic(geo, plan, {}))
    cut = re.search(r'Item.*?</table>', html, re.S)
    assert cut, "cut list not found"
    assert "/64" not in cut.group(0), "cut list must not quote 64ths"
    print("  [ok] cut list quotes to 1/32, not unusable 64ths")


def test_sheet_diagrams_lie_down():
    """A tall sheet drawn upright eats a whole page for one diagram."""
    from build_assistant.drawing.drawings import nesting_diagram
    geo = compile_design(DesignIR.from_dict(_CASE))
    plan = plan_nesting(geo)
    for mid, nest in plan.nests.items():
        c = nesting_diagram(nest, 1)
        assert c.h <= c.w, f"{mid} sheet diagram is portrait ({c.w}x{c.h}) and wastes a page"
    print("  [ok] stock diagrams lie down so sheets share a page")
