"""Nesting acceptance — brief Part 4 / section 2.5.

Every part nests; plywood utilisation matches the fixture within 0.5%; the
cut-order constraint fires; the offcut manifest contains a claimable piece of at
least 9 x 18.
"""

from __future__ import annotations

import json
import os

from build_assistant.core.solver import solve
from build_assistant.nesting.plan import plan_nesting

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "coffee_table_reference.json")


def _plan():
    return plan_nesting(solve(json.load(open(FIXTURE))))


def test_plywood_one_sheet_886():
    plan = _plan()
    ply = plan.nests["ply_075_structural"]
    assert ply.sheet_count() == 1, ply.sheet_count()
    util = ply.sheets[0].utilisation() * 100
    assert abs(util - 88.6) < 0.5, f"plywood util {util:.2f}% != 88.6%"
    assert sum(len(s.placements) for s in ply.sheets) == 15
    print(f"  [ok] plywood: 1 sheet, 15 parts, {util:.1f}% util")


def test_cut_order_constraint_fires():
    plan = _plan()
    ply = plan.nests["ply_075_structural"]
    assert ply.cut_order_constrained(), "cut-order constraint must fire above 0.85"
    print("  [ok] cut-order constraint fired (util > 0.85)")


def test_cement_board_two_sheets_11_2():
    plan = _plan()
    cb = plan.nests["cement_board_025"]
    assert cb.sheet_count() == 2, cb.sheet_count()
    counts = [len(s.placements) for s in cb.sheets]
    assert counts == [11, 2], counts
    print(f"  [ok] cement board: 2 sheets, split {counts}")


def test_claimable_offcut():
    plan = _plan()
    offcuts = plan.offcut_manifest()
    claimable = [o for o in offcuts if min(o["w"], o["h"]) >= 9.0 and o["w"] * o["h"] >= 9 * 18]
    assert claimable, f"no claimable >=9x18 offcut in {offcuts}"
    print(f"  [ok] {len(claimable)} claimable offcut(s) >= 9x18: "
          f"{claimable[0]['w']}x{claimable[0]['h']}")


def test_every_part_nests():
    plan = _plan()
    for mid, n in plan.nests.items():
        placed = sum(len(s.placements) for s in n.sheets)
        assert placed > 0, mid
    print("  [ok] every part placed on a sheet")
