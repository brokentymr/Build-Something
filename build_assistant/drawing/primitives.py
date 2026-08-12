"""Drafting primitive library — Phase 4, brief section 5.1.

Parametric SVG. Never illustrative, never model-generated.

Three hard rules, enforced structurally here:

* **Every dimension label is passed explicitly** (Lesson 7). There is no default
  that derives a label from canvas coordinates — ``label`` is a required
  positional argument, and passing ``None`` raises. A garbage default once printed
  ``352-13/16"`` where ``42"`` was meant, by formatting pixels as inches.
* **Text extents are bounds-checked against the viewBox** (Lesson 9 / Gate 3).
  :class:`Canvas` records every text run's estimated bounding box; overflow is
  detectable even though it overflows no container.
* Decimal-to-fraction formatting is a shared helper (never re-implemented).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

TICK = 6.0                 # architectural tick length (px)
EXT = 4.0                  # extension-line gap
FONT = 11.0                # default label font size
CHAR_W = 0.6               # rough glyph width factor for extent estimation


class LabelError(ValueError):
    """A dimension/label helper was called without an explicit label."""


def fmt_inches(value: float, denom: int = 64) -> str:
    """Decimal inches -> architectural fraction string, e.g. 41.25 -> 41-1/4\"."""
    neg = value < 0
    value = abs(value)
    whole = int(value)
    frac = Fraction(value - whole).limit_denominator(denom)
    sign = "-" if neg else ""
    if frac == 0:
        return f'{sign}{whole}"'
    if whole == 0:
        return f'{sign}{frac.numerator}/{frac.denominator}"'
    return f'{sign}{whole}-{frac.numerator}/{frac.denominator}"'


@dataclass
class TextBox:
    x: float
    y: float
    w: float
    h: float
    text: str


@dataclass
class Canvas:
    """An SVG canvas that tracks text extents for bounds-checking (Gate 3)."""

    w: float
    h: float
    pad: float = 24.0
    _els: list[str] = field(default_factory=list)
    _texts: list[TextBox] = field(default_factory=list)
    title: str = ""
    stage: str = ""            # every drawing declares its stage (section 5.1)
    _ext: list[float] = field(default_factory=lambda: [1e9, 1e9, -1e9, -1e9])  # minx,miny,maxx,maxy

    def _grow(self, x, y):
        self._ext[0] = min(self._ext[0], x)
        self._ext[1] = min(self._ext[1], y)
        self._ext[2] = max(self._ext[2], x)
        self._ext[3] = max(self._ext[3], y)

    # ---- raw geometry ----
    def line(self, x1, y1, x2, y2, w=1.0, dash="", color="#222"):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self._grow(x1, y1); self._grow(x2, y2)
        self._els.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{color}" stroke-width="{w}"{d}/>'
        )

    def rect(self, x, y, w, h, fill="none", stroke="#222", sw=1.0, dash=""):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self._grow(x, y); self._grow(x + w, y + h)
        self._els.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'
        )

    def polygon(self, pts, fill="none", stroke="#222", sw=1.0):
        for x, y in pts:
            self._grow(x, y)
        p = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        self._els.append(f'<polygon points="{p}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, s, size=FONT, anchor="middle", color="#111", weight="normal", rot=0):
        if s is None:
            raise LabelError("text() requires an explicit string (Lesson 7)")
        w = len(s) * size * CHAR_W
        if anchor == "middle":
            bx = x - w / 2
        elif anchor == "end":
            bx = x - w
        else:
            bx = x
        if rot:
            # rotated label occupies a narrow vertical strip; record its rotated bbox
            self._texts.append(TextBox(x - size, min(y, y - w), size * 1.2, w, s))
            transform = f' transform="rotate({rot} {x:.2f} {y:.2f})"'
        else:
            self._texts.append(TextBox(bx, y - size, w, size * 1.2, s))
            transform = ""
        self._els.append(
            f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" text-anchor="{anchor}" '
            f'font-family="Helvetica,Arial,sans-serif" fill="{color}" '
            f'font-weight="{weight}"{transform}>{_esc(s)}</text>'
        )

    # ---- drafting primitives ----
    def dim_horizontal(self, x1: float, x2: float, y: float, label: str, above=True):
        """Horizontal dimension line with architectural ticks + extension lines.

        ``label`` is REQUIRED and explicit — there is deliberately no default that
        measures ``x2 - x1`` (Lesson 7)."""
        if label is None:
            raise LabelError("dim_horizontal requires an explicit label (Lesson 7)")
        self.line(x1, y, x2, y, 0.8)
        self._tick(x1, y)
        self._tick(x2, y)
        ty = y - 5 if above else y + FONT + 2
        self.text((x1 + x2) / 2, ty, label, size=FONT)

    def dim_vertical(self, y1: float, y2: float, x: float, label: str, left=True):
        if label is None:
            raise LabelError("dim_vertical requires an explicit label (Lesson 7)")
        self.line(x, y1, x, y2, 0.8)
        self._tick(x, y1, vertical=True)
        self._tick(x, y2, vertical=True)
        tx = x - 5 if left else x + 5
        anchor = "end" if left else "start"
        self.text(tx, (y1 + y2) / 2, label, size=FONT, anchor=anchor)

    def leader(self, x: float, y: float, tx: float, ty: float, label: str):
        """A leader line with an anchored label. ``label`` is required."""
        if label is None:
            raise LabelError("leader requires an explicit label (Lesson 7)")
        self.line(x, y, tx, ty, 0.7)
        anchor = "start" if tx >= x else "end"
        self.text(tx + (3 if tx >= x else -3), ty, label, size=FONT - 1, anchor=anchor)

    def section_hatch(self, x, y, w, h, spacing=7.0):
        """45-degree section hatching, parallel lines clipped to a rectangle."""
        k = -h
        while k <= w:
            pts = []
            for lx, ly, ok in (
                (k, 0.0, 0 <= k <= w),            # bottom edge
                (k + h, h, 0 <= k + h <= w),      # top edge
                (0.0, -k, 0 <= -k <= h),          # left edge
                (w, w - k, 0 <= w - k <= h),      # right edge
            ):
                if ok:
                    pts.append((lx, ly))
            if len(pts) >= 2:
                (x1, y1), (x2, y2) = pts[0], pts[1]
                self.line(x + x1, y + y1, x + x2, y + y2, 0.4, color="#b0a99a")
            k += spacing

    # ---- material-aware section poché -------------------------------------
    def material_hatch(self, x, y, w, h, category: str, spacing=6.0):
        """Section poché keyed to the material, the way a shop drawing reads.

        sheet_good  -> ply laminations (lines along the panel's long axis)
        lumber/hardwood -> 45-degree section hatch
        cement_board -> stipple
        anything else -> light 45-degree hatch
        """
        if w <= 0 or h <= 0:
            return
        if category == "sheet_good":
            # plies run parallel to the face; draw across the SHORT dimension
            if h <= w:
                n = max(2, min(7, int(h / 1.6)))
                for i in range(1, n):
                    yy = y + h * i / n
                    self.line(x + 0.5, yy, x + w - 0.5, yy, 0.3, color="#b5ad9c")
            else:
                n = max(2, min(7, int(w / 1.6)))
                for i in range(1, n):
                    xx = x + w * i / n
                    self.line(xx, y + 0.5, xx, y + h - 0.5, 0.3, color="#b5ad9c")
        elif category == "cement_board":
            step = max(3.0, spacing * 0.7)
            j = 0
            yy = y + step / 2
            while yy < y + h:
                xx = x + (step / 2 if j % 2 else step)
                while xx < x + w:
                    self.line(xx, yy, xx + 0.9, yy, 0.7, color="#9d968a")
                    xx += step
                yy += step
                j += 1
        else:
            self.section_hatch(x, y, w, h, spacing=spacing)

    def elbow_leader(self, px, py, lx, ly, label: str, side="right", size=None):
        """Leader with a dot at the target, an elbow, and a label on a shelf line."""
        if label is None:
            raise LabelError("elbow_leader requires an explicit label (Lesson 7)")
        fs = size or (FONT - 1.5)
        mx = lx - 12 if side == "right" else lx + 12
        self.line(px, py, mx, ly, 0.55, color="#5f594e")
        self.line(mx, ly, lx, ly, 0.55, color="#5f594e")
        self._els.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="1.7" fill="#3a352c"/>')
        anchor = "start" if side == "right" else "end"
        off = 3 if side == "right" else -3
        self.text(lx + off, ly + fs * 0.35, label, size=fs, anchor=anchor, color="#3a352c")

    def notched_rect(self, x, y, w, h, nx0, nx1, depth, from_top=True,
                     fill="#f4f0e6", sw=1.1):
        """Rectangle with a rectangular housing cut (dado / groove / rabbet).

        ``nx0``/``nx1`` bound the notch across the face, ``depth`` is how deep it
        is machined. Cut from the top edge when ``from_top``, else the bottom."""
        nx0 = max(x, min(nx0, x + w))
        nx1 = max(x, min(nx1, x + w))
        if nx1 - nx0 <= 0.5 or depth <= 0.5:
            self.rect(x, y, w, h, fill=fill, sw=sw)
            return
        if from_top:
            pts = [(x, y), (nx0, y), (nx0, y + depth), (nx1, y + depth), (nx1, y),
                   (x + w, y), (x + w, y + h), (x, y + h)]
        else:
            yb = y + h
            pts = [(x, y), (x + w, y), (x + w, yb), (nx1, yb), (nx1, yb - depth),
                   (nx0, yb - depth), (nx0, yb), (x, yb)]
        self.polygon(pts, fill=fill, sw=sw)

    def balloon(self, x, y, tag: str, r=8.5):
        """Numbered/lettered callout balloon, the way an assembly schematic keys
        parts to its legend. Drawn opaque so it stays readable over geometry."""
        if tag is None:
            raise LabelError("balloon requires an explicit tag (Lesson 7)")
        self._els.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="#fffdf8" '
            f'stroke="#17150f" stroke-width="1.1"/>')
        self._grow(x - r, y - r); self._grow(x + r, y + r)
        size = r * 1.05 if len(tag) <= 2 else r * 0.82
        self.text(x, y + size * 0.36, tag, size=size, weight="bold", color="#17150f")

    def detail_bubble(self, x, y, r, tag: str):
        """Circle marking a detail region, with its reference tag."""
        self._els.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="none" '
            f'stroke="#a4632e" stroke-width="1" stroke-dasharray="4 3"/>')
        self._grow(x - r, y - r); self._grow(x + r, y + r)
        self.text(x, y - r - 4, tag, size=FONT - 2, weight="bold", color="#a4632e")

    def centerline(self, x1, y1, x2, y2):
        self.line(x1, y1, x2, y2, 0.5, dash="7 3 2 3", color="#a4632e")

    def ground_hatch(self, x, y, w, n=8):
        """Ground/hatch symbol along a baseline."""
        step = w / n
        for i in range(n):
            gx = x + i * step
            self.line(gx, y, gx - 5, y + 6, 0.5, color="#777")
        self.line(x, y, x + w, y, 0.8)

    def iso_box(self, ox, oy, L, Wd, H, scale=1.0, label=None):
        """Simple isometric box projection (30-degree).

        ``dx``/``dy`` are unit iso offsets; ``L``/``Wd``/``H`` carry the scale, so
        the depth offset is not scaled twice."""
        a = math.radians(30)
        dx, dy = math.cos(a), math.sin(a)
        L *= scale; Wd *= scale; H *= scale
        # front-bottom-left origin (ox, oy)
        p = {
            "A": (ox, oy),
            "B": (ox + L, oy),
            "C": (ox + L + Wd * dx, oy - Wd * dy),
            "D": (ox + Wd * dx, oy - Wd * dy),
        }
        top = {k: (x, y - H) for k, (x, y) in p.items()}
        self.polygon([p["A"], p["B"], top["B"], top["A"]], fill="#f4f1ec")   # front
        self.polygon([p["B"], p["C"], top["C"], top["B"]], fill="#e9e4da")   # side
        self.polygon([top["A"], top["B"], top["C"], top["D"]], fill="#fbfaf7")  # top
        if label is not None:
            self.text(ox + L / 2, oy + FONT, label, size=FONT)

    def _tick(self, x, y, vertical=False):
        if vertical:
            self.line(x - TICK / 2, y - TICK / 2, x + TICK / 2, y + TICK / 2, 1.2)
        else:
            self.line(x - TICK / 2, y - TICK / 2, x + TICK / 2, y + TICK / 2, 1.2)

    # ---- bounds checking (Gate 3 support) ----
    def overflowing_labels(self) -> list[TextBox]:
        """Text runs whose estimated box exceeds the viewBox (Lesson 9)."""
        bad = []
        for tb in self._texts:
            if (tb.x < 0 or tb.y < 0 or tb.x + tb.w > self.w + 0.5
                    or tb.y + tb.h > self.h + 0.5):
                bad.append(tb)
        return bad

    def geometry_overflow(self, tol: float = 0.5) -> tuple | None:
        """Drawn geometry extents exceeding the viewBox (e.g. a drawing running
        off its canvas edge — the side-elevation-cut-off class Gate 2 misses)."""
        minx, miny, maxx, maxy = self._ext
        if maxx < minx:
            return None
        if minx < -tol or miny < -tol or maxx > self.w + tol or maxy > self.h + tol:
            return (round(minx, 1), round(miny, 1), round(maxx, 1), round(maxy, 1))
        return None

    def render(self) -> str:
        stage_badge = ""
        if self.stage:
            stage_badge = (
                f'<rect x="{self.w - 150}" y="6" width="144" height="18" '
                f'fill="#111" rx="3"/>'
                f'<text x="{self.w - 78}" y="19" font-size="10" text-anchor="middle" '
                f'font-family="Helvetica,Arial" fill="#fff">STAGE: {_esc(self.stage.upper())}</text>'
            )
        title = ""
        if self.title:
            # The stage badge occupies the top-right; clip the in-drawing title so
            # it cannot run underneath it. The figure caption carries the full text,
            # so nothing is lost.
            avail = self.w - (165 if self.stage else 20)
            cap = max(8, int(avail / (12 * 0.58)))
            shown = self.title if len(self.title) <= cap else self.title[:cap - 1] + "…"
            title = (f'<text x="10" y="18" font-size="12" font-weight="bold" '
                     f'font-family="Helvetica,Arial" fill="#111">{_esc(shown)}</text>')
        body = "\n".join(self._els)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="100%" preserveAspectRatio="xMidYMid meet">'
            f'<rect x="0" y="0" width="{self.w}" height="{self.h}" fill="#fff"/>'
            f'{title}{stage_badge}{body}</svg>'
        )


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))
