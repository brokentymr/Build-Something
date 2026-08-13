"""Invariant checker — Phase 1, section 2.4.

Assertions the solver must satisfy. Failure is *hard failure* — never a warning,
never rendered (section 2.4). :func:`check_invariants` raises
:class:`InvariantError` on the first violation.

The subtle one is the height sum: it must **account for co-planar overlaps**
(section 2.5 assertion 2, Lesson 1). A naive "heights must sum" check rejects the
correct solve and accepts the incorrect one, so co-planar layers are modelled
explicitly and excluded from the vertical sum while being required to lie within
a stacking band.
"""

from __future__ import annotations

from .model import Geometry
from ..catalog.materials import get_material

TOL = 1e-6


class InvariantError(AssertionError):
    """A solver invariant was violated. Hard failure."""


def _close(a: float, b: float, tol: float = TOL) -> bool:
    return abs(a - b) <= tol


def check_invariants(geo: Geometry) -> None:
    _inv_height_stack_with_coplanar(geo)
    _inv_reveal_symmetry(geo)
    _inv_carcass_offset(geo)
    _inv_positive_lengths(geo)
    _inv_flex_span(geo)
    _inv_continuous_backing(geo)
    _inv_parts_fit_stock(geo)


def _inv_height_stack_with_coplanar(geo: Geometry) -> None:
    """Stacked finished heights sum to overall height, accounting for co-planar overlaps."""
    layers = geo.structure.get("height_layers")
    if not layers:
        return
    overall = geo.scalar("overall_height")
    stacked = sum(l["thickness"] for l in layers if l.get("contributes", True))
    if not _close(stacked, overall):
        raise InvariantError(
            f"height stack {stacked} != overall_height {overall} "
            f"(check co-planar overlap handling — Lesson 1)"
        )
    # Every non-contributing (co-planar) layer must lie within a stacking band,
    # i.e. it genuinely overlaps rather than being silently dropped.
    bands = [(l["z_lo"], l["z_hi"]) for l in layers if l.get("contributes", True)]
    for l in layers:
        if l.get("contributes", True):
            continue
        lo, hi = l["z_lo"], l["z_hi"]
        if not any(lo >= blo - TOL and hi <= bhi + TOL for blo, bhi in bands):
            raise InvariantError(
                f"co-planar layer {l['name']!r} [{lo},{hi}] is not spanned by any "
                f"stacking band — it would be double-counted or lost"
            )


def _inv_reveal_symmetry(geo: Geometry) -> None:
    """Reveals symmetric on all declared sides unless asymmetry was requested."""
    if geo.inputs.get("asymmetric_reveal"):
        return
    reveals = geo.structure.get("reveals", {})
    vals = list(reveals.values())
    if vals and any(not _close(v, vals[0]) for v in vals):
        raise InvariantError(f"reveals not symmetric: {reveals}")


def _inv_carcass_offset(geo: Geometry) -> None:
    """Carcass offset equals finished reveal plus allowance of the inset element."""
    for rec in geo.structure.get("inset_checks", []):
        expected = rec["reveal_finished"] + rec["offset"] * rec.get("exposed_faces", 1)
        if not _close(rec["carcass_inset"], expected):
            raise InvariantError(
                f"carcass inset {rec['carcass_inset']} != reveal "
                f"{rec['reveal_finished']} + allowance {rec['offset']} ({rec['element']})"
            )


def _inv_positive_lengths(geo: Geometry) -> None:
    """Every part length > 0 after allowance application."""
    for p in geo.parts:
        for dim in (p.length, p.width):
            if dim.as_cut <= 0:
                raise InvariantError(f"part {p.id} has non-positive as_cut: {dim.as_cut}")


def _inv_flex_span(geo: Geometry) -> None:
    """Unsupported span of any finish-bearing panel below its flex threshold."""
    import math
    for rec in geo.structure.get("spans", []):
        span, limit = rec["unsupported_span"], rec["flex_threshold"]
        if span > limit + TOL:
            # Saying only that it is too long left the loop with nowhere to go: a
            # sofa failed twice on the same seat span. Say how many intermediate
            # supports would carry it, and note the other possibility — that the
            # piece already has supports and the declared span forgot them.
            needed = max(1, math.ceil(span / limit) - 1)
            bay = span / (needed + 1)
            raise InvariantError(
                f"unsupported span {span} exceeds flex threshold {limit} for "
                f"{rec['name']}. Carry it: {needed} intermediate support"
                f"{'s' if needed > 1 else ''} divides the opening into "
                f"{needed + 1} bays of {bay:.1f}in, each inside the limit — add "
                f"them as parts and place them. If the piece ALREADY has supports "
                f"in that opening, the invariant is measuring the whole opening "
                f"instead of the clear distance between them: declare "
                f"unsupported_span as the gap between adjacent supports."
            )


def _inv_continuous_backing(geo: Geometry) -> None:
    """Continuous backing exists behind the full width of every finish-bearing surface."""
    for rec in geo.structure.get("backing", []):
        backing, surface = rec["backing_width"], rec["surface_width"]
        if backing < surface - TOL:
            # A sofa spent four rounds shaving the surface a little at a time —
            # 13in, 10in, 9in, 7.5in — because the message named the mismatch and
            # no way out of it. Both ways out, with the number.
            raise InvariantError(
                f"backing {backing} narrower than finish-bearing surface {surface} "
                f"for {rec['name']}. A surface that carries a finish needs something "
                f"continuous behind its whole width: either widen the backing to "
                f"{surface:g} (the usual answer — make that member as wide as the "
                f"surface it supports), or narrow the surface to {backing:g}. "
                f"Shaving the surface by an inch at a time does not converge."
            )


def _inv_parts_fit_stock(geo: Geometry) -> None:
    """Every part fits stock — as one piece, or as the strips it is glued from."""
    from .glueup import glue_up
    for p in geo.parts:
        mat = get_material(p.material_id)
        # A wide solid panel is checked as the strips the shop actually cuts, not
        # as the finished panel, which no board is wide enough to yield.
        gl = glue_up(p)
        L, W = (gl.strip_length, gl.strip_width) if gl.is_glued else p.cut_wh()
        ok = any(
            (L <= s.w + TOL and W <= s.h + TOL) or (L <= s.h + TOL and W <= s.w + TOL)
            for s in mat.stock_sizes
        )
        if not ok:
            raise InvariantError(
                f"part {p.id} ({L}x{W}) fits no stock size of {p.material_id}. "
                + _stock_remedy(p, mat, L, W)
            )


def _stock_remedy(part, mat, L: float, W: float) -> str:
    """Say what to do, not just what is wrong.

    A design loop given only "fits no stock" shrinks the part an inch at a time and
    never gets there. A 50in x 9in solid side is not a stock-size problem: solid
    panels that wide are edge-glued from narrower boards, which this engine does
    not model, so the workable answer is a sheet good."""
    widest = max((max(s.w, s.h) for s in mat.stock_sizes), default=0.0)
    board_width = max((min(s.w, s.h) for s in mat.stock_sizes), default=0.0)
    long_side, short_side = max(L, W), min(L, W)
    if mat.category in ("lumber", "hardwood"):
        # Width is solvable — a wide panel is edge-glued from strips, and the
        # engine plans that itself. Length is not: no glue-up makes a board longer.
        return (
            f"{mat.display_name} comes up to {widest:g}in long and {board_width:g}in "
            f"wide. A panel wider than that is edge-glued from strips, which is "
            f"planned for you — but this part is {long_side:g}in long, and no glue-up "
            f"makes a board longer than the tree. Shorten it to {widest:g}in or less, "
            f"or give it a sheet-good material (plywood or MDF, in 48x96 panels).")
    return (
        f"Stock comes in {', '.join(f'{s.w:g}x{s.h:g}' for s in mat.stock_sizes)}; "
        f"this part is {long_side:g}x{short_side:g}. Reduce it to fit one of those, "
        f"or choose a material whose stock is large enough.")
