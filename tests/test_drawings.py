"""Drawing engine acceptance — brief section 5.1 hard rules."""

from __future__ import annotations

import json
import os

from build_assistant.core.solver import solve
from build_assistant.nesting.plan import plan_nesting
from build_assistant.drawing.drawings import all_drawings
from build_assistant.drawing.primitives import Canvas, fmt_inches, LabelError

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "coffee_table_reference.json")


def _draw():
    geo = solve(json.load(open(FIXTURE)))
    return all_drawings(geo, plan_nesting(geo))


def test_fraction_formatting():
    assert fmt_inches(41.25) == '41-1/4"'
    assert fmt_inches(13.375) == '13-3/8"'
    assert fmt_inches(3.0) == '3"'
    assert fmt_inches(6.5625) == '6-9/16"'
    print("  [ok] decimal->fraction formatting")


def test_no_default_label():
    """Lesson 7: dimension helpers must reject a missing label."""
    c = Canvas(200, 200)
    for call in (
        lambda: c.dim_horizontal(0, 100, 50, None),
        lambda: c.dim_vertical(0, 100, 50, None),
        lambda: c.leader(0, 0, 10, 10, None),
        lambda: c.text(0, 0, None),
    ):
        try:
            call()
            raise AssertionError("expected LabelError for missing label")
        except LabelError:
            pass
    print("  [ok] no coordinate-derived default label (Lesson 7 enforced)")


def test_every_drawing_declares_stage():
    for name, c in _draw().items():
        assert c.stage in ("as_cut", "as_assembled", "as_finished"), (name, c.stage)
    print("  [ok] every drawing declares its stage")


def test_no_label_overflow():
    for name, c in _draw().items():
        ov = c.overflowing_labels()
        assert not ov, f"{name} overflows: {[t.text for t in ov]}"
    print("  [ok] no label overflows viewBox (Gate 3 support)")


def test_per_stage_drawings_differ():
    d = _draw()
    assert d["plinth_as_cut"].stage == "as_cut"
    assert d["plinth_as_finished"].stage == "as_finished"
    # the two quote different values (13.375 vs 13); " renders as &quot;
    assert "13-3/8&quot;" in d["plinth_as_cut"].render()
    assert ">13&quot;" in d["plinth_as_finished"].render()
    print("  [ok] dedicated per-stage plinth drawings quote 13-3/8 vs 13")
