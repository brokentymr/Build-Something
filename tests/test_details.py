"""Detail-drawing tests — sections, joint closeups, predrills, board layouts.

Deterministic (no API key): a hand-placed design exercises the contact finder and
every detail view, and asserts the drawings stay inside their canvas — the class
of defect Gate 3 exists to catch (Lesson 6/9).
"""

from __future__ import annotations

from build_assistant.generative.model import DesignIR
from build_assistant.generative.compiler import compile_design
from build_assistant.generative.detail import (
    find_contacts, cross_section, joint_detail, predrill_chart, detail_drawings,
    board_layout, pick_fastener,
)
from build_assistant.generative.draw import hero_drawings
from build_assistant.nesting.plan import plan_nesting

_CASE = {
    "name": "Case", "summary": "test case", "node_kind": "cabinet", "finish_id": "none",
    "params": [{"id": "width", "label": "W", "value": 30},
               {"id": "height", "label": "H", "value": 48},
               {"id": "depth", "label": "D", "value": 12}],
    "materials": [{"role": "carcass", "material_id": "ply_075_structural"},
                  {"role": "back", "material_id": "ply_025"}],
    "elements": [{"id": "case", "kind": "carcass", "length_expr": "width",
                  "width_expr": "depth", "height_expr": "height", "faces": []}],
    "parts": [
        {"id": "A", "name": "left side", "element": "case", "material_role": "carcass",
         "length_expr": "height", "width_expr": "depth - back_t", "qty_expr": "1",
         "box_x": "0", "box_y": "0", "box_z": "0",
         "box_w": "carcass_t", "box_d": "depth - back_t", "box_h": "height"},
        {"id": "B", "name": "right side", "element": "case", "material_role": "carcass",
         "length_expr": "height", "width_expr": "depth - back_t", "qty_expr": "1",
         "box_x": "width - carcass_t", "box_y": "0", "box_z": "0",
         "box_w": "carcass_t", "box_d": "depth - back_t", "box_h": "height"},
        {"id": "C", "name": "shelf", "element": "case", "material_role": "carcass",
         "length_expr": "width - 2*carcass_t", "width_expr": "depth - back_t", "qty_expr": "2",
         "box_x": "carcass_t", "box_y": "0", "box_z": "12",
         "box_w": "width - 2*carcass_t", "box_d": "depth - back_t", "box_h": "carcass_t",
         "step_z": "14"},
        {"id": "D", "name": "back", "element": "case", "material_role": "back",
         "length_expr": "width", "width_expr": "height", "qty_expr": "1", "grain": "none",
         "box_x": "0", "box_y": "depth - back_t", "box_z": "0",
         "box_w": "width", "box_d": "back_t", "box_h": "height"},
    ],
    "invariants": [], "derived": [], "operations": ["rip_sheet_goods"],
}


def _geo():
    return compile_design(DesignIR.from_dict(_CASE))


def test_contacts_found_and_deduped():
    cs = find_contacts(_geo())
    assert cs, "expected part contacts from the placement"
    # left/right side-to-shelf are the same joint mirrored -> one entry, typical of 2
    mirrored = [c for c in cs if c.get("count", 1) > 1]
    assert mirrored, "structurally identical joints must collapse to one detail"
    for c in cs:
        assert c["axis"] in ("x", "y", "z")
        assert len(c["overlap"]) == 2
    print(f"  [ok] {len(cs)} distinct joints found, mirrors collapsed")


def test_cross_section_cuts_real_parts():
    geo = _geo()
    c = cross_section(geo, "y")
    assert c is not None
    svg = c.render()
    # parts the plane passes through are labelled by name, keyed by item number
    for name in ("left side", "shelf"):
        assert name in svg, f"section missing {name!r}"
    assert not c.overflowing_labels() and not c.geometry_overflow()
    print("  [ok] cross-section cuts real parts, labelled, in bounds")


def test_section_shows_machined_profile():
    """A dado must read the same in the section as in the joint detail: the housed
    part seated into its housing, not floating against it."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in spec["parts"]:
        if p["id"] in ("A", "B"):
            p["joint_type"] = "dado"
            p["joint_depth_expr"] = "carcass_t/3"
    geo = compile_design(DesignIR.from_dict(spec))
    plain = compile_design(DesignIR.from_dict(_CASE))

    def rect_sizes(g):
        c = cross_section(g, "y")
        import re
        # capture the geometry attrs specifically (not stroke-width)
        return sorted((round(float(m.group(1)), 2), round(float(m.group(2)), 2))
                      for m in re.finditer(r'width="([\d.]+)" height="([\d.]+)"', c.render()))

    seated, butt = rect_sizes(geo), rect_sizes(plain)
    assert seated != butt, "seating a part in a dado must change the section geometry"
    c = cross_section(geo, "y")
    assert not c.overflowing_labels() and not c.geometry_overflow()
    print("  [ok] section seats housed parts into their dado, in bounds")


def test_joint_detail_has_fastener_and_pilot():
    geo = _geo()
    c = joint_detail(geo, find_contacts(geo)[0], "D1")
    assert c is not None
    svg = c.render()
    assert "pilot" in svg or "self-drilling" in svg, "joint detail must call out the pilot"
    assert "drive:" in svg, "joint detail must name the driver bit"
    assert not c.overflowing_labels() and not c.geometry_overflow()
    print("  [ok] joint detail carries fastener, pilot and driver, in bounds")


def test_dado_profile_is_cut_and_called_out():
    """A housing member with a dado must show the real machined profile, and the
    housed member must seat into it — not a plain butt contact."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in spec["parts"]:
        if p["id"] in ("A", "B"):
            p["joint_type"] = "dado"
            p["joint_depth_expr"] = "carcass_t/3"
    geo = compile_design(DesignIR.from_dict(spec))
    assert geo.structure["joinery"]["A"]["type"] == "dado"
    depth = geo.structure["joinery"]["A"]["depth"]
    assert 0.2 < depth < 0.3, depth       # 3/4 stock / 3

    contact = next(c for c in find_contacts(geo)
                   if "A" in (c["a"]["id"], c["b"]["id"]) and "C" in (c["a"]["id"], c["b"]["id"]))
    c = joint_detail(geo, contact, "D1")
    svg = c.render()
    assert "dado" in svg, "the joint detail must call out the housing cut"
    assert "<polygon" in svg, "the housing member must be drawn notched, not as a plain rect"
    assert not c.overflowing_labels() and not c.geometry_overflow()
    print(f"  [ok] dado profile cut {depth:.3f} deep, housed part seated, called out")


def test_butt_joint_has_no_notch_callout():
    geo = _geo()          # no joint_type set -> plain butt
    assert geo.structure.get("joinery") == {}
    c = joint_detail(geo, find_contacts(geo)[0], "D1")
    assert "dado" not in c.render()
    print("  [ok] butt joints draw without a machined profile")


def test_fastener_choice_respects_substrate():
    # cement board forbids the cabinet screw; a legal fastener must be chosen
    f = pick_fastener(0.25, "cement_board")
    assert f is not None and "cement_board" not in f.substrate_forbidden
    print(f"  [ok] fastener choice respects substrate ({f.display_name})")


def test_predrill_chart():
    c = predrill_chart(_geo())
    assert c is not None and not c.overflowing_labels() and not c.geometry_overflow()
    print("  [ok] predrill chart renders in bounds")


def test_board_layout_for_long_stock():
    """A 2x4 frame: parts must draw as a linear cut run, not a sliver."""
    frame = {
        "name": "Frame", "summary": "t", "node_kind": "frame", "finish_id": "none",
        "params": [{"id": "len", "label": "L", "value": 30}],
        "materials": [{"role": "stud", "material_id": "lumber_2x4"}],
        "elements": [{"id": "f", "kind": "frame", "length_expr": "len",
                      "width_expr": "3.5", "height_expr": "3.5", "faces": []}],
        "parts": [{"id": "A", "name": "rail", "element": "f", "material_role": "stud",
                   "length_expr": "len", "width_expr": "3.5", "qty_expr": "2",
                   "box_x": "0", "box_y": "0", "box_z": "0",
                   "box_w": "len", "box_d": "3.5", "box_h": "stud_t", "step_z": "3.5"}],
        "invariants": [], "derived": [], "operations": ["crosscut_panels"],
    }
    geo = compile_design(DesignIR.from_dict(frame))
    nest = plan_nesting(geo).nests["lumber_2x4"]
    c = board_layout(nest, 1)
    assert not c.overflowing_labels() and not c.geometry_overflow()
    print("  [ok] long stock draws as a linear cut run, in bounds")


def test_all_drawings_in_bounds():
    geo = _geo()
    every = {**hero_drawings(geo), **detail_drawings(geo)}
    assert len(every) >= 6
    for name, c in every.items():
        assert not c.overflowing_labels(), f"{name} label overflow"
        assert not c.geometry_overflow(), f"{name} geometry overflow"
        assert c.stage in ("as_cut", "as_assembled", "as_finished"), name
    print(f"  [ok] all {len(every)} hero + detail drawings in bounds, stage-tagged")


def test_designer_directed_section():
    """The designer picks where to slice and why; the engine draws exactly that."""
    spec = {**_CASE, "sections": [
        {"tag": "C-C", "axis": "z", "at_expr": "12.5",
         "why": "through the shelf line, to show the housings"}]}
    geo = compile_design(DesignIR.from_dict(spec))
    assert geo.structure["sections"][0]["at"] == 12.5
    d = detail_drawings(geo)
    secs = [k for k in d if k.startswith("section_")]
    assert secs, "a directed section must be drawn"
    svg = d[secs[0]].render()
    assert "C-C" in svg, "the designer's section tag must appear"
    assert "through the shelf line" in svg, "the reason must be shown to the builder"
    assert not d[secs[0]].overflowing_labels() and not d[secs[0]].geometry_overflow()
    print("  [ok] designer-directed section drawn at its chosen plane, with its reason")


def test_section_labels_track_the_drawing_and_title_is_whole():
    """A tall, narrow section must not strand its labels across dead space, and a
    long designer-written reason must read whole rather than clip to an ellipsis."""
    import re
    why = "through the centre showing shelf span and back panel attachment"
    spec = {**_CASE, "sections": [
        {"tag": "B-B", "axis": "x", "at_expr": "width/2", "why": why}]}
    geo = compile_design(DesignIR.from_dict(spec))
    c = next(v for k, v in detail_drawings(geo).items() if k.startswith("section_"))
    svg = c.render()

    assert why in svg, "the designer's reason must appear in full"
    assert "…" not in svg, "nothing in a section may be clipped to an ellipsis"

    # the section here is 12in deep against 48in tall, so it draws as a slim
    # column: the label gutter must follow it left instead of sitting at 306
    xs = [float(m) for m in re.findall(r'<text x="([\d.]+)"[^>]*text-anchor="start"', svg)]
    leaders = [x for x in xs if x > _MARGIN_GUESS]
    assert leaders and min(leaders) < 300, f"labels stranded right: {sorted(leaders)[:3]}"
    assert not c.overflowing_labels() and not c.geometry_overflow()
    print("  [ok] section gutter follows the geometry, title and reason read whole")


_MARGIN_GUESS = 40.0


def test_auto_section_fallback_when_undirected():
    geo = compile_design(DesignIR.from_dict(_CASE))   # no sections authored
    assert geo.structure.get("sections") == []
    d = detail_drawings(geo)
    assert any(k.startswith("section_") for k in d), "engine must still pick a cut"
    print("  [ok] engine falls back to choosing the cut when none is directed")


def test_elevation_draws_far_parts_first():
    """Without depth ordering the back panel lands on top of the shelves and a
    front elevation reads as one blank filled rectangle."""
    import re
    from build_assistant.generative.draw import front_elevation, _SHADES
    geo = _geo()
    # shades are assigned per part in first-appearance order: A, B, C, D(back)
    back_shade = _SHADES[3]
    fills = re.findall(r'<rect[^>]*fill="(#[0-9a-fA-F]+)"', front_elevation(geo).render())
    body = [f for f in fills if f.lower() not in ("#fff", "#111")]   # page, stage badge
    assert body, "elevation drew nothing"
    assert body[0].lower() == back_shade.lower(), \
        f"the back panel must be drawn first, not {body[0]}"
    assert body[-1].lower() != back_shade.lower(), "the back must not cover the shelves"
    print("  [ok] elevations draw far parts first, so the structure shows")


def test_plan_reads_as_a_cut_not_a_lid():
    """A literal top view is the top panel and nothing else. Horizontal panels that
    span the piece draw as dashed outlines so the walls and back read."""
    import re
    from build_assistant.generative.draw import plan
    svg = plan(_geo()).render()
    dashed = re.findall(r'<rect[^>]*stroke-dasharray', svg)
    solid = [r for r in re.findall(r'<rect[^>]*/>', svg)
             if "dasharray" not in r and 'fill="#fff"' not in r and 'fill="#111"' not in r]
    assert dashed, "the top and shelves must draw as outlines in a plan"
    assert solid, "the side panels and back must still read solid"
    print(f"  [ok] plan draws {len(dashed)} surfaces as outlines, walls stay solid")


def test_side_elevation_strikes_hidden_shelves_back_in():
    """The side of a closed case is one blank panel; a builder cannot see where the
    shelves land. Parts hidden behind a nearer one are drawn dashed."""
    import re
    from build_assistant.generative.draw import side_elevation
    svg = side_elevation(_geo()).render()
    hidden = re.findall(r'<rect[^>]*stroke="#8b857a"[^>]*dasharray', svg)
    assert hidden, "hidden shelf lines must be struck back in"
    print(f"  [ok] side elevation shows {len(hidden)} hidden edge(s) dashed")


def test_long_section_reason_stays_on_the_canvas():
    """Gate 3 caught this on a live build: the designer's reason moved to the
    caption line so it would read whole, and nothing bounded its width."""
    why = ("Longitudinal section through center to show seat dado, shelf dado, "
           "and back panel attachment detail for the whole assembly")
    spec = {**_CASE, "sections": [
        {"tag": "A-A", "axis": "x", "at_expr": "width/2", "why": why}]}
    geo = compile_design(DesignIR.from_dict(spec))
    c = next(v for k, v in detail_drawings(geo).items() if k.startswith("section_"))
    assert not c.overflowing_labels(), c.overflowing_labels()
    assert not c.geometry_overflow()
    print("  [ok] a long section reason is fitted to the canvas, not run off it")


def test_thick_stock_thickness_labels_stay_on_the_canvas():
    """Gate 3 held two live builds back for this: the gutter reserved for the
    thickness dimensions was a constant tuned for 3/4", and 1-1/2" ran off."""
    frame = {
        "name": "Frame", "summary": "t", "node_kind": "frame", "finish_id": "none",
        "params": [{"id": "len", "label": "L", "value": 72},
                   {"id": "ht", "label": "H", "value": 34}],
        "materials": [{"role": "stud", "material_id": "lumber_2x4"}],
        "elements": [{"id": "f", "kind": "frame", "length_expr": "len",
                      "width_expr": "3.5", "height_expr": "ht", "faces": []}],
        "parts": [
            {"id": "A", "name": "leg", "element": "f", "material_role": "stud",
             "length_expr": "ht", "width_expr": "3.5", "qty_expr": "2",
             "box_x": "0", "box_y": "0", "box_z": "0", "box_w": "stud_t",
             "box_d": "3.5", "box_h": "ht", "step_x": "len - stud_t"},
            {"id": "B", "name": "rail", "element": "f", "material_role": "stud",
             "length_expr": "len - 2*stud_t", "width_expr": "3.5", "qty_expr": "1",
             "box_x": "stud_t", "box_y": "0", "box_z": "ht - 3.5",
             "box_w": "len - 2*stud_t", "box_d": "3.5", "box_h": "stud_t"},
        ],
        "invariants": [], "derived": [], "operations": ["crosscut_panels"],
    }
    geo = compile_design(DesignIR.from_dict(frame))
    contacts = find_contacts(geo)
    assert contacts, "expected a contact between leg and rail"
    for i, ct in enumerate(contacts[:3]):
        c = joint_detail(geo, ct, f"D{i+1}")
        assert not c.overflowing_labels(), (f"D{i+1}", c.overflowing_labels())
        assert not c.geometry_overflow()
    print(f"  [ok] 1-1/2in stock keeps its dimensions on the canvas "
          f"({len(contacts[:3])} joint details)")


def test_a_fastener_through_a_chunky_member_stays_on_the_canvas():
    """A joint detail is a magnified crop and the members are drawn clipped to it,
    but the fastener was placed at the member's true far face. Through a 19in
    diagonal brace that put the screw head 600px outside a 260px canvas, Gate 3
    reported a visual defect and the document was refused release."""
    from build_assistant.generative.detail import find_contacts, joint_detail
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    # two chunky braces meeting face to face — thick across the seam, not thin
    for p in spec["parts"]:
        if p["id"] == "A":
            p.update({"box_x": "0", "box_w": "19", "box_d": "1.5", "box_h": "20.5",
                      "box_y": "0", "box_z": "0"})
        if p["id"] == "B":
            p.update({"box_x": "19", "box_w": "19", "box_d": "1.5", "box_h": "20.5",
                      "box_y": "0", "box_z": "0"})
    geo = compile_design(DesignIR.from_dict(spec))
    for i, ct in enumerate(find_contacts(geo), 1):
        c = joint_detail(geo, ct, f"D{i}")
        if c is None:
            continue
        assert not c.geometry_overflow(), (i, c.geometry_overflow())
        assert not c.overflowing_labels(), (i, c.overflowing_labels())
    print("  [ok] joint details of chunky members stay inside their canvas")
