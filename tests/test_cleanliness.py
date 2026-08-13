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


def test_short_ids_and_material_ids_never_reach_the_page():
    """The tolerance table once read "Dado depth in S1 and S2", and a step cited
    "3/4in birch plywood (ply_075_birch)". Short ids and material ids leak too."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p, new in zip(spec["parts"], ("S1", "S2", "SH1", "BACK")):
        p["id"] = new
    geo = compile_design(DesignIR.from_dict(spec))
    packet = {
        "title": "T", "subtitle": "s", "callouts": [],
        "governing_note": "Dado depth in S1 and S2 governs SH1.",
        "tolerances": [{"check": "Dado depth in S1 and S2", "tolerance": "1/64"}],
        "steps": [{"phase": "Cut", "title": "Cut SH1",
                   "detail": "Cut SH1 from ply_075_structural stock; seat into S1.",
                   "check": "BACK sits flush"}],
        "care": "Wipe S1 clean.",
    }
    text = re.sub(r"<svg.*?</svg>", " ", "".join(
        b.html for b in build_blocks_generic(geo, plan_nesting(geo), packet)), flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    for leak in ("S1", "S2", "SH1", "BACK", "ply_075_structural"):
        assert not re.search(rf"\b{leak}\b", text), f"{leak!r} leaked into the page"
    print("  [ok] short part ids and material ids are resolved to real names")


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


def test_runhead_survives_a_missing_dimension_line():
    """str.strip takes a SET of characters, so trimming " &middot;" off a runhead
    with no dims ate the kind itself: "case good" printed as "case g"."""
    from build_assistant.generative.document import build_generic_document
    geo = compile_design(DesignIR.from_dict({**_CASE, "node_kind": "case_good"}))
    doc = build_generic_document(geo, plan_nesting(geo), {"title": "T", "steps": []},
                                 out_name="_runhead_probe")
    assert "case good" in doc["html"], "the kind must survive into the runhead whole"
    assert "case g<" not in doc["html"] and "case g " not in doc["html"]
    print("  [ok] the runhead keeps the whole kind, with or without dimensions")


def test_cut_list_tells_the_shop_a_panel_is_glued_up():
    """A 12in solid panel is one row in the cut list but four strips at the saw.
    Quoting only the panel sends the builder looking for a board that wide."""
    spec = {**_CASE, "materials": [{"role": "carcass", "material_id": "hardwood_4_4"},
                                   {"role": "back", "material_id": "ply_025"}]}
    geo = compile_design(DesignIR.from_dict(spec))
    html = "".join(b.html for b in build_blocks_generic(geo, plan_nesting(geo), {}))
    assert "glue up from" in html, "the cut list must call out the glue-up"
    assert "trim to size" in html
    print("  [ok] the cut list carries the glue-up and its strip width")


def test_nesting_buys_strips_not_impossible_boards():
    from build_assistant.core.glueup import glue_up
    spec = {**_CASE, "materials": [{"role": "carcass", "material_id": "hardwood_4_4"},
                                   {"role": "back", "material_id": "ply_025"}]}
    geo = compile_design(DesignIR.from_dict(spec))
    plan = plan_nesting(geo)
    hardwood = plan.nests["hardwood_4_4"]
    widths = [min(p.w, p.h) for s in hardwood.sheets for p in s.placements]
    assert widths and max(widths) <= 8.0 + 1e-6, f"a piece wider than any board: {max(widths)}"
    side = next(p for p in geo.parts if p.id == "A")
    assert glue_up(side).count >= 2
    print("  [ok] nesting places glue-up strips, all within real board widths")


def test_one_pipeline_serves_curated_nodes_too():
    """There were two document builders and the app shipped the older one: it
    printed raw operation ids in a reader-facing column and had no sections or
    joint details at all. A curated node now goes through the same pipeline."""
    import json, os
    from build_assistant.core.solver import solve
    from build_assistant.document.curated_packet import curated_packet
    from build_assistant.generative.document import build_generic_document, generic_drawings
    fixture = os.path.join(os.path.dirname(__file__), "..", "fixtures",
                           "coffee_table_reference.json")
    geo = solve(json.load(open(fixture)))
    plan = plan_nesting(geo)
    doc = build_generic_document(geo, plan, curated_packet(geo, plan), out_name="_unified_probe")

    drawings = generic_drawings(geo, plan)
    for want in ("exploded", "section_aa", "section_bb", "joint_d1", "predrill"):
        assert want in drawings, f"the curated packet is missing {want}"

    body = re.sub(r"<svg.*?</svg>", " ", doc["html"], flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    leaks = sorted(set(re.findall(r"\b[a-z]+_[a-z_]{3,}\b", body)))
    assert not leaks, f"ids reached the page: {leaks}"

    for kept in ("The allowance layer", "plinth reads two heights", "Troubleshooting"):
        assert kept in doc["html"], f"node-specific content lost: {kept}"
    print(f"  [ok] curated node builds through the one pipeline: "
          f"{doc['page_count']}pp, {len(drawings)} drawings, no id leaks")


def test_a_node_without_a_sequence_recipe_still_releases():
    """build_sequence is written against the coffee table's scalars, so the shelf
    node crashed document generation outright — in both old pipelines."""
    from build_assistant.core.solver import solve
    from build_assistant.document.curated_packet import curated_packet
    geo = solve({"node": "floating_shelf", "overall_length": 36, "overall_depth": 10,
                 "overall_thickness": 2.5, "finish_system": "paint_buildup"})
    packet = curated_packet(geo, plan_nesting(geo))
    assert packet["steps"] == [], "expected no sequence for a node without a recipe"
    assert packet["extra_sections"], "the node still gets its tool and cure tables"
    print("  [ok] a node with no sequence recipe produces a packet instead of a crash")


def test_a_node_without_a_recipe_gets_its_sequence_written():
    """Releasing without a build order is honest but it is a worse document than the
    same engine writes for a design it drew itself. Given the packet writer, a
    curated node with no recipe gets one from its own geometry."""
    from build_assistant.core.solver import solve
    from build_assistant.document.curated_packet import curated_packet
    geo = solve({"node": "floating_shelf", "overall_length": 36, "overall_depth": 10,
                 "overall_thickness": 2.5, "finish_system": "paint_buildup"})
    seen = {}

    def author(ir, g):
        seen["ir"], seen["node"] = ir, g.node
        return {"steps": [{"phase": "Cut", "title": "Cut the decks", "detail": "d",
                           "tools": [], "fasteners": [], "check": "square"}],
                "title": "Floating shelf"}

    packet = curated_packet(geo, plan_nesting(geo), author)
    assert seen["ir"] is None and seen["node"] == "floating_shelf"
    assert len(packet["steps"]) == 1 and packet["title"] == "Floating shelf"
    assert packet["extra_sections"], "the derived tables are still there"
    # a writer that fails must not take the document down with it
    def boom(ir, g):
        raise RuntimeError("no")
    assert curated_packet(geo, plan_nesting(geo), boom)["steps"] == []
    print("  [ok] a node with no recipe has its build sequence written for it")
