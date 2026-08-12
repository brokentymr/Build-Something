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


def _ortho(geo: Geometry, ax: str, ay: str, title: str, hgt=300.0) -> Canvas:
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
    c = Canvas(W, hgt, title=title, stage="as_finished")
    s = min((W - 2 * MARGIN) / real_w, (hgt - 2 * MARGIN - 24) / real_h)
    ox = MARGIN + (W - 2 * MARGIN - real_w * s) / 2
    oy = hgt - MARGIN - 8
    invert = ay == "z"
    for i, b in enumerate(boxes):
        bx = (b[aw] - span[ax][0]) * s
        by = (b[ahp] - span[ay][0]) * s
        rw = b[wkey] * s
        rh = b[hkey] * s
        px = ox + bx
        py = (oy - by - rh) if invert else (MARGIN + 16 + by)
        c.rect(px, py, rw, rh, fill=_SHADES[i % len(_SHADES)], sw=0.9)
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
    """Isometric exploded view: each panel slides out along its own normal."""
    boxes = geo.structure["boxes"]
    minx, miny, minz, maxx, maxy, maxz = _bbox(boxes)
    cx, cy, cz = (minx + maxx) / 2, (miny + maxy) / 2, (minz + maxz) / 2
    factor = 1.0
    placed = []
    for b in boxes:
        bcx, bcy, bcz = b["x"] + b["w"] / 2, b["y"] + b["d"] / 2, b["z"] + b["h"] / 2
        normal = min((b["w"], "x"), (b["d"], "y"), (b["h"], "z"))[1]
        off = {"x": 0.0, "y": 0.0, "z": 0.0}
        if normal == "x":
            off["x"] = (bcx - cx) * factor
        elif normal == "y":
            off["y"] = (bcy - cy) * factor
        else:
            off["z"] = (bcz - cz) * factor
        placed.append({**b, "ox": off["x"], "oy": off["y"], "oz": off["z"]})

    # exploded bounding extents to compute scale
    def isopt(x, y, z, s, oxp, oyp):
        return (oxp + (x - y) * _C30 * s, oyp + ((x + y) * _S30 - z) * s)

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
    hgt = 380.0
    s = min((W - 2 * MARGIN) / (maxsx - minsx), (hgt - 2 * MARGIN) / (maxsy - minsy))
    oxp = MARGIN - minsx * s
    oyp = MARGIN - minsy * s
    c = Canvas(W, hgt, title="Exploded assembly", stage="as_finished")

    # draw back-to-front (sort by depth key x+y+z ascending so nearer drawn last)
    order = sorted(placed, key=lambda b: (b["x"] + b["ox"] + b["y"] + b["oy"] + b["z"] + b["oz"]))
    for i, b in enumerate(order):
        x, y, z = b["x"] + b["ox"], b["y"] + b["oy"], b["z"] + b["oz"]
        w, d, h = b["w"], b["d"], b["h"]
        P = lambda X, Y, Z: isopt(X, Y, Z, s, oxp, oyp)
        top = [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)]
        left = [P(x, y, z), P(x, y + d, z), P(x, y + d, z + h), P(x, y, z + h)]
        front = [P(x, y, z), P(x + w, y, z), P(x + w, y, z + h), P(x, y, z + h)]
        sh = _SHADES[i % len(_SHADES)]
        c.polygon(front, fill=sh, sw=0.8)
        c.polygon(left, fill=_darken(sh, 0.9), sw=0.8)
        c.polygon(top, fill=_lighten(sh), sw=0.8)
        mid = P(x + w / 2, y + d / 2, z + h)
        c.text(mid[0], mid[1] - 2, b["id"], size=9, weight="bold")
    return c


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
