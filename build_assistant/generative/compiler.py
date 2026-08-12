"""Compile a DesignIR into the engine's Geometry — deterministically.

Every number is produced here, by evaluating the agent's formulas over the symbol
table. The allowance layer is applied generically: a part face marked finished is
cut back by the finish system's per-face offset (Lesson 2 direction handled by the
finish system). The result is an ordinary :class:`Geometry`, so nesting, drawing,
document and the release gates all work unchanged.
"""

from __future__ import annotations

from ..catalog.materials import get_material
from ..catalog.finishes import get_finish
from ..core import allowance as A
from ..core.model import (
    Dimension, Element, Face, Part, ScalarField, DerivedDecision, Geometry,
)
from ..core.invariants import check_invariants
from .model import DesignIR
from .evaluator import evaluate, build_symbols


def compile_design(ir: DesignIR, check: bool = True) -> Geometry:
    sym = build_symbols(ir.params, ir.materials, get_material)
    role_mat = {m.role: m.material_id for m in ir.materials}
    fin = get_finish(ir.finish_id)
    s = fin.per_face_offset
    direction = fin.direction if s > 0 else A.ADDITIVE_OUTWARD

    def ev(expr):
        return evaluate(expr, sym)

    # ---- parts ----
    parts: list[Part] = []
    scalars: dict[str, ScalarField] = {}
    for p in ir.parts:
        mid = role_mat.get(p.material_role)
        if mid is None:
            raise ValueError(f"part {p.id}: unknown material role {p.material_role!r}")
        mat = get_material(mid)
        fin_len = ev(p.length_expr)
        fin_wid = ev(p.width_expr)
        cut_len = A.substrate_from_finished(fin_len, s, min(2, p.finished_faces_len), direction) if s else fin_len
        cut_wid = A.substrate_from_finished(fin_wid, s, min(2, p.finished_faces_wid), direction) if s else fin_wid
        qty = max(1, int(round(ev(p.qty_expr))))
        L = Dimension(cut_len, cut_len, fin_len, f"part.{p.id}.length")
        W = Dimension(cut_wid, cut_wid, fin_wid, f"part.{p.id}.width")
        parts.append(Part(p.id, p.name, mid, L, W, mat.actual_thickness, qty,
                          p.grain, "as_cut", p.element, p.joint))
        scalars[f"part.{p.id}.length"] = ScalarField(f"part.{p.id}.length", L.as_cut)
        scalars[f"part.{p.id}.width"] = ScalarField(f"part.{p.id}.width", W.as_cut)

    # ---- params as scalars (provenance) ----
    for pr in ir.params:
        scalars[f"param.{pr.id}"] = ScalarField(f"param.{pr.id}", round(pr.value, 4), pr.unit)

    # ---- elements (finished boxes, for drawings) ----
    elements: list[Element] = []
    for e in ir.elements:
        L = ev(e.length_expr); Wd = ev(e.width_expr); H = ev(e.height_expr)
        elements.append(Element(
            id=e.id, display_name=e.kind.replace("_", " ").title(),
            finished_length=Dimension.uniform(L, f"elem.{e.id}.length"),
            finished_width=Dimension.uniform(Wd, f"elem.{e.id}.width"),
            finished_height=Dimension.uniform(H, f"elem.{e.id}.height"),
            carcass_height=Dimension.uniform(H, f"elem.{e.id}.carcass"),
            faces=tuple(Face(f.name, f.exposed, ir.finish_id if f.finished else "none")
                        for f in e.faces),
            z_base=ev(e.z_base_expr), footprint_inset=0.0,
        ))

    # ---- structure for invariants (opt-in per IR) ----
    structure: dict = {}
    height_layers = []
    for e in ir.elements:
        if e.stacks_height:
            z = ev(e.z_base_expr); h = ev(e.height_expr)
            height_layers.append({"name": e.id, "thickness": h, "z_lo": z, "z_hi": z + h,
                                  "contributes": True})
    for inv in ir.invariants:
        if inv.kind == "span":
            structure.setdefault("spans", []).append({
                "name": inv.params.get("name", "span"),
                "unsupported_span": ev(str(inv.params["unsupported_span"])),
                "flex_threshold": float(inv.params["flex_threshold"])})
        elif inv.kind == "backing":
            structure.setdefault("backing", []).append({
                "name": inv.params.get("name", "backing"),
                "surface_width": ev(str(inv.params["surface_width"])),
                "backing_width": ev(str(inv.params["backing_width"]))})
        elif inv.kind == "height_stack" and height_layers:
            structure["height_layers"] = height_layers
            oh = ev(str(inv.params.get("overall_height", "0")))
            scalars["overall_height"] = ScalarField("overall_height", round(oh, 4))

    # ---- derived decisions ----
    derived = tuple(DerivedDecision(f"derived.{i}", d.label, d.value, d.basis, d.is_overridable)
                    for i, d in enumerate(ir.derived))

    # operations / joints carried for the document + tool schedule
    structure["operations"] = set(ir.operations)
    structure["fasteners"] = ir.fasteners
    structure["summary"] = ir.summary
    structure["node_kind"] = ir.node_kind
    structure["warnings"] = ir.warnings

    geo = Geometry(
        node=ir.node_kind, elements=tuple(elements), parts=tuple(parts), scalars=scalars,
        derived_decisions=derived, finish_id=ir.finish_id, per_face_offset=s,
        inputs={"name": ir.name, "node_kind": ir.node_kind}, structure=structure,
    )
    if check:
        check_invariants(geo)     # hard failure on any violation (Law 5 upstream)
    return geo
