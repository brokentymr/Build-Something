"""Drawing types — Phase 4, brief section 5.1.

Each function turns solved geometry into a parametric SVG. Every dimension label
is the solver value passed through :func:`fmt_inches` — never a coordinate. Every
drawing declares its stage. Nesting diagrams label by ID only and scale font to
the smaller rectangle (Lesson 9).
"""

from __future__ import annotations

from .primitives import Canvas, fmt_inches
from ..core.model import Geometry
from ..nesting.guillotine import NestResult

W = 520.0                    # print-column width in px
MARGIN = 60.0


def _scale(inner_w, inner_h, real_w, real_h):
    return min(inner_w / real_w, inner_h / real_h)


def plan_view(geo: Geometry) -> Canvas:
    L = geo.elements[0].finished_length.as_finished
    Wd = geo.elements[0].finished_width.as_finished
    reveal = geo.scalar("plinth.inset.as_finished")
    c = Canvas(W, 300, title="Plan — top view", stage="as_finished")
    s = _scale(W - 2 * MARGIN, 300 - 2 * MARGIN - 30, L, Wd)
    ox, oy = MARGIN, 60.0
    c.rect(ox, oy, L * s, Wd * s, fill="#fbfaf7", sw=1.3)
    # plinth footprint (dashed, reveal inset)
    c.rect(ox + reveal * s, oy + reveal * s, (L - 2 * reveal) * s, (Wd - 2 * reveal) * s,
           dash="4 3", stroke="#a00")
    c.dim_horizontal(ox, ox + L * s, oy + Wd * s + 28, fmt_inches(L))
    c.dim_vertical(oy, oy + Wd * s, ox - 14, fmt_inches(Wd))
    c.leader(ox + reveal * s, oy + reveal * s, ox + reveal * s + 30, oy + 12,
             f"reveal {fmt_inches(reveal)}")
    return c


def side_elevation(geo: Geometry) -> Canvas:
    # rebuild with finished width span
    L = geo.elements[0].finished_width.as_finished
    H = geo.scalar("overall_height")
    edge = geo.elements[0].finished_height.as_finished
    plinth_vis = geo.scalar("plinth.height.as_finished")
    reveal = geo.scalar("plinth.inset.as_finished")
    c = Canvas(W, 340, title="Side elevation", stage="as_finished")
    s = _scale(W - 2 * MARGIN, 340 - 2 * MARGIN - 20, L, H)
    ox = MARGIN
    oy = 340 - MARGIN - 20
    c.rect(ox + reveal * s, oy - plinth_vis * s, (L - 2 * reveal) * s, plinth_vis * s, fill="#e9e4da")
    c.rect(ox, oy - H * s, L * s, edge * s, fill="#d8d0c4", sw=1.3)
    c.ground_hatch(ox - 6, oy + 1, L * s + 12)
    c.dim_vertical(oy - H * s, oy, ox - 16, fmt_inches(H))
    c.dim_vertical(oy - plinth_vis * s, oy, ox + L * s + 16, fmt_inches(plinth_vis), left=False)
    c.dim_horizontal(ox, ox + L * s, oy + 26, fmt_inches(L))
    return c


def front_elevation_real(geo: Geometry) -> Canvas:
    L = geo.elements[0].finished_length.as_finished
    H = geo.scalar("overall_height")
    edge = geo.elements[0].finished_height.as_finished
    plinth_vis = geo.scalar("plinth.height.as_finished")
    reveal = geo.scalar("plinth.inset.as_finished")
    c = Canvas(W, 340, title="Front elevation", stage="as_finished")
    s = _scale(W - 2 * MARGIN, 340 - 2 * MARGIN - 20, L, H)
    ox = MARGIN
    oy = 340 - MARGIN - 20
    c.rect(ox + reveal * s, oy - plinth_vis * s, (L - 2 * reveal) * s, plinth_vis * s, fill="#e9e4da")
    c.rect(ox, oy - H * s, L * s, edge * s, fill="#d8d0c4", sw=1.3)
    c.ground_hatch(ox - 6, oy + 1, L * s + 12)
    c.dim_vertical(oy - H * s, oy, ox - 16, fmt_inches(H))
    c.dim_vertical(oy - H * s, oy - H * s + edge * s, ox + L * s + 16, fmt_inches(edge), left=False)
    c.dim_vertical(oy - plinth_vis * s, oy, ox + L * s + 16, fmt_inches(plinth_vis), left=False)
    c.dim_horizontal(ox, ox + L * s, oy + 26, fmt_inches(L))
    return c


def allowance_section(geo: Geometry) -> Canvas:
    """Enlarged section through the allowance stack (substrate + skin layers)."""
    from ..catalog.finishes import get_finish
    fin = get_finish(geo.finish_id)
    c = Canvas(W, 300, title="Enlarged section — allowance stack", stage="as_finished")
    # magnified layers, bottom-up: carcass, cement board, microcement
    ox, oy = 70.0, 60.0
    layer_w = 100.0
    scale_px = 240.0  # px per inch (magnified)
    y = oy
    carcass_h = 0.45 * scale_px  # illustrative carcass slice
    c.rect(ox, y, layer_w, carcass_h, fill="#efe9dd")
    c.section_hatch(ox, y, layer_w, carcass_h)
    c.leader(ox + layer_w, y + carcass_h / 2, ox + layer_w + 24, y + carcass_h / 2,
             "plywood carcass (substrate)")
    y += carcass_h
    for layer in fin.layers:
        h = layer.thickness * scale_px
        c.rect(ox, y, layer_w, h, fill="#cfc6b6")
        c.leader(ox + layer_w, y + h / 2, ox + layer_w + 24, y + h / 2,
                 f"{layer.name} {fmt_inches(layer.thickness)}")
        y += h
    c.dim_vertical(oy + carcass_h, y, ox - 12, fmt_inches(fin.per_face_offset))
    return c


def core_layout(geo: Geometry) -> Canvas:
    """Framing/core layout with cumulative positional dimensions (Lesson 4)."""
    deck_l = geo.scalar("slab.deck.length")
    deck_w = geo.scalar("slab.deck.width")
    ring = geo.scalar("slab.core_ring_width")
    edges = geo.structure.get("rib_left_edges", [])
    c = Canvas(W, 300, title="Core / framing layout — cumulative dims", stage="as_cut")
    s = _scale(W - 2 * MARGIN, 300 - 2 * MARGIN - 40, deck_l, deck_w)
    ox, oy = MARGIN, 60.0
    c.rect(ox, oy, deck_l * s, deck_w * s, fill="#fbfaf7")
    # ring
    c.rect(ox, oy, deck_l * s, ring * s, fill="#e5ded1")
    c.rect(ox, oy + (deck_w - ring) * s, deck_l * s, ring * s, fill="#e5ded1")
    c.rect(ox, oy, ring * s, deck_w * s, fill="#e5ded1")
    c.rect(ox + (deck_l - ring) * s, oy, ring * s, deck_w * s, fill="#e5ded1")
    # ribs with cumulative dimension from left edge
    for i, e in enumerate(edges, 1):
        c.rect(ox + e * s, oy, ring * s, deck_w * s, fill="#e5ded1")
        c.dim_horizontal(ox, ox + e * s, oy - 8 - (i % 2) * 14, fmt_inches(e))
    c.dim_horizontal(ox, ox + deck_l * s, oy + deck_w * s + 22, fmt_inches(deck_l))
    return c


def exploded_assembly(geo: Geometry) -> Canvas:
    L = geo.elements[0].finished_length.as_finished
    Wd = geo.elements[0].finished_width.as_finished
    edge = geo.elements[0].finished_height.as_finished
    plinth_vis = geo.scalar("plinth.height.as_finished")
    c = Canvas(W, 360, title="Exploded assembly", stage="as_finished")
    s = 6.0
    # slab up top
    c.iso_box(120, 120, L, Wd, edge, scale=s, label=None)
    c.leader(150, 110, 90, 90, "slab")
    # plinth below
    c.iso_box(150, 300, L * 0.72, Wd * 0.72, plinth_vis, scale=s, label=None)
    c.leader(180, 290, 110, 300, "plinth")
    c.line(220, 150, 235, 210, 0.6, dash="3 3", color="#888")
    return c


def per_stage_plinth(geo: Geometry) -> tuple[Canvas, Canvas]:
    """Dedicated drawings for a stage-dependent dimension (plinth height)."""
    cut = geo.scalar("plinth.carcass_height.as_cut")
    fin = geo.scalar("plinth.height.as_finished")

    def one(val, stage, note):
        c = Canvas(W, 240, title=f"Plinth height — {stage}", stage=stage)
        s = _scale(120, 240 - 2 * MARGIN, 20, val)
        ox, oy = 200.0, 40.0
        c.rect(ox, oy, 120, val * s, fill="#e9e4da")
        c.dim_vertical(oy, oy + val * s, ox - 16, fmt_inches(val))
        c.text(ox + 60, oy + val * s + 24, note, size=10)
        return c

    return (one(cut, "as_cut", "what you cut the panel to"),
            one(fin, "as_finished", "what you measure on the finished piece (slab edge occludes 3/8)"))


def nesting_diagram(nest: NestResult, sheet_index: int) -> Canvas:
    """Sheet layout, labelled by ID only; font scaled to the smaller rectangle."""
    sheet = nest.sheets[sheet_index - 1]
    c = Canvas(W, W * sheet.sheet_h / sheet.sheet_w + 40,
               title=f"{nest.material_id} — sheet {sheet_index} "
                     f"({sheet.utilisation()*100:.1f}% used)", stage="as_cut")
    s = (W - 20) / sheet.sheet_w
    oy = 30.0
    c.rect(10, oy, sheet.sheet_w * s, sheet.sheet_h * s, sw=1.3)
    for p in sheet.placements:
        c.rect(10 + p.x * s, oy + p.y * s, p.w * s, p.h * s, fill="#f0ece3", sw=0.6)
        rect_min = min(p.w * s, p.h * s)
        fs = max(6.0, min(12.0, rect_min * 0.5))
        pid = p.part_id.rstrip("0123456789")  # label by ID only (Lesson 9)
        c.text(10 + (p.x + p.w / 2) * s, oy + (p.y + p.h / 2) * s + fs / 3, pid, size=fs)
    return c


def fastener_spacing(geo: Geometry) -> Canvas:
    c = Canvas(W, 180, title="Fastener spacing pattern", stage="as_assembled")
    ox, oy = 40.0, 90.0
    length = W - 80
    spacing = 40.0
    c.line(ox, oy, ox + length, oy, 1.0)
    n = int(length // spacing)
    for i in range(n + 1):
        x = ox + i * spacing
        c.line(x, oy - 8, x, oy + 8, 0.8)
        c.polygon([(x - 3, oy - 8), (x + 3, oy - 8), (x, oy - 2)], fill="#333")
    c.dim_horizontal(ox, ox + spacing, oy + 30, '4"')
    c.text(W / 2, oy - 24, "cabinet screws @ 4\" o.c., pilot 7/64", size=11)
    return c


def all_drawings(geo: Geometry, plan) -> dict[str, Canvas]:
    """The full required drawing set for the document."""
    d: dict[str, Canvas] = {
        "exploded_assembly": exploded_assembly(geo),
        "plan": plan_view(geo),
        "front_elevation": front_elevation_real(geo),
        "side_elevation": side_elevation(geo),
        "allowance_section": allowance_section(geo),
        "core_layout": core_layout(geo),
        "fastener_spacing": fastener_spacing(geo),
    }
    cut_c, fin_c = per_stage_plinth(geo)
    d["plinth_as_cut"] = cut_c
    d["plinth_as_finished"] = fin_c
    for mid, nest in plan.nests.items():
        for i in range(1, nest.sheet_count() + 1):
            d[f"nest_{mid}_{i}"] = nesting_diagram(nest, i)
    return d
