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
    """Four-layer exploded isometric, numbered bottom-to-top (reference FIG 1)."""
    c = Canvas(W, 380, title="Exploded assembly — four-layer build, bottom to top",
               stage="as_finished")
    import math
    a = math.radians(30)
    dx, dy = math.cos(a), math.sin(a)
    sc = 3.0                                   # px per inch
    L = geo.elements[0].finished_length.as_finished * sc
    Wd = geo.elements[0].finished_width.as_finished * sc
    ox, oy = 250.0, 250.0                       # origin of the bottom layer (front-bottom-left)

    def slab(base_y, thick, top_fill, side_fill, front_fill, footprint=1.0):
        """Draw one flat iso slab; returns the y of its top face centre for leaders."""
        ll = L * footprint
        ww = Wd * footprint
        offx = (L - ll) / 2
        x0 = ox + offx
        t = thick * sc
        # front face
        c.polygon([(x0, base_y), (x0 + ll, base_y), (x0 + ll, base_y - t), (x0, base_y - t)],
                  fill=front_fill, sw=1.0)
        # right side face
        c.polygon([(x0 + ll, base_y), (x0 + ll + ww * dx, base_y - ww * dy),
                   (x0 + ll + ww * dx, base_y - ww * dy - t), (x0 + ll, base_y - t)],
                  fill=side_fill, sw=1.0)
        # top face
        c.polygon([(x0, base_y - t), (x0 + ll, base_y - t),
                   (x0 + ll + ww * dx, base_y - ww * dy - t), (x0 + offx + ww * dx, base_y - ww * dy - t)],
                  fill=top_fill, sw=1.0)
        return x0, base_y - t

    # layer geometry (exploded with vertical gaps), bottom -> top
    layers = [
        ("1", "Plinth carcass", "3/4 ply box, 13 tall, inset 3 per side",
         14.0, "#e8d7ac", "#d9c48f", "#f0e4c6", 0.66),
        ("2", "Slab carcass", "3/4 ply torsion box, 2-1/4 thick",
         2.25, "#c9cdd2", "#b3b8bf", "#dde0e4", 1.0),
        ("3", "Cement board skin", "1/4 in, thinset + screws",
         0.9, "#b8bcc0", "#a4a8ad", "#cfd2d6", 1.0),
        ("4", "Microcement", "3 coats, sealer, wax",
         0.7, "#8a8f95", "#767b81", "#a3a8ad", 1.0),
    ]
    gap = 34
    base = oy
    tops = []
    for (num, name, sub, thick, tf, sf, ff, fp) in layers:
        x0, top_y = slab(base, thick, tf, sf, ff, fp)
        tops.append((num, name, sub, base, top_y))
        base = top_y - gap
    # dashed alignment guides between layers
    for i in range(len(tops) - 1):
        c.line(ox + 4, tops[i][4] - 4, ox + 4, tops[i + 1][3] + 4, 0.5, dash="3 3", color="#b7b1a6")
    # numbered legend down the left with a rule per layer
    ly = 120
    for (num, name, sub, base_y, top_y) in tops:
        c.text(30, ly + 4, num, size=17, anchor="start", weight="bold", color="#c0b7a5")
        c.text(52, ly, name.upper(), size=10, anchor="start", weight="bold")
        c.text(52, ly + 12, sub, size=8, anchor="start", color="#8b857a")
        c.line(52, ly + 18, 200, ly + 18, 0.4, color="#e0dacd")
        ly += 58
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
    """Sheet layout, labelled by ID only; font scaled to the smaller rectangle.

    Long, skinny stock (lumber/boards) is drawn in landscape — its length runs
    across the page — so it stays a readable strip instead of a 1px sliver."""
    sheet = nest.sheets[sheet_index - 1]
    landscape = sheet.sheet_h > sheet.sheet_w * 2.2
    sw = sheet.sheet_h if landscape else sheet.sheet_w
    sh = sheet.sheet_w if landscape else sheet.sheet_h
    title = (f"{nest.material_id} — sheet {sheet_index} "
             f"({sheet.utilisation()*100:.1f}% used)"
             + (" · not to scale, board shown lengthwise" if landscape else ""))
    c = Canvas(W, min(760.0, W * sh / sw + 40), title=title, stage="as_cut")
    s = (W - 20) / sw
    oy = 30.0
    c.rect(10, oy, sw * s, sh * s, sw=1.3)
    for p in sheet.placements:
        # in landscape, swap axes so the board's length is horizontal
        px, py, pw, ph = (p.y, p.x, p.h, p.w) if landscape else (p.x, p.y, p.w, p.h)
        c.rect(10 + px * s, oy + py * s, pw * s, ph * s, fill="#f0ece3", sw=0.6)
        rect_min = min(pw * s, ph * s)
        fs = max(6.0, min(12.0, rect_min * 0.6))
        pid = p.part_id.rstrip("0123456789")  # label by ID only (Lesson 9)
        c.text(10 + (px + pw / 2) * s, oy + (py + ph / 2) * s + fs / 3, pid, size=fs)
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
