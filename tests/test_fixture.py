"""Golden test — brief section 2.5 and 2.6.

Reproduces every value in the reference-fixture table from the seven inputs, and
exercises the three hard assertions plus both allowance directions and co-planar
overlap. Stdlib only (no pytest dependency): run with ``python -m tests.test_fixture``
or via ``run_tests.py``.
"""

from __future__ import annotations

import json
import os

from build_assistant.core.solver import solve, solve_hash
from build_assistant.core import allowance as A

HERE = os.path.dirname(__file__)
FIXTURE = os.path.join(HERE, "..", "fixtures", "coffee_table_reference.json")


def _answers() -> dict:
    with open(FIXTURE) as fh:
        return json.load(fh)


def _eq(a, b, tol=1e-6, msg=""):
    assert abs(a - b) <= tol, f"{msg}: expected {b}, got {a}"


def test_scalars_match_fixture():
    geo = solve(_answers())
    exp = {
        "skin.per_face_offset": 0.375,
        "slab.carcass_thickness": 2.25,
        "slab.deck.length": 41.25,
        "slab.deck.width": 19.25,
        "slab.core_ring_width": 3.0,
        "slab.rib_count": 3,
        "slab.bay_width": 6.5625,
        "slab.rib_left_edge.1": 9.5625,
        "slab.rib_left_edge.2": 19.125,
        "slab.rib_left_edge.3": 28.6875,
        "plinth.carcass_height.as_cut": 13.375,
        "plinth.height.as_finished": 13.0,
        "plinth.long_side.length": 35.25,
        "plinth.long_side.height": 13.375,
        "plinth.end_panel.length": 11.75,
        "plinth.end_panel.height": 13.375,
        "plinth.platform.length": 33.75,
        "plinth.platform.width": 11.75,
        "plinth.inset.as_assembled": 3.375,
        "plinth.inset.as_finished": 3.0,
        "overall_height": 16.0,
    }
    for fid, val in exp.items():
        _eq(geo.scalar(fid), val, msg=f"scalar {fid}")
    print(f"  [ok] {len(exp)} fixture scalars reproduced from 7 inputs")


def test_per_face_offset():
    geo = solve(_answers())
    _eq(geo.per_face_offset, 0.375, msg="per_face_offset")


def test_part_table():
    geo = solve(_answers())
    # 8 part types, 15 pieces
    assert geo.part_type_count() == 8, geo.part_type_count()
    assert geo.piece_count() == 15, geo.piece_count()
    expected = {
        "A": (41.25, 19.25, 1), "B": (41.25, 19.25, 1),
        "C": (41.25, 3.0, 2), "D": (13.25, 3.0, 2), "E": (13.25, 3.0, 3),
        "F": (35.25, 13.375, 2), "G": (11.75, 13.375, 2), "H": (33.75, 11.75, 2),
    }
    for pid, (L, Wd, qty) in expected.items():
        p = geo.part(pid)
        l, w = p.cut_wh()
        _eq(l, L, msg=f"part {pid} length")
        _eq(w, Wd, msg=f"part {pid} width")
        assert p.qty == qty, f"part {pid} qty {p.qty} != {qty}"
    print("  [ok] 8 part types / 15 pieces reproduced exactly")


def test_hard_assertion_1_plinth_height_two_values():
    """as_cut != as_finished — a solver returning one plinth height is wrong."""
    geo = solve(_answers())
    cut = geo.scalar("plinth.carcass_height.as_cut")
    fin = geo.scalar("plinth.height.as_finished")
    assert cut != fin, "plinth height must differ across stages"
    _eq(cut, 13.375, msg="plinth as_cut")
    _eq(fin, 13.0, msg="plinth as_finished")
    print("  [ok] hard assertion 1: plinth 13.375 as_cut vs 13.0 as_finished")


def test_hard_assertion_2_coplanar_overlap():
    """13.375 + 3 = 16.375 but overall is 16 — co-planar overlap must be handled."""
    geo = solve(_answers())
    plinth_cut = geo.scalar("plinth.carcass_height.as_cut")
    slab_finished = geo.elements[0].finished_height.as_finished  # slab edge = 3
    naive = plinth_cut + slab_finished
    _eq(naive, 16.375, msg="naive additive sum")
    _eq(geo.scalar("overall_height"), 16.0, msg="true overall height")
    assert naive != geo.scalar("overall_height")
    # And the solve passed invariants, so the co-planar checker accepted 16.0.
    print("  [ok] hard assertion 2: co-planar overlap (16 not 16.375) accepted by invariants")


def test_hard_assertion_3_inset_grows():
    """Plinth is set in further (3.375) than the finished reveal (3.0)."""
    geo = solve(_answers())
    asm = geo.scalar("plinth.inset.as_assembled")
    fin = geo.scalar("plinth.inset.as_finished")
    assert asm > fin, "carcass inset must exceed finished reveal"
    _eq(asm, 3.375, msg="inset as_assembled")
    _eq(fin, 3.0, msg="inset as_finished")
    print("  [ok] hard assertion 3: inset 3.375 as_assembled vs 3.0 as_finished")


def test_allowance_both_directions():
    """Property: the fixture exercises shrink (7 parts) AND grow (plinth) cases."""
    geo = solve(_answers())
    # subtractive effect: deck cut smaller than finished
    deckA = geo.part("A")
    assert deckA.length.as_cut < deckA.length.as_finished, "deck should be cut smaller"
    # additive effect: plinth cut taller than it reads finished (occluded top)
    F = geo.part("F")
    assert F.width.as_cut > F.width.as_finished, "plinth wall should be cut taller"
    # direct primitive coverage
    _eq(A.substrate_from_finished(42, 0.375, 2, A.ADDITIVE_OUTWARD), 41.25, msg="additive_outward")
    _eq(A.substrate_from_finished(10, 0.1, 2, A.SUBTRACTIVE), 10.2, msg="subtractive")
    _eq(A.visible_after_occlusion(13.375, 0.375), 13.0, msg="occlusion")
    print("  [ok] allowance direction exercised both ways (shrink + grow)")


def test_approximate_outputs():
    geo = solve(_answers())
    coated = geo.scalar("coated_area")
    weight = geo.scalar("weight_estimate")
    assert abs(coated - 18.9) / 18.9 < 0.15, f"coated_area {coated} not ~18.9"
    assert abs(weight - 120.0) / 120.0 < 0.15, f"weight {weight} not ~120"
    print(f"  [ok] coated_area {coated} sqft ~18.9, weight {weight} lb ~120")


def test_derived_decisions_present():
    geo = solve(_answers())
    ids = {d.field_id for d in geo.derived_decisions}
    for req in ("derived.substrate", "derived.core_ring_width", "derived.rib_count",
                "derived.joint_type", "derived.excluded_fastener"):
        assert req in ids, f"missing derived decision {req}"
    for d in geo.derived_decisions:
        assert d.basis.strip(), f"derived decision {d.field_id} has no basis"
    print(f"  [ok] {len(geo.derived_decisions)} derived decisions with basis strings")


def test_determinism_hash():
    a = solve_hash(solve(_answers()))
    b = solve_hash(solve(_answers()))
    assert a == b, "solve hash not stable within process"
    print(f"  [ok] deterministic solve hash {a[:16]}...")


def test_input_change_regenerates():
    ans = _answers()
    ans2 = dict(ans, overall_length=48)
    h1 = solve_hash(solve(ans))
    h2 = solve_hash(solve(ans2))
    assert h1 != h2, "changing an input must change the solve"
    # and the changed solve still satisfies invariants (solve would have raised)
    geo2 = solve(ans2)
    _eq(geo2.part("A").length.as_cut, 47.25, msg="deck length at L=48")
    print("  [ok] input change regenerates downstream cleanly")
