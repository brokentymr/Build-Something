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
    assert any("floats free" in i for i in issues), issues
    print("  [ok] a part touching nothing is caught")


def test_catches_interpenetration():
    geo = _with({"C": {"box_x": "0"}})         # shelf driven through the side panel
    issues = audit_placement(geo)
    assert any("pass through each other" in i for i in issues), issues
    print("  [ok] two parts sharing solid volume are caught")


def test_housed_joint_is_not_flagged_as_interpenetration():
    """A shelf seated in a dado is SUPPOSED to sit inside its housing."""
    geo = _with(
        {"A": {"joint_type": "dado", "joint_depth_expr": "0.25"},
         "B": {"joint_type": "dado", "joint_depth_expr": "0.25"},
         "C": {"box_x": "carcass_t - 0.25", "box_w": "width - 2*carcass_t + 0.5"}})
    issues = [i for i in audit_placement(geo) if "pass through each other" in i]
    assert not issues, f"joinery overlap must not be reported: {issues}"
    print("  [ok] joinery overlap within the cut depth is accepted")


def test_catches_stacked_duplicate_instances():
    geo = _with({"C": {"qty_expr": "3", "step_z": "0"}})   # all copies in one place
    issues = audit_placement(geo)
    assert any("stacked at the same" in i for i in issues), issues
    print("  [ok] repeated instances landing on each other are caught")


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
