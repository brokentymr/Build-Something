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
