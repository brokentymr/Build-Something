"""Edge-glued panels.

Solid stock comes in boards, and a board is only so wide. A 50in x 12in bookcase
side is not a stock-size problem to be trimmed away — it is four strips jointed
and glued into a panel, which is how solid casework has always been made. The
engine modelled only "one part, one piece of stock", so any solid panel wider
than the widest board was simply unbuildable and the design loop had nowhere to go.

The glue-up is *derived*, never stored: a part plus its material determines it, so
both the curated and the agent-authored paths get it without either having to
declare anything. That also keeps one source of truth — a stored count could
disagree with the part it sits on.

Strips are cut oversize by :data:`JOINT_ALLOWANCE`, because jointing the mating
edges takes material off, and the glued panel is trimmed to final width. Cutting
them to exact width would leave the panel narrow after jointing, which is the
expensive direction to be wrong in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Part
from ..catalog.materials import get_material, Material

#: Taken off each strip's mating edges when jointing, so strips are cut this much
#: wider and the glued panel is trimmed back.
JOINT_ALLOWANCE = 0.125

#: Categories that come as boards, and so can be edge-glued.
BOARD_CATEGORIES = ("lumber", "hardwood")


@dataclass(frozen=True)
class GlueUp:
    """How a part is made from stock. ``count == 1`` is a single piece."""

    count: int
    strip_length: float
    strip_width: float

    @property
    def is_glued(self) -> bool:
        return self.count > 1

    def describe(self) -> str:
        from ..drawing.primitives import fmt_inches
        if not self.is_glued:
            return ""
        return (f"glue up from {self.count} strips at "
                f"{fmt_inches(self.strip_width)} wide")


def board_width(mat: Material) -> float:
    """The widest board this material comes in."""
    return max((min(s.w, s.h) for s in mat.stock_sizes), default=0.0)


def board_length(mat: Material) -> float:
    return max((max(s.w, s.h) for s in mat.stock_sizes), default=0.0)


def glue_up_for(material_id: str, length: float, width: float) -> GlueUp:
    """Strips needed to make a panel of ``length`` x ``width`` from this stock."""
    single = GlueUp(1, length, width)
    try:
        mat = get_material(material_id)
    except Exception:  # noqa: BLE001 — unknown material stays a single piece
        return single
    if mat.category not in BOARD_CATEGORIES:
        return single
    bw, bl = board_width(mat), board_length(mat)
    if bw <= 0:
        return single
    # the long dimension runs with the grain, so the panel is glued across its width
    long_side, short_side = max(length, width), min(length, width)
    if short_side <= bw + 1e-6 or long_side > bl + 1e-6:
        return single                       # fits a board, or is too long for one
    usable = bw - JOINT_ALLOWANCE
    if usable <= 0:
        return single
    count = math.ceil(short_side / usable)
    return GlueUp(count, long_side, short_side / count + JOINT_ALLOWANCE)


def glue_up(part: Part) -> GlueUp:
    L, W = part.cut_wh()
    return glue_up_for(part.material_id, L, W)
