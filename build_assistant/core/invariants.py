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
    for rec in geo.structure.get("spans", []):
        if rec["unsupported_span"] > rec["flex_threshold"] + TOL:
            raise InvariantError(
                f"unsupported span {rec['unsupported_span']} exceeds flex threshold "
                f"{rec['flex_threshold']} for {rec['name']}"
            )


def _inv_continuous_backing(geo: Geometry) -> None:
    """Continuous backing exists behind the full width of every finish-bearing surface."""
    for rec in geo.structure.get("backing", []):
        if rec["backing_width"] < rec["surface_width"] - TOL:
            raise InvariantError(
                f"backing {rec['backing_width']} narrower than finish-bearing surface "
                f"{rec['surface_width']} for {rec['name']}"
            )


def _inv_parts_fit_stock(geo: Geometry) -> None:
    """Every part fits at least one stock size in at least one orientation."""
    for p in geo.parts:
        mat = get_material(p.material_id)
        L, W = p.cut_wh()
        ok = any(
            (L <= s.w + TOL and W <= s.h + TOL) or (L <= s.h + TOL and W <= s.w + TOL)
            for s in mat.stock_sizes
        )
        if not ok:
            raise InvariantError(
                f"part {p.id} ({L}x{W}) fits no stock size of {p.material_id}"
            )
