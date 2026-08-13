"""Generative engine tests — the deterministic half of "build anything".

No API key needed: these prove the evaluator is safe, the compiler turns an IR into
correct numbers, and the result is deterministic. The agent authors the IR; these
guard the machinery that turns it into trustworthy geometry.
"""

from __future__ import annotations

from build_assistant.generative.evaluator import evaluate, ExprError
from build_assistant.generative.model import DesignIR
from build_assistant.generative.compiler import compile_design
from build_assistant.core.solver import solve_hash


def test_evaluator_arithmetic():
    sym = {"width": 30.0, "carcass_t": 0.75}
    assert evaluate("width - 2*carcass_t", sym) == 28.5
    assert evaluate("max(width, 40)", sym) == 40.0
    print("  [ok] evaluator computes formulas over the symbol table")


def test_evaluator_does_a_diagonal():
    """A firewood rack asked for a brace and the design failed outright: the
    whitelist could not express a hypotenuse."""
    env = {"depth": 12.0, "rise": 16.0}
    assert evaluate("sqrt(depth*depth + rise*rise)", env) == 20.0
    assert evaluate("hypot(depth, rise)", env) == 20.0
    print("  [ok] a diagonal member can be expressed")


def test_evaluator_rejects_unsafe():
    for bad in ("__import__('os')", "open('x')", "width.__class__", "(1).__add__(2)", "a and b"):
        try:
            evaluate(bad, {"width": 1, "a": 1, "b": 1})
            raise AssertionError(f"expected ExprError for {bad!r}")
        except ExprError:
            pass
    print("  [ok] evaluator rejects non-arithmetic / unsafe expressions")


_BOOKSHELF = {
    "name": "Test shelf", "summary": "s", "node_kind": "bookshelf",
    "params": [{"id": "width", "label": "W", "value": 30}, {"id": "height", "label": "H", "value": 48},
               {"id": "depth", "label": "D", "value": 11}, {"id": "shelves", "label": "N", "value": 3}],
    "materials": [{"role": "carcass", "material_id": "ply_075_structural"},
                  {"role": "back", "material_id": "ply_025"}],
    "finish_id": "none",
    "elements": [{"id": "case", "kind": "carcass", "length_expr": "width", "width_expr": "depth",
                  "height_expr": "height", "z_base_expr": "0", "stacks_height": False, "faces": []}],
    "parts": [
        {"id": "A", "name": "side", "element": "case", "material_role": "carcass",
         "length_expr": "height", "width_expr": "depth", "qty_expr": "2", "grain": "length"},
        {"id": "B", "name": "top/bottom", "element": "case", "material_role": "carcass",
         "length_expr": "width - 2*carcass_t", "width_expr": "depth", "qty_expr": "2", "grain": "length"},
        {"id": "C", "name": "shelf", "element": "case", "material_role": "carcass",
         "length_expr": "width - 2*carcass_t", "width_expr": "depth - 0.25", "qty_expr": "shelves",
         "grain": "length"},
        {"id": "D", "name": "back", "element": "case", "material_role": "back",
         "length_expr": "width", "width_expr": "height", "qty_expr": "1", "grain": "none"}],
    "invariants": [{"kind": "span", "params": {"name": "shelf",
                    "unsupported_span": "width - 2*carcass_t", "flex_threshold": 36}}],
    "derived": [], "operations": ["rip_sheet_goods"], "fasteners": [], "warnings": [],
}


def test_compiler_produces_correct_numbers():
    geo = compile_design(DesignIR.from_dict(_BOOKSHELF))
    assert geo.node == "bookshelf"
    assert geo.part_type_count() == 4 and geo.piece_count() == 8
    b = geo.part("B")
    assert b.cut_wh() == (28.5, 11.0), b.cut_wh()   # 30 - 2*0.75
    c = geo.part("C")
    assert c.cut_wh() == (28.5, 10.75) and c.qty == 3
    print("  [ok] compiler evaluates the IR into correct part geometry (no recipe)")


def test_compiler_deterministic():
    a = solve_hash(compile_design(DesignIR.from_dict(_BOOKSHELF)))
    b = solve_hash(compile_design(DesignIR.from_dict(_BOOKSHELF)))
    assert a == b
    print("  [ok] same IR -> same geometry hash (deterministic)")


def test_invariant_catches_bad_span():
    bad = {**_BOOKSHELF, "invariants": [{"kind": "span", "params": {
        "name": "shelf", "unsupported_span": "width - 2*carcass_t", "flex_threshold": 0.02}}]}
    try:
        compile_design(DesignIR.from_dict(bad))
        raise AssertionError("expected the span invariant to fail")
    except Exception as exc:  # noqa: BLE001
        assert "span" in str(exc).lower()
    print("  [ok] deterministic audit catches an over-long span the agent might miss")


def test_a_derived_decision_reaches_the_user_as_a_number():
    """'Derived, not asked' tells someone what the app decided for them, so it has
    to be a number. A released sofa showed a user 'Interior Seat Width (between
    arms): overall_width - 2*arm_width' — a formula in symbol names is engine-speak,
    the same defect as a raw part id in prose. The model still never emits the
    number; the engine computes it and keeps the formula as the basis."""
    from build_assistant.generative.model import DesignIR
    from build_assistant.generative.compiler import compile_design
    from tests.test_details import _CASE
    spec = {**_CASE, "derived": [
        {"label": "Interior width", "value": "width - 2*carcass_t",
         "basis": "Clear span between the sides", "is_overridable": False},
        {"label": "Finish", "value": "left bare", "basis": "User asked for raw wood",
         "is_overridable": True}]}
    geo = compile_design(DesignIR.from_dict(spec))
    by_label = {d.label: d for d in geo.derived_decisions}
    assert by_label["Interior width"].value == "28.5 in", by_label["Interior width"].value
    assert "width - 2*carcass_t" in by_label["Interior width"].basis
    # prose that is not an expression is left exactly as written
    assert by_label["Finish"].value == "left bare"
    print("  [ok] a derived decision shows its value, and keeps its formula as basis")
