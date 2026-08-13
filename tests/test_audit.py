"""Placement audit — the check that catches designs which compile but are not
real objects.

This is the class of defect that produced a nonsensical section drawing: six
shelves stepped sideways out of a 32in case, four of them floating in open air.
Every expression evaluated, every invariant passed, the cut list looked sane, and
only the placement gave it away.
"""

from __future__ import annotations

from build_assistant.generative.model import DesignIR
from build_assistant.generative.compiler import compile_design
from build_assistant.generative.audit import audit_placement
from tests.test_details import _CASE


def _with(parts_patch=None, extra=None):
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    if parts_patch:
        for p in spec["parts"]:
            if p["id"] in parts_patch:
                p.update(parts_patch[p["id"]])
    if extra:
        spec.update(extra)
    return compile_design(DesignIR.from_dict(spec))


def test_sound_assembly_is_clean():
    issues = audit_placement(compile_design(DesignIR.from_dict(_CASE)))
    assert issues == [], issues
    print("  [ok] a sound assembly raises no placement issues")


def test_catches_parts_stepped_out_of_the_object():
    """The real defect: qty>1 parts marching sideways past the outside."""
    geo = _with({"C": {"qty_expr": "6", "step_x": "15.65", "step_z": "0"}})
    issues = audit_placement(geo)
    assert any("outside the object" in i for i in issues), issues
    assert any("step_x" in i for i in issues), "the message must point at the cause"
    print("  [ok] parts stepped outside the object are caught, cause named")


def test_catches_floating_parts():
    geo = _with({"C": {"box_z": "200"}})       # shelf far above everything
    issues = audit_placement(geo)
    floats = [i for i in issues if "floats free" in i]
    assert floats, issues
    # "place it against the parts it fixes to" is true and useless — the repair
    # guesses, overshoots, and comes back as an interpenetration. Name the number,
    # and make sure the number named actually clears the defect.
    assert "box_z=47.250" in floats[0], floats[0]
    fixed = _with({"C": {"box_z": "47.25", "qty_expr": "1"}})
    assert not [i for i in audit_placement(fixed) if "floats free" in i or "pass through" in i]
    print("  [ok] a part touching nothing is caught, and the coordinate offered seats it")


def test_catches_interpenetration():
    """Two parts lying broadside into each other really do share wood."""
    geo = _with({"D": {"box_y": "0"}})         # back panel buried in the side panels
    issues = audit_placement(geo)
    assert any("pass through each other" in i for i in issues), issues
    print("  [ok] two parts sharing solid volume are caught")


def test_end_buried_in_a_face_is_reported_as_an_undeclared_joint():
    """A shelf whose end sits inside the side panel is not a collision — it is a
    dado nobody declared. Told to "shorten one of them", the repair loop shortens
    it until it touches nothing, gets a floating error, pushes it back, and
    oscillates: there is no legal position while the audit denies the joint."""
    geo = _with({"C": {"box_x": "0"}})         # shelf end driven into the side panel
    issues = [i for i in audit_placement(geo) if "undeclared" in i or "joint's worth" in i]
    assert issues, audit_placement(geo)
    msg = issues[0]
    assert "joint_type" in msg and "joint_depth_expr" in msg, msg
    assert "box_x=0.750" in msg, msg               # ...and the butt-joint coordinate
    assert "box_w=27.750" in msg, msg              # shortened by what it gave up
    assert "pass through each other" not in msg
    print("  [ok] an end buried in a face is named as a joint, both remedies given")


def test_housed_joint_is_not_flagged_as_interpenetration():
    """A shelf seated in a dado is SUPPOSED to sit inside its housing."""
    geo = _with(
        {"A": {"joint_type": "dado", "joint_depth_expr": "0.25"},
         "B": {"joint_type": "dado", "joint_depth_expr": "0.25"},
         "C": {"box_x": "carcass_t - 0.25", "box_w": "width - 2*carcass_t + 0.5"}})
    issues = [i for i in audit_placement(geo) if "pass through each other" in i]
    assert not issues, f"joinery overlap must not be reported: {issues}"
    print("  [ok] joinery overlap within the cut depth is accepted")


def test_an_undersized_element_is_blamed_before_the_part_that_escapes_it():
    """Two checks can point opposite ways. A part sticks out of the envelope, and
    the envelope is also smaller than the brief. Told to move the part in, the
    model shrinks the piece; told the piece is too small, it grows the element and
    the part escapes again. Neither message alone escapes that loop."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]],
            "elements": [dict(e) for e in _CASE["elements"]],
            "params": [dict(p) for p in _CASE["params"]]}
    # the user asked for 30in wide; the element is built to 20
    spec["elements"][0]["length_expr"] = "20"
    for p in spec["parts"]:
        p["box_w"] = p["box_w"].replace("width", "30")
    issues = audit_placement(compile_design(DesignIR.from_dict(spec)))
    escapes = [i for i in issues if "placed outside the object" in i]
    assert escapes, issues
    assert any("Fix the ELEMENT first" in i for i in escapes), escapes
    assert any("length_expr should evaluate to 30" in i for i in escapes), escapes
    assert not any("step_x =" in i for i in escapes), "wrong end blamed"
    print("  [ok] an undersized element is blamed before the parts that escape it")


def test_corner_blocks_can_be_placed_at_corners():
    """Four blocks at four corners do not lie on a line, so no step_x/step_y/step_z
    can place them: two always march out past the end. A live sofa run burned three
    rounds on exactly that, with the audit prescribing a step that could not exist."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    spec["parts"].append(
        {"id": "BLK", "name": "corner blocks", "element": "case",
         "material_role": "carcass", "length_expr": "3", "width_expr": "3",
         "qty_expr": "4", "box_w": "3", "box_d": "3", "box_h": "carcass_t",
         "positions": [["carcass_t", "0", "0"], ["width - carcass_t - 3", "0", "0"],
                       ["carcass_t", "depth - back_t - 3", "0"],
                       ["width - carcass_t - 3", "depth - back_t - 3", "0"]]})
    geo = compile_design(DesignIR.from_dict(spec))
    placed = [b for b in geo.structure["boxes"] if b["id"] == "BLK"]
    assert len(placed) == 4, placed
    assert len({(round(b["x"], 3), round(b["y"], 3)) for b in placed}) == 4
    assert not [i for i in audit_placement(geo) if "BLK" in i], audit_placement(geo)
    print("  [ok] corner blocks placed by `positions` land at four corners, clean")


def test_bought_count_must_match_placed_count():
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    spec["parts"].append(
        {"id": "BLK", "name": "corner blocks", "element": "case",
         "material_role": "carcass", "length_expr": "3", "width_expr": "3",
         "qty_expr": "6", "box_w": "3", "box_d": "3", "box_h": "carcass_t",
         "positions": [["carcass_t", "0", "0"], ["width - carcass_t - 3", "0", "0"]]})
    issues = audit_placement(compile_design(DesignIR.from_dict(spec)))
    assert any("bought 6 time(s) but placed 2" in i for i in issues), issues
    print("  [ok] a cut list buying more than the drawing places is caught")


def test_catches_stacked_duplicate_instances():
    geo = _with({"C": {"qty_expr": "3", "step_z": "0"}})   # all copies in one place
    issues = audit_placement(geo)
    assert any("stacked at the same" in i for i in issues), issues
    print("  [ok] repeated instances landing on each other are caught")


def test_part_running_through_a_divider_is_told_to_split_into_bays():
    """A shelf crossing a centre divider cannot be cured by shortening it — that
    empties a bay. The loop burned five rounds on exactly this before the audit
    said which of the two remedies applies."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    spec["parts"].append(
        {"id": "DIV", "name": "centre divider", "element": "case",
         "material_role": "carcass", "length_expr": "height",
         "width_expr": "depth - back_t", "qty_expr": "1",
         "box_x": "width/2 - carcass_t/2", "box_y": "0", "box_z": "0",
         "box_w": "carcass_t", "box_d": "depth - back_t", "box_h": "height"})
    issues = audit_placement(compile_design(DesignIR.from_dict(spec)))
    split = [i for i in issues if "one piece per bay" in i]
    assert split, issues
    assert "step_x" in split[0] and "qty" in split[0], split[0]
    print("  [ok] a part crossing a divider is told to split into bays, with numbers")


def test_catches_solid_drawn_thinner_than_its_stock():
    """A back written as `box_d = rabbet_depth` is 3/4in ply modelled 1/4in thick —
    the cut list buys one panel and every drawing shows another."""
    geo = _with({"D": {"box_d": "0.25"}})
    issues = audit_placement(geo)
    assert any("thick on y" in i for i in issues), issues
    assert any("box_d" in i for i in issues), "the message must prescribe the fix"
    print("  [ok] a solid thinner than its own stock is caught")


def test_lamination_is_not_flagged():
    """Two layers of the back's own stock glued up — legitimate, not a defect."""
    geo = _with({"D": {"box_d": "0.4"}})            # 2 x the 0.20in actual
    assert not [i for i in audit_placement(geo) if "stock" in i and "thick on" in i]
    print("  [ok] a multiple of the stock thickness is accepted as a lamination")


def test_catches_useless_directed_section():
    geo = _with(extra={"sections": [
        {"tag": "Z-Z", "axis": "z", "at_expr": "60", "why": "above the piece entirely"}]})
    issues = audit_placement(geo)
    assert any("reveals" in i or "passes through" in i for i in issues), issues
    print("  [ok] a section plane that reveals nothing is caught")


def test_audit_runs_inside_the_design_loop():
    """The loop must treat a placement defect as repairable, not ship it."""
    from webapp.designer import DesignAgent
    agent = DesignAgent()
    broken = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in broken["parts"]:
        if p["id"] == "C":
            p.update({"qty_expr": "6", "step_x": "15.65", "step_z": "0"})
    geo, error = agent._try_compile(DesignIR.from_dict(broken))
    assert geo is not None, "geometry is still built so the critique can see it"
    assert error.startswith("PlacementError"), error
    assert "outside the object" in error
    print("  [ok] the design loop receives the placement defect for repair")


def test_prose_that_contradicts_the_design_is_caught():
    """Gate 1 proves a number came from the solver. It cannot tell that "3/8in-deep
    dado" is the wrong solver value for a design whose dados are 1/4in."""
    from build_assistant.generative.prose_audit import audit_prose
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in spec["parts"]:
        if p["id"] in ("A", "B"):
            p["joint_type"] = "dado"
            p["joint_depth_expr"] = "0.25"
    geo = compile_design(DesignIR.from_dict(spec))

    bad = {"governing_note": 'Cut 3/4" wide x 3/8" deep dado joints in each side.',
           "steps": [{"title": "Rout", "detail": 'Set the router 1/4" deep for the dado.'},
                     {"title": "Drill", "detail": 'Bore a pilot hole 1" deep for the dado screw.'}]}
    issues = audit_prose(geo, bad)
    assert len(issues) == 1, issues
    assert "3/8" in issues[0] and '1/4"' in issues[0], issues[0]
    print("  [ok] a sentence quoting the wrong joinery depth is caught, correct value named")


def test_prose_audit_leaves_correct_packets_alone():
    from build_assistant.generative.prose_audit import audit_prose
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in spec["parts"]:
        if p["id"] in ("A", "B"):
            p["joint_type"] = "dado"
            p["joint_depth_expr"] = "0.25"
    geo = compile_design(DesignIR.from_dict(spec))
    good = {"governing_note": 'Cut the dado 1/4" deep.',
            "care": "Wipe with a damp cloth.",
            "steps": [{"title": "Rout", "detail": 'Dado depth is 1/4"; test in scrap.'}]}
    assert audit_prose(geo, good) == []
    print("  [ok] a packet that agrees with its design raises nothing")


def test_packet_reconciliation_rewrites_the_offending_sentence():
    """The loop must repair the prose, not merely report it."""
    from webapp.designer import DesignAgent
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in spec["parts"]:
        if p["id"] in ("A", "B"):
            p["joint_type"] = "dado"
            p["joint_depth_expr"] = "0.25"
    geo = compile_design(DesignIR.from_dict(spec))

    drafts = [
        {"steps": [{"title": "Rout", "detail": 'Cut the dado 3/8" deep.'}]},
        {"steps": [{"title": "Rout", "detail": 'Cut the dado 1/4" deep.'}]},
    ]
    agent = DesignAgent()
    agent.boundary_call = lambda system, user: drafts.pop(0)     # stub the model
    fixed = agent._reconcile_packet(geo, drafts.pop(0), "sys", "user")
    assert '1/4"' in fixed["steps"][0]["detail"], fixed
    assert agent.packet_prose_issues == []
    print("  [ok] the packet loop rewrites prose that contradicts the design")


def test_top_capping_two_sides_is_not_told_to_split_into_bays():
    """A live run stalled here: a top panel spans both side panels, so each side
    sits inside its span — but a top is not divided into bays by the walls it rests
    on. The wrong remedy sent the repair loop in circles."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    spec["parts"].append(
        {"id": "TOP", "name": "top panel", "element": "case",
         "material_role": "carcass", "length_expr": "width",
         "width_expr": "depth", "qty_expr": "1",
         "box_x": "0", "box_y": "0", "box_z": "height - carcass_t/2",   # sunk into the sides
         "box_w": "width", "box_d": "depth - back_t", "box_h": "carcass_t"})
    issues = audit_placement(compile_design(DesignIR.from_dict(spec)))
    bays = [i for i in issues if "one piece per bay" in i]
    assert not bays, f"a top panel must never be told to split into bays: {bays}"
    # It is still a defect — the side ends are half-buried in the lid — and it is
    # still reported, with the trim that lands them on the lid's underside.
    assert any("box_h=47.625" in i for i in issues), issues
    print("  [ok] a top sunk into its sides is a joint to declare, not a bay problem")


def test_loop_never_ends_worse_than_the_best_round_it_found():
    """A repair rewrites the whole model, so a later round can undo an earlier fix.
    A live run went clean at round 2, broke at round 3, and spent the rest of its
    budget getting back. The loop keeps the best model it saw."""
    from webapp.designer import DesignAgent
    clean = dict(_CASE)
    broken = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in broken["parts"]:
        if p["id"] == "C":
            p.update({"qty_expr": "6", "step_x": "15.65", "step_z": "0"})

    agent = DesignAgent()
    agent.synthesize = lambda *a, **k: DesignIR.from_dict(broken)
    agent.critique = lambda *a, **k: {"issues": [{"severity": "high", "what": "x"}],
                                      "buildable": True}
    drafts = [DesignIR.from_dict(clean), DesignIR.from_dict(broken)]   # good, then a regression
    agent.repair = lambda *a, **k: drafts.pop(0)

    res = agent.design("bookcase", {}, max_rounds=2)
    assert res.geo is not None
    from build_assistant.generative.audit import audit_placement
    assert audit_placement(res.geo) == [], "the loop shipped the regressed model"
    assert any(t["action"] == "revert_to_best" for t in res.rounds), res.rounds
    print("  [ok] the loop keeps the best model it found, not the last one")


def test_wide_solid_panel_is_built_as_a_glue_up():
    """A 12in solid side used to be unbuildable — the loop spent six rounds
    trimming it an inch at a time. It is four strips jointed and glued."""
    from build_assistant.core.invariants import check_invariants
    from build_assistant.core.glueup import glue_up
    spec = {**_CASE, "materials": [{"role": "carcass", "material_id": "hardwood_4_4"},
                                   {"role": "back", "material_id": "ply_025"}]}
    geo = compile_design(DesignIR.from_dict(spec), check=False)
    check_invariants(geo)                       # no longer raises
    side = next(p for p in geo.parts if p.id == "A")
    gl = glue_up(side)
    assert gl.is_glued and gl.count >= 2, gl
    assert gl.strip_width <= 8.0 + 1e-6, "each strip must fit a real board"
    assert "glue up from" in gl.describe()
    print(f"  [ok] a 12in solid panel builds as {gl.count} glued strips")


def test_a_part_longer_than_any_board_still_names_the_remedy():
    """Width is solvable by gluing up; length is not."""
    from build_assistant.core.invariants import check_invariants, InvariantError
    spec = {**_CASE, "params": [{"id": "width", "label": "W", "value": 30},
                                {"id": "height", "label": "H", "value": 130},
                                {"id": "depth", "label": "D", "value": 12}],
            "materials": [{"role": "carcass", "material_id": "hardwood_4_4"},
                          {"role": "back", "material_id": "ply_025"}]}
    geo = compile_design(DesignIR.from_dict(spec), check=False)
    try:
        check_invariants(geo)
    except InvariantError as exc:
        msg = str(exc)
    else:
        raise AssertionError("a 130in board must not pass the stock check")
    assert "no glue-up makes a board longer" in msg, msg
    assert "96in" in msg, "the message must state the real board length"
    print("  [ok] a part longer than any board names the remedy")


def test_a_piece_that_is_not_the_size_asked_for_is_caught():
    """An 84in sofa was placed as a 237in row of parts and released: 21 pages, all
    three gates green. Nothing escaped its envelope, nothing floated, nothing
    interpenetrated — the design was internally consistent about being the wrong
    object, and the gates check provenance and bounds, not the brief."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]],
            "elements": [{"id": "case", "kind": "carcass", "length_expr": "150",
                          "width_expr": "depth", "height_expr": "height", "faces": []}]}
    for i, p in enumerate(spec["parts"]):
        p["box_x"] = str(i * 40)                 # laid out in a row, not assembled
    issues = audit_placement(compile_design(DesignIR.from_dict(spec)))
    brief = [i for i in issues if "than the brief" in i]
    assert brief, issues
    assert "30in on x" in brief[0] and "150.0in" in brief[0], brief[0]
    print("  [ok] a piece that is not the size asked for is caught")


def test_a_frame_built_deliberately_undersize_is_not_flagged():
    """An upholstery frame is built an inch or two under so the padding and fabric
    land on the finished dimension. That is correct, not a defect."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in spec["parts"]:                       # every part 1in narrower
        if p["id"] in ("A", "B"):
            p["box_x"] = "0" if p["id"] == "A" else "width - carcass_t - 1"
    issues = audit_placement(compile_design(DesignIR.from_dict(spec)))
    assert not [i for i in issues if "than the brief" in i], issues
    print("  [ok] a frame an inch under its finished size is accepted")


def test_a_declared_tenon_is_not_interpenetration():
    """A sofa frame joined with mortise and tenon tripped eighteen
    interpenetration flags. The agent had written `tenon_length` as a parameter and
    used it in the placement — it was cutting real joints — but the joint_type
    vocabulary was butt|dado|groove|rabbet|pocket|miter, with no way to say tenon.
    Every joint therefore read as two parts occupying the same wood."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in spec["parts"]:
        if p["id"] == "C":
            p.update({"joint_type": "tenon", "joint_depth_expr": "1.5",
                      "box_x": "carcass_t - 1.5",
                      "box_w": "width - 2*carcass_t + 3"})
    geo = compile_design(DesignIR.from_dict(spec))
    assert geo.structure["joinery"]["C"] == {"type": "tenon", "depth": 1.5}
    assert not [i for i in audit_placement(geo) if "pass through each other" in i]
    print("  [ok] a declared tenon seats in its mortise instead of being a defect")


def test_a_tenon_without_a_stated_depth_goes_through_not_a_third_in():
    """A housing cut goes about a third into its member; a tenon goes right in."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    for p in spec["parts"]:
        if p["id"] == "C":
            p["joint_type"] = "tenon"                 # no depth stated
        if p["id"] == "A":
            p["joint_type"] = "dado"
    geo = compile_design(DesignIR.from_dict(spec))
    tenon = geo.structure["joinery"]["C"]["depth"]
    dado = geo.structure["joinery"]["A"]["depth"]
    assert tenon > dado, (tenon, dado)
    assert abs(tenon - 0.75) < 1e-6, tenon           # a full board thickness
    print(f"  [ok] an undeclared tenon defaults through ({tenon}) not a third in ({dado:.3f})")


def test_an_overlong_span_says_how_to_carry_it():
    """A sofa failed twice on the same seat span. The invariant said only that it
    was too long, which left the repair nowhere to go."""
    from build_assistant.core.invariants import _inv_flex_span, InvariantError

    class Geo:
        structure = {"spans": [{"name": "Seat slats", "unsupported_span": 87.0625,
                                "flex_threshold": 36.0}]}
    try:
        _inv_flex_span(Geo())
    except InvariantError as exc:
        msg = str(exc)
    else:
        raise AssertionError("an 87in span over a 36in limit must fail")
    assert "2 intermediate supports" in msg, msg
    assert "29.0in" in msg, "the message must state the resulting bay"
    assert "clear distance between them" in msg, "the other remedy must be named"
    print("  [ok] an overlong span names the supports that would carry it")


def test_escaped_repeats_are_told_the_step_that_would_fit():
    """A sofa spent six of eight rounds on this defect — slats, blocks and braces
    marching out past the end — because the message said to check step_x without
    ever saying what it should be."""
    spec = {**_CASE, "parts": [dict(p) for p in _CASE["parts"]]}
    spec["parts"].append(
        {"id": "BLK", "name": "corner block", "element": "case",
         "material_role": "carcass", "length_expr": "3", "width_expr": "3",
         "qty_expr": "2", "box_x": "0", "box_y": "0", "box_z": "0",
         "box_w": "3", "box_d": "3", "box_h": "3", "step_x": "60"})
    issues = audit_placement(compile_design(DesignIR.from_dict(spec)))
    esc = [i for i in issues if i.startswith("part BLK")]
    assert esc, issues
    assert "step_x = 27.000" in esc[0], esc[0]
    assert "NOT the full width" in esc[0]
    print("  [ok] escaped repeats are given the step that would fit them")


def test_parts_that_cannot_sit_side_by_side_are_told_so():
    """Four full-width shelves have no step that fits across; the honest answer is
    that they repeat up the height instead."""
    geo = _with({"C": {"qty_expr": "4", "step_x": "30", "step_z": "0"}})
    esc = [i for i in audit_placement(geo) if i.startswith("part C")]
    assert esc, "expected the shelves to escape"
    assert "overlap them" in esc[0], esc[0]
    assert "different axis" in esc[0]
    print("  [ok] parts that cannot fit side by side are told so, not given a bad step")


def test_a_narrow_backing_names_both_ways_out():
    """A sofa spent four rounds shaving a surface an inch at a time — 13, 10, 9,
    7.5 — because the message named the mismatch and no way out of it."""
    from build_assistant.core.invariants import _inv_continuous_backing, InvariantError

    class Geo:
        structure = {"backing": [{"name": "Back panel", "backing_width": 3.5,
                                  "surface_width": 13.0}]}
    try:
        _inv_continuous_backing(Geo())
    except InvariantError as exc:
        msg = str(exc)
    else:
        raise AssertionError("a 3.5in backing under a 13in surface must fail")
    assert "widen the backing to 13" in msg, msg
    assert "narrow the surface to 3.5" in msg, msg
    assert "does not converge" in msg
    print("  [ok] a narrow backing names both ways out, with the numbers")
