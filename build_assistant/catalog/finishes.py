"""Finish system catalog — Phase 1, sections 2.1 and 2.2.

A finish system imposes a *per-face offset* between substrate and finished
surface. Tile, veneer, plaster, drywall, laminate, paint, powder coat and
upholstery are all the same transform with different numbers (section 2.2).

``direction`` records which way finished geometry moves relative to substrate.
It is a *required field* (Lesson 2): allowance is directional and not every
part is cut smaller.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FinishLayer:
    name: str
    thickness: float


@dataclass(frozen=True)
class FinishSystem:
    id: str
    display_name: str
    layers: tuple[FinishLayer, ...]
    direction: str                     # additive_outward | additive_inward | subtractive
    substrate_requirements: tuple[str, ...]
    incompatible_substrates: tuple[str, ...]
    substrate_material_id: str | None  # the rigid backing this system is built on
    notes: str = ""

    @property
    def per_face_offset(self) -> float:
        """Sum of layer thicknesses — the substrate-to-finished-surface offset."""
        return round(sum(layer.thickness for layer in self.layers), 6)


_FINISHES: dict[str, FinishSystem] = {}


def _reg(fs: FinishSystem) -> FinishSystem:
    _FINISHES[fs.id] = fs
    return fs


# Reference fixture finish: microcement over cement board.
#   cement board 0.25 + microcement 0.125 = 0.375 per_face_offset.
_reg(FinishSystem(
    id="microcement_over_cement_board",
    display_name="Microcement over cement board",
    layers=(
        FinishLayer("cement board substrate", 0.25),
        FinishLayer("microcement (base + top coats)", 0.125),
    ),
    direction="additive_outward",
    substrate_requirements=("rigid", "dimensionally_stable"),
    incompatible_substrates=("solid_wood", "bare_mdf"),
    substrate_material_id="cement_board_025",
    notes=(
        "Troweled cementitious overlay on a rigid board substrate. The cement "
        "board is the backing that the microcement bonds to; the plywood carcass "
        "beneath is fine because it never sees the microcement directly."
    ),
))

_reg(FinishSystem(
    id="paint_buildup",
    display_name="Primer + paint buildup",
    layers=(FinishLayer("primer + 2 coats", 0.02),),
    direction="additive_outward",
    substrate_requirements=("dimensionally_stable",),
    incompatible_substrates=(),
    substrate_material_id=None,
))

_reg(FinishSystem(
    id="veneer_backed",
    display_name="Wood veneer with backer",
    layers=(FinishLayer("veneer", 0.025), FinishLayer("glue line", 0.005)),
    direction="additive_outward",
    substrate_requirements=("dimensionally_stable",),
    incompatible_substrates=(),
    substrate_material_id=None,
))

_reg(FinishSystem(
    id="none",
    display_name="No finish (bare substrate)",
    layers=(),
    direction="subtractive",
    substrate_requirements=(),
    incompatible_substrates=(),
    substrate_material_id=None,
))


def get_finish(fid: str) -> FinishSystem:
    if fid not in _FINISHES:
        raise KeyError(f"unknown finish system id: {fid!r}")
    return _FINISHES[fid]


def all_finishes() -> tuple[FinishSystem, ...]:
    return tuple(_FINISHES.values())
