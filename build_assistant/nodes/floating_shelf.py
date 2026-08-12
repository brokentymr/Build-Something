"""floating_shelf leaf node — proves the architecture (Definition of Done, final).

Added with schema + joinery + recipe data only. It solves, nests, draws and
documents through the *unchanged* engine (solver, allowance, invariants, nesting,
drawing, document, gates). If adding this node had required touching the solver,
the abstraction boundary would be wrong. It does not.

A wall-hung hollow shelf: a shallow torsion box skinned on every face except the
back, which is concealed against the wall (Lesson 3 — exposure is assembly, not
geometry).
"""

from __future__ import annotations

from ..catalog.materials import get_material
from ..catalog.finishes import get_finish
from ..core import allowance as A
from ..core.model import Dimension, Element, Face, Part, ScalarField, DerivedDecision
from ..parts.joinery import Joint, JoineryTemplate
from ..elicitation.question_graph import Question, Option
from .coffee_table import SolveDraft, CARCASS_MATERIAL

NODE_ID = "floating_shelf"

SCHEMA = {
    "id": NODE_ID,
    "display_name": "Floating shelf",
    "mode": "hybrid",
    "rough_dimension_fields": ["overall_length", "overall_depth", "overall_thickness"],
    "required_fields": ["overall_length", "overall_depth", "overall_thickness", "finish_system"],
    "defaults": {"finish_system": "paint_buildup"},
    "joinery_default": "shallow_torsion_box",
    "structural_notice": "Wall fixing must hit studs or use rated anchors — verify locally.",
}

JOINERY = JoineryTemplate(
    id="shallow_torsion_box", applies_to=(NODE_ID,), is_default=True,
    description="Shallow torsion box skinned on all faces but the wall-concealed back.",
)

RING = 2.0
FLEX_THRESHOLD = 12.0

QUESTIONS = [
    Question(id="q_len", field="overall_length", prompt="How long a shelf?",
             type="numeric", options=(), required=True, downstream_impact=100,
             numeric_presets=(24, 36, 48, 60), unit="in"),
    Question(id="q_depth", field="overall_depth", prompt="How deep?",
             type="numeric", options=(), required=True, downstream_impact=90,
             numeric_presets=(8, 10, 12), unit="in"),
    Question(id="q_thick", field="overall_thickness", prompt="How thick should it read?",
             type="numeric", options=(), required=True, downstream_impact=80,
             numeric_presets=(2, 2.5, 3), unit="in"),
    Question(id="q_finish", field="finish_system", prompt="Finish?",
             type="choice", required=True, downstream_impact=60,
             options=(Option("paint_buildup", "Painted"),
                      Option("veneer_backed", "Wood veneer"),
                      Option("microcement_over_cement_board", "Microcement"))),
]


def build(answers: dict) -> SolveDraft:
    fin = get_finish(answers["finish_system"])
    s = fin.per_face_offset
    t = get_material(CARCASS_MATERIAL).actual_thickness
    L = float(answers["overall_length"])
    D = float(answers["overall_depth"])
    TH = float(answers["overall_thickness"])

    carcass_th = A.substrate_from_finished(TH, s, 2, A.ADDITIVE_OUTWARD)   # top+bottom skinned
    if carcass_th <= 0:
        raise ValueError("shelf too thin for this finish system")
    deck_len = A.substrate_from_finished(L, s, 2, A.ADDITIVE_OUTWARD)      # both ends exposed
    deck_depth = A.substrate_from_finished(D, s, 1, A.ADDITIVE_OUTWARD)    # front exposed, back concealed

    interior = deck_len - 2 * RING
    rib_count = 1
    while (interior - rib_count * RING) / (rib_count + 1) > FLEX_THRESHOLD:
        rib_count += 1
    bay = (interior - rib_count * RING) / (rib_count + 1)

    def d_add(finished, exposed, fid):
        cut = A.substrate_from_finished(finished, s, exposed, A.ADDITIVE_OUTWARD)
        return Dimension(cut, cut, finished, fid)

    def d_int(v, fid):
        return Dimension.uniform(v, fid)

    parts = [
        Part("A", "shelf top deck", CARCASS_MATERIAL,
             d_add(L, 2, "shelf.deck.length"), d_add(D, 1, "shelf.deck.depth"),
             t, 1, "length", "as_cut", "shelf", "glue+brad to core"),
        Part("B", "shelf bottom deck", CARCASS_MATERIAL,
             d_add(L, 2, "shelf.deck.length"), d_add(D, 1, "shelf.deck.depth"),
             t, 1, "length", "as_cut", "shelf", "glue+brad to core"),
        Part("C", "front rail", CARCASS_MATERIAL,
             d_int(deck_len, "shelf.rail.length"), d_int(RING, "shelf.ring_width"),
             t, 1, "length", "as_cut", "shelf", "butt to end caps"),
        Part("D", "back rail", CARCASS_MATERIAL,
             d_int(deck_len, "shelf.rail.length"), d_int(RING, "shelf.ring_width"),
             t, 1, "length", "as_cut", "shelf", "butt to end caps"),
        Part("E", "end cap", CARCASS_MATERIAL,
             d_int(deck_depth - 2 * RING, "shelf.endcap.length"), d_int(RING, "shelf.ring_width"),
             t, 2, "length", "as_cut", "shelf", "butt between rails"),
        Part("F", "rib", CARCASS_MATERIAL,
             d_int(deck_depth - 2 * RING, "shelf.rib.length"), d_int(RING, "shelf.ring_width"),
             t, rib_count, "length", "as_cut", "shelf", "butt between rails"),
    ]

    scalars = {}

    def sc(fid, v, unit="in"):
        scalars[fid] = ScalarField(fid, round(v, 6), unit)

    sc("skin.per_face_offset", s)
    sc("shelf.carcass_thickness", carcass_th)
    sc("shelf.deck.length", deck_len)
    sc("shelf.deck.depth", deck_depth)
    sc("shelf.ring_width", RING)
    sc("shelf.rib_count", rib_count, "count")
    sc("shelf.bay_width", bay)
    sc("overall_height", TH)   # generic overall for downstream (doc/QC)

    structure = {
        "height_layers": [
            {"name": "bottom_skin", "thickness": s, "z_lo": 0.0, "z_hi": s, "contributes": True},
            {"name": "carcass", "thickness": carcass_th, "z_lo": s, "z_hi": s + carcass_th,
             "contributes": True},
            {"name": "top_skin", "thickness": s, "z_lo": s + carcass_th,
             "z_hi": TH, "contributes": True},
        ],
        "reveals": {},
        "inset_checks": [],
        "spans": [{"name": "shelf_bay", "unsupported_span": bay, "flex_threshold": FLEX_THRESHOLD}],
        "backing": [{"name": "shelf_front", "surface_width": carcass_th, "backing_width": carcass_th}],
        "rib_left_edges": [RING + k * bay + (k - 1) * RING for k in range(1, rib_count + 1)],
        "boxes": _placement(deck_len=deck_len, deck_depth=deck_depth, t=t,
                            carcass_th=carcass_th, skin=s, L=L, D=D,
                            ribs=[RING + k * bay + (k - 1) * RING
                                  for k in range(1, rib_count + 1)]),
        "node_kind": "floating_shelf",
        "summary": "Shallow torsion-box shelf, skinned and coated as one piece.",
    }

    elements = (
        Element(
            id="shelf", display_name="Floating shelf",
            finished_length=Dimension.uniform(L, "shelf.finished_length"),
            finished_width=Dimension.uniform(D, "shelf.finished_depth"),
            finished_height=Dimension.uniform(TH, "shelf.finished_thickness"),
            carcass_height=Dimension.uniform(carcass_th, "shelf.carcass_thickness"),
            faces=(
                Face("top", True, fin.id), Face("bottom", True, fin.id),
                Face("front", True, fin.id), Face("back", False, "none"),  # against wall
                Face("left", True, fin.id), Face("right", True, fin.id),
            ),
            z_base=0.0, footprint_inset=0.0,
        ),
    )

    joints = (
        Joint("shelf_corners", "screw_cabinet_1_25in", 2 * (deck_len + deck_depth), 4.0, 1,
              "drill_pilot_countersink"),
        Joint("shelf_decks", "brad_18ga_1in", 2 * (deck_len + deck_depth), 4.0, 2, "brad_nail"),
    )
    operations = {"rip_sheet_goods", "crosscut_panels", "drill_pilot_countersink",
                  "drive_cabinet_screw", "brad_nail"}
    if fin.substrate_material_id:
        operations |= {"cut_cement_board", "drive_cement_board_screw", "trowel_microcement"}

    skins = [
        ("S1", "shelf top", L, D, 1),
        ("S2", "shelf front", L, TH, 1),
        ("S3", "shelf end", D, TH, 2),
        ("S4", "shelf bottom", L, D, 1),
    ] if fin.per_face_offset > 0 else []

    derived = (
        DerivedDecision("derived.ring_width", "Core ring width", f"{RING:g} in",
                        "Perimeter frame for the shallow torsion box; carries the wall fixing load.",
                        is_overridable=True),
        DerivedDecision("derived.rib_count", "Rib count", f"{rib_count}",
                        f"Fewest ribs keeping each bay ({bay:.3g} in) under the "
                        f"{FLEX_THRESHOLD:g} in flex threshold.", is_overridable=True),
    )

    return SolveDraft(
        node=NODE_ID, elements=elements, parts=tuple(parts), scalars=scalars,
        derived_decisions=derived, finish_id=fin.id, per_face_offset=s,
        structure=structure, joints=joints, operations=operations, skins=skins,
    )


def _placement(*, deck_len, deck_depth, t, carcass_th, skin, L, D, ribs) -> list[dict]:
    """Where every part sits. The solver sizes them; this places them, so the same
    drawing set and placement audit that serve an agent-authored design serve this
    one too. Origin is the front-left-bottom corner of the finished shelf."""
    boxes: list[dict] = []

    def add(pid, x, y, z, w, d, h):
        boxes.append({"id": pid, "x": round(x, 4), "y": round(y, 4), "z": round(z, 4),
                      "w": round(w, 4), "d": round(d, 4), "h": round(h, 4)})

    ox = (L - deck_len) / 2          # skin is added back on both ends
    oy = 0.0                         # front face skinned, back sits against the wall
    z0 = skin
    add("B", ox, oy, z0, deck_len, deck_depth, t)                       # bottom deck
    core_z = z0 + t
    # The core members are strips of the same sheet laid flat, so the cavity they
    # fill is one board thick — the same way the coffee table's core reads.
    core_h = t
    add("C", ox, oy, core_z, deck_len, RING, core_h)                    # front rail
    add("D", ox, oy + deck_depth - RING, core_z, deck_len, RING, core_h)  # back rail
    inner_d = deck_depth - 2 * RING
    add("E", ox, oy + RING, core_z, RING, inner_d, core_h)              # end cap, left
    add("E", ox + deck_len - RING, oy + RING, core_z, RING, inner_d, core_h)
    for edge in ribs:
        add("F", ox + edge, oy + RING, core_z, RING, inner_d, core_h)
    add("A", ox, oy, core_z + core_h, deck_len, deck_depth, t)          # top deck
    return boxes
