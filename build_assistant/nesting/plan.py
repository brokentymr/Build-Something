"""Nesting orchestration — expands a solved Geometry into sheet nests.

Groups parts by material, expands quantities into individual pieces, and packs
each material onto its stock size. Returns one :class:`NestResult` per material
plus a combined cut-order flag and offcut manifest.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..catalog.materials import get_material
from ..core.model import Geometry
from ..core.glueup import glue_up
from .guillotine import nest, NestResult


@dataclass
class NestingPlan:
    nests: dict[str, NestResult]

    def cut_order_constrained(self) -> bool:
        return any(n.cut_order_constrained() for n in self.nests.values())

    def offcut_manifest(self) -> list[dict]:
        out: list[dict] = []
        for n in self.nests.values():
            out.extend(n.offcut_manifest())
        return out

    def purchase(self) -> dict[str, int]:
        return {mid: n.sheet_count() for mid, n in self.nests.items()}


def plan_nesting(geo: Geometry) -> NestingPlan:
    nests: dict[str, NestResult] = {}

    # --- carcass parts, grouped by material ---
    by_mat: dict[str, list[tuple[str, float, float]]] = {}
    for p in geo.parts:
        # An edge-glued panel is bought and cut as strips — nesting the finished
        # panel would ask for a board no mill sells.
        gl = glue_up(p)
        L, W = (gl.strip_length, gl.strip_width) if gl.is_glued else p.cut_wh()
        for i in range(p.qty * gl.count):
            by_mat.setdefault(p.material_id, []).append((f"{p.id}{i+1}", L, W))
    for mid, pieces in by_mat.items():
        mat = get_material(mid)
        stock = mat.stock_sizes[0]
        allow_rotate = mat.grain_direction == "none"
        if not allow_rotate:
            # Grained: each piece gets ONE fixed orientation (rotation stays off so
            # grain is never broken). Keep the piece as-given when it fits the sheet
            # that way; only swap length onto the long axis when it otherwise would
            # not fit (a part longer than the short sheet dimension).
            oriented = []
            for pid, L, Wd in pieces:
                if L <= stock.w + 1e-6 and Wd <= stock.h + 1e-6:
                    oriented.append((pid, L, Wd))
                else:
                    oriented.append((pid, Wd, L))       # length onto the long axis
            pieces = oriented
        nests[mid] = nest(mid, stock.w, stock.h, pieces, allow_rotate=allow_rotate)

    # --- finish skin panels (cement board) ---
    skins = geo.structure.get("skins", [])
    if skins:
        from ..catalog.finishes import get_finish
        sub_id = get_finish(geo.finish_id).substrate_material_id
        if sub_id:
            mat = get_material(sub_id)
            stock = mat.stock_sizes[0]
            pieces = []
            for sid, _name, w, h, qty in skins:
                for i in range(qty):
                    pieces.append((f"{sid}{i+1}", w, h))
            nests[sub_id] = nest(sub_id, stock.w, stock.h, pieces, allow_rotate=True)

    return NestingPlan(nests)
