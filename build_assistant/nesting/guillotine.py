"""Nesting engine — Phase 3, brief Part 4.

Guillotine-constrained rectangle packing: kerf-aware, orientation-aware,
grain-constrained where declared. Outputs per-sheet layouts with x/y/w/h and
orientation, utilisation per sheet, purchase quantities and an offcut manifest.

Two non-obvious behaviours (Part 4):
* Utilisation above 0.85 emits a **cut-order constraint** into the build sequence.
* Offcuts are **claimable** by the build-sequence generator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KERF = 0.125                 # 1/8" saw kerf
HIGH_UTIL = 0.85             # cut-order constraint threshold (Part 4)
MIN_CLAIMABLE = 9.0 * 18.0   # a claimable offcut is at least 9 x 18


@dataclass(frozen=True)
class Placement:
    part_id: str
    x: float
    y: float
    w: float                 # placed width (after any rotation)
    h: float
    rotated: bool


@dataclass
class FreeRect:
    x: float
    y: float
    w: float
    h: float


@dataclass
class SheetLayout:
    material_id: str
    sheet_w: float
    sheet_h: float
    index: int
    placements: list[Placement] = field(default_factory=list)
    free_rects: list[FreeRect] = field(default_factory=list)

    def used_area(self) -> float:
        return sum(p.w * p.h for p in self.placements)

    def sheet_area(self) -> float:
        return self.sheet_w * self.sheet_h

    def utilisation(self) -> float:
        return self.used_area() / self.sheet_area()

    def offcuts(self) -> list[FreeRect]:
        return [r for r in self.free_rects if r.w * r.h >= MIN_CLAIMABLE
                and min(r.w, r.h) >= 9.0]


@dataclass
class NestResult:
    material_id: str
    sheet_w: float
    sheet_h: float
    sheets: list[SheetLayout]

    def sheet_count(self) -> int:
        return len(self.sheets)

    def total_utilisation(self) -> float:
        used = sum(s.used_area() for s in self.sheets)
        return used / (self.sheets[0].sheet_area() * len(self.sheets)) if self.sheets else 0.0

    def high_util_sheets(self) -> list[int]:
        return [s.index for s in self.sheets if s.utilisation() > HIGH_UTIL]

    def cut_order_constrained(self) -> bool:
        return bool(self.high_util_sheets())

    def offcut_manifest(self) -> list[dict]:
        out = []
        for s in self.sheets:
            for r in s.offcuts():
                out.append({"sheet": s.index, "material_id": self.material_id,
                            "w": round(r.w, 3), "h": round(r.h, 3),
                            "area": round(r.w * r.h, 2)})
        return out


# ---------------------------------------------------------------------------
# Guillotine placement (best-short-side-fit, guillotine split, rotation)
# ---------------------------------------------------------------------------

def _fits(rw: float, rh: float, fr: FreeRect) -> bool:
    return rw <= fr.w + 1e-9 and rh <= fr.h + 1e-9


def _place_in(sheet: SheetLayout, part_id: str, w: float, h: float,
              allow_rotate: bool) -> bool:
    """Try to place a w x h part (kerf already included) into the sheet."""
    best = None  # (score, idx, rw, rh, rotated)
    for idx, fr in enumerate(sheet.free_rects):
        for rw, rh, rot in ((w, h, False), (h, w, True)):
            if rot and not allow_rotate:
                continue
            if _fits(rw, rh, fr):
                short_leftover = min(fr.w - rw, fr.h - rh)
                score = short_leftover
                if best is None or score < best[0]:
                    best = (score, idx, rw, rh, rot)
    if best is None:
        return False
    _, idx, rw, rh, rot = best
    fr = sheet.free_rects.pop(idx)
    sheet.placements.append(Placement(part_id, fr.x, fr.y, rw - KERF, rh - KERF, rot))
    # Guillotine split: split remaining L-shape along the longer leftover axis.
    right = FreeRect(fr.x + rw, fr.y, fr.w - rw, rh)
    top = FreeRect(fr.x, fr.y + rh, fr.w, fr.h - rh)
    for nr in (right, top):
        if nr.w > 1e-6 and nr.h > 1e-6:
            sheet.free_rects.append(nr)
    return True


def nest(material_id: str, sheet_w: float, sheet_h: float,
         pieces: list[tuple[str, float, float]], allow_rotate: bool = True) -> NestResult:
    """Pack ``pieces`` (part_id, w, h) onto ``sheet_w`` x ``sheet_h`` sheets.

    Deterministic: pieces are sorted by descending max dimension then area, so the
    result is a pure function of the input list.
    """
    order = sorted(pieces, key=lambda p: (-max(p[1], p[2]), -(p[1] * p[2]), p[0]))
    sheets: list[SheetLayout] = []

    def new_sheet() -> SheetLayout:
        s = SheetLayout(material_id, sheet_w, sheet_h, len(sheets) + 1)
        s.free_rects.append(FreeRect(0, 0, sheet_w, sheet_h))
        sheets.append(s)
        return s

    for pid, pw, ph in order:
        w, h = pw + KERF, ph + KERF
        placed = False
        for s in sheets:
            if _place_in(s, pid, w, h, allow_rotate):
                placed = True
                break
        if not placed:
            s = new_sheet()
            if not _place_in(s, pid, w, h, allow_rotate):
                raise ValueError(
                    f"part {pid} ({pw}x{ph}) does not fit a {sheet_w}x{sheet_h} "
                    f"sheet of {material_id} even empty"
                )
    return NestResult(material_id, sheet_w, sheet_h, sheets)
