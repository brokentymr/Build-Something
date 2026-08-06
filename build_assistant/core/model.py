"""Core geometry model — Phase 1, section 2.3.

Every dimension is a *triple*, never a scalar (section 2.3). Drawings and build
steps must declare which stage they quote; a dimension in a step without a stage
tag is a validation error.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

Stage = Literal["as_cut", "as_assembled", "as_finished"]
STAGES: tuple[Stage, ...] = ("as_cut", "as_assembled", "as_finished")


def _r(x: float) -> float:
    """Round to a clean shop precision (1/64") to kill float dust deterministically."""
    return round(round(x * 64.0) / 64.0, 6)


@dataclass(frozen=True)
class Dimension:
    """A stage-versioned length. Access by stage; never treated as a scalar."""

    as_cut: float
    as_assembled: float
    as_finished: float
    field_id: str = ""        # solver field id (Law 1 / Gate 1 provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_cut", _r(self.as_cut))
        object.__setattr__(self, "as_assembled", _r(self.as_assembled))
        object.__setattr__(self, "as_finished", _r(self.as_finished))

    def at(self, stage: Stage) -> float:
        return getattr(self, stage)

    def with_field(self, field_id: str) -> "Dimension":
        return replace(self, field_id=field_id)

    @classmethod
    def uniform(cls, value: float, field_id: str = "") -> "Dimension":
        return cls(value, value, value, field_id)


@dataclass(frozen=True)
class Face:
    """A single face of an element.

    ``exposed`` is decided by assembly, not geometry (section 2.2 / Lesson 3):
    a face buried against another element or on the floor receives no allowance.
    """

    name: str                 # top | bottom | left | right | front | back
    exposed: bool
    finish_id: str            # finish system id, or "none"
    occluded_depth: float = 0.0   # how much of this face another element's finish hides


@dataclass(frozen=True)
class Part:
    """A cut piece destined for the cut list and nesting."""

    id: str                   # A, B, C ...
    name: str
    material_id: str
    length: Dimension         # long dimension
    width: Dimension          # short dimension
    thickness: float          # actual material thickness
    qty: int
    grain: Literal["length", "width", "none"]
    stage_quoted: Stage       # the stage the cut list quotes (must be as_cut)
    source_element: str
    joint: str = ""

    def cut_wh(self) -> tuple[float, float]:
        return (self.length.as_cut, self.width.as_cut)

    def area_as_cut(self) -> float:
        return self.length.as_cut * self.width.as_cut


@dataclass(frozen=True)
class Element:
    """A physical assembly element (e.g. slab, plinth)."""

    id: str
    display_name: str
    finished_length: Dimension
    finished_width: Dimension
    finished_height: Dimension
    carcass_height: Dimension
    faces: tuple[Face, ...]
    z_base: float             # bottom of the element in overall stack coordinates
    footprint_inset: float    # inset per side vs overall footprint (finished)


@dataclass(frozen=True)
class DerivedDecision:
    """A calculated-not-asked decision — first-class solver output (Lesson 11)."""

    field_id: str
    label: str
    value: str
    basis: str
    is_overridable: bool


@dataclass(frozen=True)
class ScalarField:
    """A named solver scalar with a stable field id (Gate 1 provenance)."""

    field_id: str
    value: float
    unit: str = "in"


@dataclass(frozen=True)
class Geometry:
    """The complete solve output. Pure function of (answers, catalog, schema)."""

    node: str
    elements: tuple[Element, ...]
    parts: tuple[Part, ...]
    scalars: dict[str, ScalarField]
    derived_decisions: tuple[DerivedDecision, ...]
    finish_id: str
    per_face_offset: float
    inputs: dict[str, object]           # the seven answers, echoed
    structure: dict = field(default_factory=dict)  # height stack, backing, spans

    def scalar(self, field_id: str) -> float:
        return self.scalars[field_id].value

    def part(self, part_id: str) -> Part:
        for p in self.parts:
            if p.id == part_id:
                return p
        raise KeyError(part_id)

    def piece_count(self) -> int:
        return sum(p.qty for p in self.parts)

    def part_type_count(self) -> int:
        return len(self.parts)

    # ---- number provenance (Gate 1) ------------------------------------
    def all_field_ids(self) -> set[str]:
        ids = set(self.scalars.keys())
        for d in self.derived_decisions:
            ids.add(d.field_id)
        for p in self.parts:
            for dim in (p.length, p.width):
                if dim.field_id:
                    ids.add(dim.field_id)
        for e in self.elements:
            for dim in (e.finished_length, e.finished_width,
                        e.finished_height, e.carcass_height):
                if dim.field_id:
                    ids.add(dim.field_id)
        return ids

    def provenance_values(self) -> dict[str, float]:
        """field_id -> numeric value, for Gate 1 matching of prose numbers."""
        out: dict[str, float] = {fid: s.value for fid, s in self.scalars.items()}
        for p in self.parts:
            for dim in (p.length, p.width):
                if dim.field_id:
                    out.setdefault(dim.field_id + ".as_cut", dim.as_cut)
        for e in self.elements:
            for tag, dim in (
                ("carcass_height", e.carcass_height),
                ("finished_height", e.finished_height),
                ("finished_length", e.finished_length),
                ("finished_width", e.finished_width),
            ):
                if dim.field_id:
                    for stage in ("as_cut", "as_assembled", "as_finished"):
                        out.setdefault(f"{dim.field_id}.{stage}", getattr(dim, stage))
        return out
