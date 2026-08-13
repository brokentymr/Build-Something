"""Material catalog — Phase 1, brief section 2.1.

A data table, not code. Every entry carries *nominal* and *actual* dimensions.
The solver consumes ``actual`` only (Law 1 / section 2.1).

NOTE ON 3/4 PLYWOOD ACTUAL THICKNESS
------------------------------------
The brief's prose seeds "3/4 birch plywood (actual 0.703)". The reference
fixture in section 2.5, however, is the *golden test* and its numbers are
computed against a 3/4 sheet good of actual thickness **0.75**:

    slab.carcass_thickness = 2.25 = 3 * 0.75   (two decks + core ring, all flat)
    plinth end_panel        = 11.75 = 13.25 - 2 * 0.75
    plywood utilisation      = 4084.75 / 4608 = 88.6%  (all parts one sheet)

None of those reproduce at 0.703 (3 * 0.703 = 2.109 != 2.25). The golden test
governs (section 2.5: "If your solver reproduces every number below ... it is
correct"), so the coffee_table build path references a 3/4 structural panel of
actual 0.75. The 0.703 birch entry is retained for completeness; nodes choose
their carcass material by id, so both coexist without engine changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class StockSize:
    w: float
    h: float


@dataclass(frozen=True)
class Material:
    id: str
    display_name: str
    category: str
    nominal_thickness: float
    actual_thickness: float
    actual_tolerance: float
    stock_sizes: tuple[StockSize, ...]
    grain_direction: Literal["length", "none"]
    requires_backing: bool
    density_lb_per_cuft: float
    notes: str = ""


# ---------------------------------------------------------------------------
# Seed catalog
# ---------------------------------------------------------------------------

_MATERIALS: dict[str, Material] = {}


def _reg(m: Material) -> Material:
    _MATERIALS[m.id] = m
    return m


# Structural 3/4 panel used by the coffee_table fixture (actual 0.75).
_reg(Material(
    id="ply_075_structural",
    display_name='3/4" plywood (structural)',
    category="sheet_good",
    nominal_thickness=0.75,
    actual_thickness=0.75,
    actual_tolerance=0.015,
    stock_sizes=(StockSize(48, 96),),
    grain_direction="length",
    requires_backing=False,
    density_lb_per_cuft=34.0,
    notes="Carcass panel for slab decks, core ring and plinth in the reference fixture.",
))

_reg(Material(
    id="ply_075_birch",
    display_name='3/4" birch plywood',
    category="sheet_good",
    nominal_thickness=0.75,
    actual_thickness=0.703,
    actual_tolerance=0.015,
    stock_sizes=(StockSize(48, 96),),
    grain_direction="length",
    requires_backing=False,
    density_lb_per_cuft=42.0,
    notes="Cabinet-grade birch; true actual 0.703. Not used by the fixture.",
))

_reg(Material(
    id="ply_050",
    display_name='1/2" plywood',
    category="sheet_good",
    nominal_thickness=0.5,
    actual_thickness=0.472,
    actual_tolerance=0.015,
    stock_sizes=(StockSize(48, 96),),
    grain_direction="length",
    requires_backing=False,
    density_lb_per_cuft=34.0,
))

_reg(Material(
    id="ply_025",
    display_name='1/4" plywood',
    category="sheet_good",
    nominal_thickness=0.25,
    actual_thickness=0.20,
    actual_tolerance=0.015,
    stock_sizes=(StockSize(48, 96),),
    grain_direction="length",
    requires_backing=False,
    density_lb_per_cuft=34.0,
))

_reg(Material(
    id="cement_board_025",
    display_name='1/4" cement board',
    category="cement_board",
    nominal_thickness=0.25,
    actual_thickness=0.25,
    actual_tolerance=0.02,
    stock_sizes=(StockSize(36, 60),),
    grain_direction="none",
    requires_backing=True,
    density_lb_per_cuft=100.0,
    notes="Rigid, dimensionally-stable substrate for microcement.",
))

_reg(Material(
    id="cement_board_050",
    display_name='1/2" cement board',
    category="cement_board",
    nominal_thickness=0.5,
    actual_thickness=0.5,
    actual_tolerance=0.02,
    stock_sizes=(StockSize(36, 60),),
    grain_direction="none",
    requires_backing=True,
    density_lb_per_cuft=100.0,
))

_reg(Material(
    id="mdf_075",
    display_name='3/4" MDF',
    category="sheet_good",
    nominal_thickness=0.75,
    actual_thickness=0.75,
    actual_tolerance=0.01,
    stock_sizes=(StockSize(49, 97),),
    grain_direction="none",
    requires_backing=False,
    density_lb_per_cuft=48.0,
))

# Dimensional lumber — real actuals.
for _nom, _aw, _ah in [
    ("2x4", 1.5, 3.5), ("2x6", 1.5, 5.5), ("2x8", 1.5, 7.25),
    ("2x10", 1.5, 9.25), ("2x12", 1.5, 11.25),
]:
    _reg(Material(
        id=f"lumber_{_nom}",
        display_name=f"{_nom} dimensional lumber",
        category="lumber",
        nominal_thickness=_aw,
        actual_thickness=_aw,
        actual_tolerance=0.03,
        stock_sizes=(StockSize(_ah, 96), StockSize(_ah, 120)),
        grain_direction="length",
        requires_backing=False,
        density_lb_per_cuft=32.0,
        notes=f"actual {_aw} x {_ah}",
    ))

# Hardwood in nominal quarters (4/4, 5/4, 6/4, 8/4).
for _q, _act in [("4_4", 0.8125), ("5_4", 1.0625), ("6_4", 1.3125), ("8_4", 1.8125)]:
    _reg(Material(
        id=f"hardwood_{_q}",
        display_name=f"{_q.replace('_', '/')} hardwood",
        category="hardwood",
        nominal_thickness=float(_q.split('_')[0]) / 4.0,
        actual_thickness=_act,
        actual_tolerance=0.03,
        # A hardwood dealer sells boards by the board foot in random widths and
        # lengths; 8ft was the only length here, which quietly made anything wider
        # than a 7ft sofa unbuildable in solid wood. 10 and 12ft are ordinary.
        stock_sizes=(StockSize(8, 96), StockSize(8, 120), StockSize(8, 144)),
        grain_direction="length",
        requires_backing=False,
        density_lb_per_cuft=45.0,
        notes="Surfaced two sides; actual is post-planing. Sold in random widths — "
              "8in is a fair planning width; wider panels are edge-glued.",
    ))


def get_material(mid: str) -> Material:
    if mid not in _MATERIALS:
        raise KeyError(f"unknown material id: {mid!r}")
    return _MATERIALS[mid]


def all_materials() -> tuple[Material, ...]:
    return tuple(_MATERIALS.values())
