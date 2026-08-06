"""Fastener catalog — Phase 1, section 2.1.

Separate from materials. Every entry carries pilot diameter, countersink
diameter and driver bit type, because the *tool schedule is derived from it*
and must be able to say "7/64 brad point" rather than "a drill bit."
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fastener:
    id: str
    display_name: str
    kind: str                 # screw | brad | staple | dowel | ...
    length: float             # inches
    pilot_diameter: float     # inches — drives the drill/bit schedule
    countersink_diameter: float
    driver_bit: str           # e.g. "T20 star", "#2 square"
    substrate_ok: tuple[str, ...]     # material categories it may drive into
    substrate_forbidden: tuple[str, ...]
    notes: str = ""


_FASTENERS: dict[str, Fastener] = {}


def _reg(f: Fastener) -> Fastener:
    _FASTENERS[f.id] = f
    return f


_reg(Fastener(
    id="screw_cabinet_2in",
    display_name='#8 x 2" cabinet screw',
    kind="screw",
    length=2.0,
    pilot_diameter=7 / 64,       # "7/64 brad point"
    countersink_diameter=0.328,
    driver_bit="#2 square",
    substrate_ok=("sheet_good", "hardwood", "lumber"),
    substrate_forbidden=("cement_board",),
    notes="Primary carcass fastener into plywood edges.",
))

_reg(Fastener(
    id="screw_cabinet_1_25in",
    display_name='#8 x 1-1/4" cabinet screw',
    kind="screw",
    length=1.25,
    pilot_diameter=7 / 64,
    countersink_diameter=0.328,
    driver_bit="#2 square",
    substrate_ok=("sheet_good", "hardwood", "lumber"),
    substrate_forbidden=("cement_board",),
    notes="Platform and rib attachment.",
))

_reg(Fastener(
    id="pocket_screw_1_25in",
    display_name='1-1/4" coarse pocket screw',
    kind="screw",
    length=1.25,
    pilot_diameter=0.0,          # pocket hole jig sets geometry; no separate pilot
    countersink_diameter=0.0,
    driver_bit="#2 square",
    substrate_ok=("sheet_good",),
    substrate_forbidden=("cement_board",),
    notes="Requires a pocket-hole jig set to 3/4 stock. Implies the jig in the tool schedule.",
))

_reg(Fastener(
    id="cement_board_screw_1_25in",
    display_name='1-1/4" cement board screw',
    kind="screw",
    length=1.25,
    pilot_diameter=0.0,          # self-drilling / Phillips wafer head
    countersink_diameter=0.0,
    driver_bit="#2 Phillips",
    substrate_ok=("cement_board", "sheet_good"),
    substrate_forbidden=(),
    notes=(
        "Corrosion-resistant wafer head. Drywall screws are explicitly excluded — "
        "they snap under the head in cement board (see derived_decisions)."
    ),
))

_reg(Fastener(
    id="brad_18ga_1in",
    display_name='18ga x 1" brad',
    kind="brad",
    length=1.0,
    pilot_diameter=0.0,
    countersink_diameter=0.0,
    driver_bit="18ga brad nailer",
    substrate_ok=("sheet_good",),
    substrate_forbidden=("cement_board",),
    notes="Tacks decks to the core ring during glue-up.",
))


def get_fastener(fid: str) -> Fastener:
    if fid not in _FASTENERS:
        raise KeyError(f"unknown fastener id: {fid!r}")
    return _FASTENERS[fid]


def all_fasteners() -> tuple[Fastener, ...]:
    return tuple(_FASTENERS.values())
