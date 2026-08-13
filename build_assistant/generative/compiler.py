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
from .model import DesignIR, THROUGH_JOINTS
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
    boxes: list[dict] = []
    joinery: dict[str, dict] = {}
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
        # machined joinery this part receives (drives the joint detail profile)
        if p.joint_type and p.joint_type != "butt":
            # A housing cut goes about a third into its member; a tenon, lap or
            # dowel goes right through into the other part, so an undeclared depth
            # defaults to the member's own thickness rather than a third of it.
            through = p.joint_type in THROUGH_JOINTS
            default = mat.actual_thickness if through else mat.actual_thickness / 3.0
            depth = ev(p.joint_depth_expr) if p.joint_depth_expr else default
            joinery[p.id] = {"type": p.joint_type, "depth": round(max(0.0, depth), 4)}
        # 3D placement (for hero drawings): one box per instance
        if p.has_box():
            bx, by, bz = ev(p.box_x or "0"), ev(p.box_y or "0"), ev(p.box_z or "0")
            bw, bd, bh = ev(p.box_w), ev(p.box_d), ev(p.box_h)
            sx, sy, sz = ev(p.step_x or "0"), ev(p.step_y or "0"), ev(p.step_z or "0")
            for k in range(qty):
                boxes.append({"id": p.id, "name": p.name,
                              "x": bx + k * sx, "y": by + k * sy, "z": bz + k * sz,
                              "w": bw, "d": bd, "h": bh})

    # ---- params as scalars (provenance) ----
    for pr in ir.params:
        scalars[f"param.{pr.id}"] = ScalarField(f"param.{pr.id}", round(pr.value, 4), pr.unit)

    # ---- weight estimate (material volume x density) ----
    lb = 0.0
    for part in parts:
        m = get_material(part.material_id)
        lb += part.area_as_cut() * part.thickness * part.qty / 1728.0 * m.density_lb_per_cuft
    if s > 0 and fin.substrate_material_id:
        from ..catalog.materials import get_material as gm
        sub = gm(fin.substrate_material_id)
        # rough: skin area ~ finished exposed area; approximate as total part face area
        skin_area = sum(p.area_as_cut() * p.qty for p in parts)
        lb += skin_area * sub.actual_thickness / 1728.0 * sub.density_lb_per_cuft * 0.5
    scalars["weight_estimate"] = ScalarField("weight_estimate", round(lb, 1), "lb")

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
    structure["boxes"] = boxes
    structure["joinery"] = joinery
    # Designer-directed sections: the agent picks where to slice and says why;
    # the engine evaluates the position and draws it.
    secs = []
    for x in ir.sections:
        try:
            secs.append({"tag": x.tag, "axis": x.axis, "at": round(ev(x.at_expr), 4),
                         "why": x.why})
        except Exception:  # noqa: BLE001
            continue
    structure["sections"] = secs
    # Register the assembled bounding-box dimensions as solver scalars so the
    # cover's "overall" dims trace (Gate 1). These are engine-computed from the
    # part placements, not authored.
    if boxes:
        xs = [b["x"] for b in boxes] + [b["x"] + b["w"] for b in boxes]
        ys = [b["y"] for b in boxes] + [b["y"] + b["d"] for b in boxes]
        zs = [b["z"] for b in boxes] + [b["z"] + b["h"] for b in boxes]
        scalars["overall.width"] = ScalarField("overall.width", round(max(xs) - min(xs), 4))
        scalars["overall.depth"] = ScalarField("overall.depth", round(max(ys) - min(ys), 4))
        scalars["overall.height"] = ScalarField("overall.height", round(max(zs) - min(zs), 4))

    geo = Geometry(
        node=ir.node_kind, elements=tuple(elements), parts=tuple(parts), scalars=scalars,
        derived_decisions=derived, finish_id=ir.finish_id, per_face_offset=s,
        inputs={"name": ir.name, "node_kind": ir.node_kind}, structure=structure,
    )
    if check:
        check_invariants(geo)     # hard failure on any violation (Law 5 upstream)
    return geo
