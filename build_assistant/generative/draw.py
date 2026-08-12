"""Generic hero drawings from 3D part placement — works for any object.

The agent places each part as a box in assembly space; these functions project
those boxes into real orthographic views (plan, front, side) with overall
dimensions, and an exploded isometric that slides each panel out along its own
normal. No object-specific assumptions — a bookshelf, a planter and a table all
draw from the same box list.
"""

from __future__ import annotations

import math

from ..core.model import Geometry
from ..drawing.primitives import Canvas, fmt_inches

W = 520.0
MARGIN = 58.0
_C30, _S30 = math.cos(math.radians(30)), math.sin(math.radians(30))
_SHADES = ["#e7e2d7", "#d9d3c4", "#efeadf", "#e0dacd", "#f0ece2", "#d2ccbd"]


def _bbox(boxes):
    xs = [b["x"] for b in boxes] + [b["x"] + b["w"] for b in boxes]
    ys = [b["y"] for b in boxes] + [b["y"] + b["d"] for b in boxes]
    zs = [b["z"] for b in boxes] + [b["z"] + b["h"] for b in boxes]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def _has_boxes(geo: Geometry) -> bool:
    return bool(geo.structure.get("boxes"))


ORTHO_MIN_H, ORTHO_MAX_H = 260.0, 540.0


def _ortho(geo: Geometry, ax: str, ay: str, title: str, hgt=None) -> Canvas:
    """Orthographic projection. ax/ay pick which world axes map to screen x/y.

    ay is drawn with world-up inverted so z points up on the page."""
    boxes = geo.structure["boxes"]
    minx, miny, minz, maxx, maxy, maxz = _bbox(boxes)
    span = {"x": (minx, maxx), "y": (miny, maxy), "z": (minz, maxz)}
    ext = {"x": ("x", "w"), "y": ("y", "d"), "z": ("z", "h")}
    (aw, wkey) = ext[ax]
    (ahp, hkey) = ext[ay]
    real_w = span[ax][1] - span[ax][0]
    real_h = span[ay][1] - span[ay][0]
    # Scale to the full width, then let the height follow — a 32 x 54in case in a
    # fixed 300pt frame drew at a third of the size and left half the page blank.
    if hgt is None:
        s_w = (W - 2 * MARGIN) / real_w
        hgt = max(ORTHO_MIN_H, min(ORTHO_MAX_H, real_h * s_w + 2 * MARGIN + 24))
    c = Canvas(W, hgt, title=title, stage="as_finished")
    s = min((W - 2 * MARGIN) / real_w, (hgt - 2 * MARGIN - 24) / real_h)
    ox = MARGIN + (W - 2 * MARGIN - real_w * s) / 2
    oy = hgt - MARGIN - 8
    # z grows up the page; depth (y) also grows up so a plan reads with the front
    # of the piece at the bottom, the way a plan is conventionally drawn.
    invert = ay in ("z", "y")

    # Draw far parts first. Without this the back panel lands on top of the
    # shelves and a front elevation reads as one blank filled rectangle.
    view = next(a for a in ("x", "y", "z") if a not in (ax, ay))
    depth_key = {"y": lambda b: -b["y"],      # front elevation: viewer in front
                 "z": lambda b: b["z"],       # plan: viewer above
                 "x": lambda b: b["x"]}[view]  # side elevation: viewer at the right
    shade = {pid: _SHADES[i % len(_SHADES)]
             for i, pid in enumerate(dict.fromkeys(x["id"] for x in boxes))}

    # A plan is a cut, not a lid. Drawn as a literal top view the top panel covers
    # the whole carcass and the drawing says nothing. Horizontal panels that span
    # the piece — the top, the shelves — become dashed outlines, the way a plan
    # implies its surfaces, leaving the walls, back and plinth reading solid.
    outline_only = set()
    if view == "z":
        footprint = real_w * real_h
        for b in boxes:
            flat = b["h"] <= 0.5 * min(b["w"], b["d"])
            if flat and b["w"] * b["d"] >= 0.4 * footprint:
                outline_only.add(id(b))

    for i, b in enumerate(sorted(boxes, key=depth_key)):
        bx = (b[aw] - span[ax][0]) * s
        by = (b[ahp] - span[ay][0]) * s
        rw = b[wkey] * s
        rh = b[hkey] * s
        px = ox + bx
        py = (oy - by - rh) if invert else (MARGIN + 16 + by)
        if id(b) in outline_only:
            c.rect(px, py, rw, rh, fill="none", sw=0.9, dash="5,3")
        else:
            c.rect(px, py, rw, rh, fill=shade.get(b["id"], _SHADES[0]), sw=0.9)
    # overall dimensions — horizontal below, vertical in the left gutter (rotated)
    c.dim_horizontal(ox, ox + real_w * s, oy + 22, fmt_inches(real_w))
    y0 = (oy - real_h * s) if invert else (MARGIN + 16)
    gx = 30.0
    c.line(gx, y0, gx, y0 + real_h * s, 0.8)
    c._tick(gx, y0, vertical=True); c._tick(gx, y0 + real_h * s, vertical=True)
    c.text(gx - 6, (y0 + y0 + real_h * s) / 2, fmt_inches(real_h), size=11,
           anchor="middle", rot=-90)
    return c


def plan(geo: Geometry) -> Canvas:
    return _ortho(geo, "x", "y", "Plan — top view")


def front_elevation(geo: Geometry) -> Canvas:
    return _ortho(geo, "x", "z", "Front elevation")


def side_elevation(geo: Geometry) -> Canvas:
    return _ortho(geo, "y", "z", "Side elevation")


def exploded(geo: Geometry) -> Canvas:
    """Isometric exploded assembly, drawn the way a build schematic reads.

    Three things make it legible rather than a pile of panels:

    * **Depth is correct.** World ``y`` grows toward the BACK, so it is negated in
      the projection — a back panel projects up-and-right and is painted first,
      behind everything, instead of landing on top of the shelves.
    * **Explosion preserves assembly order.** Each part slides along its own
      thin axis, away from the middle of the assembly, ranked by how far out it
      already sits. Every part moves at least one full gap, so nothing stays
      buried in the middle, and relative order is never scrambled.
    * **Parts are keyed by balloon to a legend**, so labels cannot crowd.
    """
    boxes = geo.structure["boxes"]
    minx, miny, minz, maxx, maxy, maxz = _bbox(boxes)
    mid = {"x": (minx + maxx) / 2, "y": (miny + maxy) / 2, "z": (minz + maxz) / 2}
    span = max(maxx - minx, maxy - miny, maxz - minz)
    gap = max(1.5, span * 0.085)

    # group parts by the axis they slide along (their thinnest dimension)
    groups: dict[str, list] = {"x": [], "y": [], "z": []}
    for b in boxes:
        normal = min((b["w"], "x"), (b["d"], "y"), (b["h"], "z"))[1]
        groups[normal].append(b)

    placed = []
    for axis, members in groups.items():
        lo_key, ext_key = {"x": ("x", "w"), "y": ("y", "d"), "z": ("z", "h")}[axis]
        m = mid[axis]
        for direction in (-1, 1):
            side = [b for b in members
                    if (1 if (b[lo_key] + b[ext_key] / 2) >= m else -1) == direction]
            # nearest the middle moves least; every part moves at least one gap
            side.sort(key=lambda b: abs((b[lo_key] + b[ext_key] / 2) - m))
            for rank, b in enumerate(side):
                off = {"x": 0.0, "y": 0.0, "z": 0.0}
                off[axis] = direction * gap * (1 + rank)
                placed.append({**b, "ox": off["x"], "oy": off["y"], "oz": off["z"]})

    def isopt(x, y, z, s, oxp, oyp):
        # y is negated: increasing depth recedes up-and-right, as it should
        return (oxp + (x + y) * _C30 * s, oyp + ((x - y) * _S30 - z) * s)

    pts = []
    for b in placed:
        for dx in (0, b["w"]):
            for dy in (0, b["d"]):
                for dz in (0, b["h"]):
                    pts.append(((b["x"] + b["ox"] + dx), (b["y"] + b["oy"] + dy),
                                (b["z"] + b["oz"] + dz)))
    raw = [isopt(x, y, z, 1.0, 0, 0) for x, y, z in pts]
    minsx = min(p[0] for p in raw); maxsx = max(p[0] for p in raw)
    minsy = min(p[1] for p in raw); maxsy = max(p[1] for p in raw)

    names = {p.id: p.name for p in geo.parts}
    qty = {p.id: p.qty for p in geo.parts}
    ids = [p.id for p in geo.parts]
    # Balloons carry an ITEM NUMBER, not the part id — ids can be long words and
    # would burst the balloon. The same number keys the legend and the cut list.
    item_no = item_numbers(geo)
    legend_text = {pid: names.get(pid, "") + (f"  ×{qty[pid]}" if qty.get(pid, 1) > 1 else "")
                   for pid in ids}
    longest = max((len(t) for t in legend_text.values()), default=1)
    cols = 3 if (len(ids) > 8 and longest <= 26) else (2 if longest <= 42 else 1)
    rows_n = -(-len(ids) // cols)
    legend_h = 26.0 + rows_n * 13.0
    draw_h = 350.0
    hgt = draw_h + legend_h

    pad = 30.0
    s = min((W - 2 * pad) / (maxsx - minsx), (draw_h - 2 * pad) / (maxsy - minsy))
    oxp = pad - minsx * s + (W - 2 * pad - (maxsx - minsx) * s) / 2
    oyp = pad - minsy * s
    c = Canvas(W, hgt, title="Exploded assembly", stage="as_finished")

    # Painter's order: far and low first. With depth toward -y and +x, closeness
    # rises with (x - y + z), so ascending draws the back of the piece first.
    def depth(b):
        return ((b["x"] + b["ox"] + b["w"] / 2) - (b["y"] + b["oy"] + b["d"] / 2)
                + (b["z"] + b["oz"] + b["h"] / 2))

    anchors: dict[str, tuple] = {}
    for i, b in enumerate(sorted(placed, key=depth)):
        x, y, z = b["x"] + b["ox"], b["y"] + b["oy"], b["z"] + b["oz"]
        w, d, h = b["w"], b["d"], b["h"]
        P = lambda X, Y, Z: isopt(X, Y, Z, s, oxp, oyp)
        # visible faces from this camera: top (+z), front (y min), right (x max)
        top = [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)]
        front = [P(x, y, z), P(x + w, y, z), P(x + w, y, z + h), P(x, y, z + h)]
        right = [P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)]
        sh = _SHADES[i % len(_SHADES)]
        c.polygon(top, fill=_lighten(sh), sw=0.8)
        c.polygon(front, fill=sh, sw=0.8)
        c.polygon(right, fill=_darken(sh, 0.88), sw=0.8)
        anchors[b["id"]] = P(x + w / 2, y + d / 2, z + h / 2)

    # Balloons key each part to the legend. Small parts cluster, so relax the
    # balloon positions apart and tie any that had to move back to their part with
    # a short leader — a balloon never sits on top of another balloon.
    pos = {pid: [p[0], p[1]] for pid, p in anchors.items()}
    r = 8.5
    for _ in range(60):
        moved = False
        keys = list(pos)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                dx = pos[b][0] - pos[a][0]
                dy = pos[b][1] - pos[a][1]
                dist = (dx * dx + dy * dy) ** 0.5 or 0.01
                need = 2 * r + 3
                if dist < need:
                    push = (need - dist) / 2
                    ux, uy = dx / dist, dy / dist
                    pos[a][0] -= ux * push; pos[a][1] -= uy * push
                    pos[b][0] += ux * push; pos[b][1] += uy * push
                    moved = True
        if not moved:
            break
    for pid, (ax, ay) in anchors.items():
        bx, by = pos[pid]
        bx = min(max(bx, r + 2), W - r - 2)
        by = min(max(by, r + 16), draw_h - r - 2)
        if abs(bx - ax) + abs(by - ay) > 3:
            c.line(ax, ay, bx, by, 0.5, color="#7a746a")
        c.balloon(bx, by, str(item_no.get(pid, "?")))

    # legend grid beneath the view
    ly0 = draw_h + 12.0
    c.line(pad, ly0 - 8, W - pad, ly0 - 8, 0.8, color="#17150f")
    colw = (W - 2 * pad) / cols
    for i, pid in enumerate(ids):
        col, row = i % cols, i // cols
        lx = pad + col * colw
        ty = ly0 + 10 + row * 13.0
        c.balloon(lx + 6, ty - 3.2, str(item_no.get(pid, "?")), r=6.0)
        label = legend_text[pid]
        maxchars = int((colw - 22) / (7.6 * 0.55))
        if len(label) > maxchars:
            label = label[: max(1, maxchars - 1)] + "…"
        c.text(lx + 16, ty, label, size=7.6, anchor="start", color="#3a352c")
    return c


def item_numbers(geo: Geometry) -> dict[str, int]:
    """Stable 1-based item number per part — the key shared by the exploded
    balloons, the legend and the cut list."""
    return {p.id: i + 1 for i, p in enumerate(geo.parts)}


def _darken(hex_c, f):
    r = int(hex_c[1:3], 16); g = int(hex_c[3:5], 16); b = int(hex_c[5:7], 16)
    return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"


def _lighten(hex_c):
    r = int(hex_c[1:3], 16); g = int(hex_c[3:5], 16); b = int(hex_c[5:7], 16)
    return f"#{min(255,int(r*1.06)):02x}{min(255,int(g*1.06)):02x}{min(255,int(b*1.06)):02x}"


def hero_drawings(geo: Geometry) -> dict:
    """The view set for the packet, when the design carries 3D placement."""
    if not _has_boxes(geo):
        return {}
    return {"exploded": exploded(geo), "plan": plan(geo),
            "front_elevation": front_elevation(geo), "side_elevation": side_elevation(geo)}
