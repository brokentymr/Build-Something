"""coffee_table leaf node — schema + geometry recipe.

This module is *node data*, not engine. It declares the assembly relationships
(which faces are exposed, what stacks co-planar, which allowance direction
applies) and calls the engine's allowance primitives to do every piece of
arithmetic. No number here is typed as a literal answer; each is derived from the
seven inputs and the catalog via :mod:`build_assistant.core.allowance`.

Reproduces the reference fixture in brief section 2.5 exactly.
"""

from __future__ import annotations

from ..catalog.materials import get_material
from ..catalog.finishes import get_finish
from ..core import allowance as A
from ..core.model import (
    Dimension, Element, Face, Part, ScalarField, DerivedDecision,
)
from ..parts.joinery import Joint, JoineryTemplate

NODE_ID = "coffee_table"

# ---- schema metadata (Phase 7 shape, carried now for the node registry) ----
SCHEMA = {
    "id": NODE_ID,
    "display_name": "Coffee table",
    "mode": "hybrid",
    "rough_dimension_fields": ["overall_length", "overall_width", "overall_height"],
    "required_fields": [
        "overall_length", "overall_width", "overall_height",
        "slab_edge_thickness", "base_type", "finish_system", "plinth_inset", "assembly",
    ],
    "defaults": {"base_type": "plinth", "assembly": "single_monolith"},
    "joinery_default": "closed_torsion_box",
    "structural_notice": None,
}

JOINERY = JoineryTemplate(
    id="closed_torsion_box",
    applies_to=(NODE_ID,),
    is_default=True,
    description="Closed torsion-box slab on a butt-jointed plinth box, mesh-reinforced "
                "butt corners under a continuous microcement coating.",
)

# The carcass panel material for this build path (see materials.py note: 0.75).
CARCASS_MATERIAL = "ply_075_structural"
MICROCEMENT_DENSITY = 90.0  # lb/cuft, troweled overlay (for the weight estimate)
FLEX_THRESHOLD = 8.0        # max unsupported bay for a 3/4 finish-bearing deck


def _dim_additive(finished: float, offset: float, exposed: int, field_id: str) -> Dimension:
    """Triple for an outward-finished part: cut smaller, finished larger."""
    cut = A.substrate_from_finished(finished, offset, exposed, A.ADDITIVE_OUTWARD)
    return Dimension(as_cut=cut, as_assembled=cut, as_finished=finished, field_id=field_id)


def _dim_internal(value: float, field_id: str) -> Dimension:
    """Triple for a concealed internal part: identical across stages."""
    return Dimension.uniform(value, field_id)


def build(answers: dict) -> "SolveDraft":
    """Pure geometry recipe. Returns a draft the solver validates and freezes."""
    fin = get_finish(answers["finish_system"])
    s = fin.per_face_offset                      # 0.375
    mat = get_material(CARCASS_MATERIAL)
    t = mat.actual_thickness                     # 0.75

    L = float(answers["overall_length"])         # 42
    W = float(answers["overall_width"])          # 20
    H = float(answers["overall_height"])         # 16
    edge = float(answers["slab_edge_thickness"]) # 3
    reveal = float(answers["plinth_inset"])      # 3

    # ---- SLAB (closed torsion box, all exposed faces skinned) --------------
    slab_carcass_thickness = A.substrate_from_finished(edge, s, 2, A.ADDITIVE_OUTWARD)  # 2.25
    deck_len = A.substrate_from_finished(L, s, 2, A.ADDITIVE_OUTWARD)  # 41.25
    deck_wid = A.substrate_from_finished(W, s, 2, A.ADDITIVE_OUTWARD)  # 19.25

    # Core ring width == underside reveal band (continuous-backing invariant).
    ring_width = reveal                                                # 3.0

    # Rib count: fewest ribs keeping every bay below the flex threshold.
    interior_len = deck_len - 2 * ring_width                           # 35.25
    rib_count = 1
    while True:
        bay_width = (interior_len - rib_count * ring_width) / (rib_count + 1)
        if bay_width <= FLEX_THRESHOLD:
            break
        rib_count += 1
    rib_left_edges = [
        ring_width + k * bay_width + (k - 1) * ring_width for k in range(1, rib_count + 1)
    ]

    # ---- PLINTH (box; top concealed under slab, bottom on floor) -----------
    carcass_inset = A.carcass_inset_from_reveal(reveal, s, 1)          # 3.375
    fp_len = L - 2 * carcass_inset                                     # 35.25
    fp_wid = W - 2 * carcass_inset                                     # 13.25
    plinth_carcass_h = H - slab_carcass_thickness - s                 # 13.375
    plinth_visible_h = A.visible_after_occlusion(plinth_carcass_h, s)  # 13.0

    # ---- parts (Phase 2) ----------------------------------------------------
    ch = Dimension(as_cut=plinth_carcass_h, as_assembled=plinth_carcass_h,
                   as_finished=plinth_visible_h, field_id="plinth.carcass_height")
    parts: list[Part] = [
        Part("A", "slab top deck", CARCASS_MATERIAL,
             _dim_additive(L, s, 2, "slab.deck.length"),
             _dim_additive(W, s, 2, "slab.deck.width"), t, 1, "length", "as_cut", "slab", "glue+brad to core"),
        Part("B", "slab bottom deck", CARCASS_MATERIAL,
             _dim_additive(L, s, 2, "slab.deck.length"),
             _dim_additive(W, s, 2, "slab.deck.width"), t, 1, "length", "as_cut", "slab", "glue+brad to core"),
        Part("C", "core rail, long", CARCASS_MATERIAL,
             _dim_internal(deck_len, "slab.core_rail_long.length"),
             _dim_internal(ring_width, "slab.core_ring_width"), t, 2, "length", "as_cut", "slab", "butt to end rails"),
        Part("D", "core rail, end", CARCASS_MATERIAL,
             _dim_internal(deck_wid - 2 * ring_width, "slab.core_rail_end.length"),
             _dim_internal(ring_width, "slab.core_ring_width"), t, 2, "length", "as_cut", "slab", "butt between long rails"),
        Part("E", "core rib", CARCASS_MATERIAL,
             _dim_internal(deck_wid - 2 * ring_width, "slab.rib.length"),
             _dim_internal(ring_width, "slab.core_ring_width"), t, rib_count, "length", "as_cut", "slab", "butt between long rails"),
        Part("F", "plinth long side", CARCASS_MATERIAL,
             Dimension(fp_len, fp_len, fp_len + 2 * s, "plinth.long_side.length"),
             ch, t, 2, "length", "as_cut", "plinth", "butt corner, mesh-reinforced"),
        Part("G", "plinth end panel", CARCASS_MATERIAL,
             _dim_internal(fp_wid - 2 * t, "plinth.end_panel.length"),
             ch, t, 2, "length", "as_cut", "plinth", "butt into long sides"),
        Part("H", "plinth platform", CARCASS_MATERIAL,
             _dim_internal(fp_len - 2 * t, "plinth.platform.length"),
             _dim_internal(fp_wid - 2 * t, "plinth.platform.width"), t, 2, "length", "as_cut", "plinth", "pocket-screw to walls"),
    ]

    # ---- scalars (every fixture-table field, with stable field ids) --------
    scalars = _scalars(
        skin_per_face_offset=s,
        slab_carcass_thickness=slab_carcass_thickness,
        deck_len=deck_len, deck_wid=deck_wid, ring_width=ring_width,
        rib_count=rib_count, bay_width=bay_width, rib_left_edges=rib_left_edges,
        plinth_carcass_h=plinth_carcass_h, plinth_visible_h=plinth_visible_h,
        fp_len=fp_len, fp_wid=fp_wid, t=t,
        carcass_inset=carcass_inset, reveal=reveal, H=H,
    )

    # ---- coated area + weight (approximate outputs) ------------------------
    coated_area_sqin = _coated_area(L, W, H, edge, reveal, plinth_visible_h)
    scalars["coated_area"] = ScalarField("coated_area", round(coated_area_sqin / 144.0, 3), "sqft")
    weight = _weight(parts, coated_area_sqin, s)
    scalars["weight_estimate"] = ScalarField("weight_estimate", round(weight, 1), "lb")

    # ---- structure payload for the invariant checker -----------------------
    structure = {
        "height_layers": [
            {"name": "plinth_carcass", "thickness": plinth_carcass_h,
             "z_lo": 0.0, "z_hi": plinth_carcass_h, "contributes": True},
            {"name": "slab_carcass", "thickness": slab_carcass_thickness,
             "z_lo": plinth_carcass_h, "z_hi": plinth_carcass_h + slab_carcass_thickness,
             "contributes": True},
            {"name": "slab_top_skin", "thickness": s,
             "z_lo": plinth_carcass_h + slab_carcass_thickness,
             "z_hi": plinth_carcass_h + slab_carcass_thickness + s, "contributes": True},
            # co-planar: the slab underside reveal skin sits outboard of the plinth,
            # co-planar with the plinth's top 3/8 — it does NOT stack (Lesson 1).
            {"name": "slab_underside_reveal_skin", "thickness": s,
             "z_lo": plinth_carcass_h - s, "z_hi": plinth_carcass_h, "contributes": False},
        ],
        "reveals": {"left": reveal, "right": reveal, "front": reveal, "back": reveal},
        "inset_checks": [{
            "element": "plinth", "carcass_inset": carcass_inset,
            "reveal_finished": reveal, "offset": s, "exposed_faces": 1,
        }],
        "spans": [{"name": "slab_deck_bay", "unsupported_span": bay_width,
                   "flex_threshold": FLEX_THRESHOLD}],
        "backing": [{"name": "slab_underside_reveal", "surface_width": reveal,
                     "backing_width": ring_width}],
        "rib_left_edges": rib_left_edges,
        "boxes": _placement(
            deck_len=deck_len, deck_wid=deck_wid, t=t, ring_width=ring_width,
            rib_left_edges=rib_left_edges, plinth_carcass_h=plinth_carcass_h,
            carcass_inset=carcass_inset, fp_len=fp_len, fp_wid=fp_wid, L=L, W=W),
        "node_kind": "coffee_table",
        "summary": "Micro-cement coffee table: torsion-box slab on a recessed plinth.",
    }

    # ---- elements ----------------------------------------------------------
    elements = (
        Element(
            id="slab", display_name="Top slab (closed torsion box)",
            finished_length=Dimension.uniform(L, "slab.finished_length"),
            finished_width=Dimension.uniform(W, "slab.finished_width"),
            finished_height=Dimension.uniform(edge, "slab.finished_edge_thickness"),
            carcass_height=Dimension.uniform(slab_carcass_thickness, "slab.carcass_thickness"),
            faces=(
                Face("top", True, fin.id), Face("bottom", True, fin.id, occluded_depth=0.0),
                Face("left", True, fin.id), Face("right", True, fin.id),
                Face("front", True, fin.id), Face("back", True, fin.id),
            ),
            z_base=plinth_carcass_h, footprint_inset=0.0,
        ),
        Element(
            id="plinth", display_name="Plinth base",
            finished_length=Dimension.uniform(L - 2 * reveal, "plinth.finished_length"),
            finished_width=Dimension.uniform(W - 2 * reveal, "plinth.finished_width"),
            finished_height=Dimension(plinth_carcass_h, plinth_carcass_h, plinth_visible_h,
                                      "plinth.height"),
            carcass_height=ch,
            faces=(
                Face("top", False, "none", occluded_depth=s),   # concealed under slab
                Face("bottom", False, "none"),                  # on the floor
                Face("left", True, fin.id), Face("right", True, fin.id),
                Face("front", True, fin.id), Face("back", True, fin.id),
            ),
            z_base=0.0, footprint_inset=reveal,
        ),
    )

    joints, operations = _joinery(parts, plinth_carcass_h, fp_len, fp_wid, deck_len, deck_wid, rib_count, ring_width)
    skins = _skin_panels(L, W, edge, reveal, plinth_visible_h, fin)
    derived = _derived_decisions(ring_width, reveal, rib_count, bay_width)

    return SolveDraft(
        node=NODE_ID, elements=elements, parts=tuple(parts), scalars=scalars,
        derived_decisions=derived, finish_id=fin.id, per_face_offset=s,
        structure=structure, joints=joints, operations=operations, skins=skins,
    )


def _scalars(**kw) -> dict[str, ScalarField]:
    S = {}

    def add(fid, val, unit="in"):
        S[fid] = ScalarField(fid, round(val, 6), unit)

    add("skin.per_face_offset", kw["skin_per_face_offset"])
    add("slab.carcass_thickness", kw["slab_carcass_thickness"])
    add("slab.deck.length", kw["deck_len"])
    add("slab.deck.width", kw["deck_wid"])
    add("slab.core_ring_width", kw["ring_width"])
    add("slab.rib_count", kw["rib_count"], "count")
    add("slab.bay_width", kw["bay_width"])
    for i, e in enumerate(kw["rib_left_edges"], 1):
        add(f"slab.rib_left_edge.{i}", e)
    add("plinth.carcass_height.as_cut", kw["plinth_carcass_h"])
    add("plinth.height.as_finished", kw["plinth_visible_h"])
    add("plinth.long_side.length", kw["fp_len"])
    add("plinth.long_side.height", kw["plinth_carcass_h"])
    add("plinth.end_panel.length", kw["fp_wid"] - 2 * kw["t"])
    add("plinth.end_panel.height", kw["plinth_carcass_h"])
    add("plinth.platform.length", kw["fp_len"] - 2 * kw["t"])
    add("plinth.platform.width", kw["fp_wid"] - 2 * kw["t"])
    add("plinth.inset.as_assembled", kw["carcass_inset"])
    add("plinth.inset.as_finished", kw["reveal"])
    add("overall_height", kw["H"])
    return S


def _coated_area(L, W, H, edge, reveal, plinth_h) -> float:
    """Sum of exposed, finish-bearing faces (sq in). Approximate fixture output."""
    slab_top = L * W
    slab_edges = 2 * (L + W) * edge
    plinth_fp_len, plinth_fp_wid = L - 2 * reveal, W - 2 * reveal
    slab_underside_reveal = L * W - plinth_fp_len * plinth_fp_wid
    plinth_sides = 2 * (plinth_fp_len + plinth_fp_wid) * plinth_h
    return slab_top + slab_edges + slab_underside_reveal + plinth_sides


def _weight(parts, coated_area_sqin, s) -> float:
    mat = get_material(CARCASS_MATERIAL)
    ply_vol = sum(p.area_as_cut() * p.qty for p in parts) * mat.actual_thickness  # cu in
    ply_lb = ply_vol / 1728.0 * mat.density_lb_per_cuft
    cb = get_material("cement_board_025")
    cb_lb = coated_area_sqin * cb.actual_thickness / 1728.0 * cb.density_lb_per_cuft
    mc_lb = coated_area_sqin * 0.125 / 1728.0 * MICROCEMENT_DENSITY
    return ply_lb + cb_lb + mc_lb


def _joinery(parts, plinth_h, fp_len, fp_wid, deck_len, deck_wid, rib_count, ring_width):
    joints: list[Joint] = []
    # Plinth corner butt joints: 4 corners, screws up the height.
    for i in range(4):
        joints.append(Joint(f"plinth_corner_{i+1}", "screw_cabinet_2in", plinth_h, 4.0, 1,
                            "drill_pilot_countersink"))
    # Plinth platforms pocket-screwed to walls (2 platforms, perimeter seam).
    plat_perim = 2 * ((fp_len - 1.5) + (fp_wid - 1.5))
    for i in range(2):
        joints.append(Joint(f"plinth_platform_{i+1}", "pocket_screw", plat_perim, 6.0, 1, "pocket_screw"))
    # Slab decks glued + bradded to the core ring and ribs, both decks.
    ring_perim = 2 * (deck_len + deck_wid)
    rib_seam = rib_count * (deck_wid - 2 * ring_width)
    for deck in ("top", "bottom"):
        joints.append(Joint(f"slab_{deck}_ring", "brad_18ga_1in", ring_perim, 4.0, 1, "brad_nail"))
        joints.append(Joint(f"slab_{deck}_ribs", "brad_18ga_1in", rib_seam, 4.0, 1, "brad_nail"))
    # Cement board fastened to substrate over all skinned faces.
    joints.append(Joint("skin_fastening", "cement_board_screw_1_25in",
                        2 * (deck_len + deck_wid) + 2 * (fp_len + fp_wid), 6.0, 1,
                        "drive_cement_board_screw"))
    operations = {
        "rip_sheet_goods", "crosscut_panels", "drill_pilot_countersink",
        "drive_cabinet_screw", "pocket_screw", "brad_nail",
        "cut_cement_board", "drive_cement_board_screw", "trowel_microcement",
    }
    return tuple(joints), operations


def _skin_panels(L, W, edge, reveal, plinth_h, fin):
    """Cement-board skin panels, one set of pieces per exposed face group.

    13 pieces total (see nesting fixture: 11 on sheet 1, 2 on sheet 2)."""
    pfl, pfw = L - 2 * reveal, W - 2 * reveal   # plinth finished footprint 36 x 14
    band = reveal                               # underside reveal band width
    panels = [
        ("S1", "slab top", L, W, 1),
        ("S2", "slab edge, long", L, edge, 2),
        ("S3", "slab edge, end", W, edge, 2),
        ("S4", "slab underside reveal, long", L, band, 2),
        ("S5", "slab underside reveal, end", pfw, band, 2),
        ("S6", "plinth side, long", pfl, plinth_h, 2),
        ("S7", "plinth side, end", pfw, plinth_h, 2),
    ]
    return panels


def _derived_decisions(ring_width, reveal, rib_count, bay_width) -> tuple[DerivedDecision, ...]:
    return (
        DerivedDecision(
            "derived.substrate", "Finish substrate", "1/4 in cement board",
            "Microcement requires a rigid, dimensionally-stable substrate; troweled over "
            "bare plywood it flexes and the coating crazes. Cement board is the backing.",
            is_overridable=False),
        DerivedDecision(
            "derived.core_ring_width", "Core ring width", f'{ring_width:g} in',
            f"Set equal to the {reveal:g} in underside reveal band so continuous backing "
            "sits behind the full width of the finish-bearing underside (backing invariant).",
            is_overridable=False),
        DerivedDecision(
            "derived.rib_count", "Torsion-box rib count", f"{rib_count}",
            f"Fewest ribs keeping every bay ({bay_width:.4g} in) below the {FLEX_THRESHOLD:g} in "
            "flex threshold for a 3/4 in finish-bearing deck.",
            is_overridable=True),
        DerivedDecision(
            "derived.joint_type", "Corner joinery", "Butt joints, mesh-reinforced",
            "A mesh-reinforced butt corner under a continuous coating is stronger than a "
            "mitered one; a miter opens a hairline the microcement telegraphs.",
            is_overridable=True),
        DerivedDecision(
            "derived.excluded_fastener", "Excluded fastener", "No drywall screws",
            "Drywall screws snap under the head in cement board. Wafer-head cement-board "
            "screws are specified instead.",
            is_overridable=False),
    )


# Lightweight draft container the solver freezes into a Geometry.
from dataclasses import dataclass  # noqa: E402


@dataclass
class SolveDraft:
    node: str
    elements: tuple
    parts: tuple
    scalars: dict
    derived_decisions: tuple
    finish_id: str
    per_face_offset: float
    structure: dict
    joints: tuple
    operations: set
    skins: list


def _placement(*, deck_len, deck_wid, t, ring_width, rib_left_edges,
               plinth_carcass_h, carcass_inset, fp_len, fp_wid, L, W) -> list[dict]:
    """Where every part sits in the assembled object.

    The solver computes sizes; this says where they go. Without it the drawing set
    has nothing to project — elevations, sections, joint details and the placement
    audit all read from here — and a curated node could only ever produce the older,
    thinner document. Origin is the front-left-bottom corner of the finished piece.

    Boxes are carcass geometry, so the slab decks sit inboard by the finish
    thickness the skin will add back.
    """
    boxes: list[dict] = []

    def add(pid, x, y, z, w, d, h):
        boxes.append({"id": pid, "x": round(x, 4), "y": round(y, 4), "z": round(z, 4),
                      "w": round(w, 4), "d": round(d, 4), "h": round(h, 4)})

    # --- plinth: a box of two long walls, two end panels, two platforms -----
    px, py = carcass_inset, carcass_inset
    add("F", px, py, 0.0, fp_len, t, plinth_carcass_h)                    # front wall
    add("F", px, py + fp_wid - t, 0.0, fp_len, t, plinth_carcass_h)       # back wall
    add("G", px, py + t, 0.0, t, fp_wid - 2 * t, plinth_carcass_h)        # left end
    add("G", px + fp_len - t, py + t, 0.0, t, fp_wid - 2 * t, plinth_carcass_h)
    add("H", px + t, py + t, 0.0, fp_len - 2 * t, fp_wid - 2 * t, t)      # floor platform
    add("H", px + t, py + t, plinth_carcass_h - t, fp_len - 2 * t, fp_wid - 2 * t, t)

    # --- slab: bottom deck, core ring and ribs, top deck --------------------
    sx, sy = (L - deck_len) / 2, (W - deck_wid) / 2
    z0 = plinth_carcass_h
    add("B", sx, sy, z0, deck_len, deck_wid, t)                           # bottom deck
    core_z = z0 + t
    add("C", sx, sy, core_z, deck_len, ring_width, t)                     # long rail, front
    add("C", sx, sy + deck_wid - ring_width, core_z, deck_len, ring_width, t)
    inner_d = deck_wid - 2 * ring_width
    add("D", sx, sy + ring_width, core_z, ring_width, inner_d, t)         # end rail, left
    add("D", sx + deck_len - ring_width, sy + ring_width, core_z, ring_width, inner_d, t)
    for edge in rib_left_edges:
        add("E", sx + edge, sy + ring_width, core_z, ring_width, inner_d, t)
    add("A", sx, sy, core_z + t, deck_len, deck_wid, t)                   # top deck
    return boxes
