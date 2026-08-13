"""Generative design IR — the parametric model the agent authors at runtime.

This is how "build anything" stays inside Law 1. The agent emits *structure and
relationships* — parameters, elements, which faces are finished, parts as
formulas over parameters and catalog actuals. It never emits a final dimension.
The engine (evaluator + compiler) computes every number deterministically.

A ``DesignIR`` is validated against a JSON schema before use and evaluated by a
whitelisted arithmetic evaluator (no arbitrary code). Same IR + same catalog →
same numbers → same hash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# A joint is declared on the part that is MACHINED. For a dado, groove, rabbet or
# mortise that part houses the other; for a tenon, lap, bridle, dowel or domino it
# is the member that enters. Both families cut as deep as the joint is long, which
# is what THROUGH_JOINTS is for — a housing cut, by contrast, goes about a third
# into its member.
ENTERING_JOINTS = ("tenon", "half_lap", "bridle", "dowel", "domino")
THROUGH_JOINTS = ENTERING_JOINTS + ("mortise",)


def joint_roles(joinery: dict, id_a: str, id_b: str):
    """``(housing_id, housed_id)`` for a contact, or ``(None, None)``.

    Reading the declaring part as the housing in every case draws the mortise on
    the wrong stick: a rail that says "tenon" is the one going in, not the one
    being cut into.
    """
    for declarer, other in ((id_a, id_b), (id_b, id_a)):
        spec = joinery.get(declarer)
        if not spec:
            continue
        if spec.get("type") in ENTERING_JOINTS:
            return other, declarer
        return declarer, other
    return None, None


@dataclass
class Param:
    id: str                       # symbol usable in expressions, e.g. "width"
    label: str
    value: float                  # in inches (converted on the way in)
    unit: str = "in"
    source: Literal["user", "default", "derived"] = "user"
    basis: str = ""


@dataclass
class MaterialRole:
    role: str                     # e.g. "carcass", "back", "shelf"
    material_id: str              # catalog id


@dataclass
class FaceSpec:
    name: str                     # top|bottom|left|right|front|back
    exposed: bool
    finished: bool                # receives the finish allowance


@dataclass
class ElementSpec:
    id: str
    kind: str                     # side|shelf|top|back|leg|rail|box ...
    length_expr: str              # expression over params/material symbols
    width_expr: str
    height_expr: str
    z_base_expr: str = "0"        # bottom of the element in the overall stack
    faces: list[FaceSpec] = field(default_factory=list)
    stacks_height: bool = False   # contributes to overall height stack


@dataclass
class PartSpec:
    id: str                       # A, B, C...
    name: str
    element: str                  # element id it belongs to
    material_role: str
    length_expr: str
    width_expr: str
    qty_expr: str = "1"
    grain: Literal["length", "width", "none"] = "length"
    finished_faces_len: int = 0   # # finished faces along the length axis (0-2)
    finished_faces_wid: int = 0
    joint: str = ""
    # placement of the FIRST instance in assembly space (inches), as expressions.
    # x=left→right, y=front→back(depth), z=floor→up. w/d/h are extents along x/y/z.
    # Two extents equal the cut size, one equals the material thickness. Optional:
    # when present, the engine draws real plan/elevation/exploded views.
    box_x: str = ""
    box_y: str = ""
    box_z: str = ""
    box_w: str = ""
    box_d: str = ""
    box_h: str = ""
    # for multi-instance parts (qty>1): step between instances, e.g. shelves up z.
    step_x: str = "0"
    step_y: str = "0"
    step_z: str = "0"
    # Instances that do not lie on a line — four legs at four corners, blocks in
    # the corners of a plinth — cannot be expressed by a step, which marches in one
    # direction. Give their origins outright instead, one [x, y, z] triple of
    # expressions per instance. Present, this replaces box_x/y/z and step_*.
    positions: list[list[str]] = field(default_factory=list)
    # Machined joinery. Declared on the part that is MACHINED: for a dado, groove,
    # rabbet or mortise that is the housing member; for a tenon, lap, bridle, dowel
    # or domino it is the member that enters. Drives the joint detail drawing,
    # which cuts the real profile instead of drawing a butt contact.
    joint_type: str = "butt"          # butt | dado | groove | rabbet | pocket | miter
    joint_depth_expr: str = ""        # how deep that cut goes, e.g. "carcass_t/3"

    def has_box(self) -> bool:
        return bool(self.box_w and self.box_d and self.box_h)


@dataclass
class SectionSpec:
    """A section the DESIGNER asks for — where to slice and why it matters.

    The agent chooses the viewpoint; the engine still computes every dimension it
    contains. Without any of these the engine falls back to picking a cut
    automatically."""
    tag: str                      # "A-A", "B-B" ...
    axis: str                     # x | y | z — the axis the cutting plane is normal to
    at_expr: str                  # position of the plane along that axis
    why: str = ""                 # what this section is meant to show


@dataclass
class InvariantSpec:
    kind: str                     # span | backing | positive | fits_stock | height_stack
    params: dict = field(default_factory=dict)


@dataclass
class DerivedNote:
    label: str
    value: str
    basis: str
    is_overridable: bool = True


@dataclass
class DesignIR:
    name: str
    summary: str
    node_kind: str                # free-form, e.g. "bookshelf", "planter"
    params: list[Param]
    materials: list[MaterialRole]
    finish_id: str                # finish system id or "none"
    elements: list[ElementSpec]
    parts: list[PartSpec]
    sections: list[SectionSpec] = field(default_factory=list)
    invariants: list[InvariantSpec] = field(default_factory=list)
    derived: list[DerivedNote] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    fasteners: list[dict] = field(default_factory=list)  # {fastener_id, seam_expr, spacing}
    warnings: list[str] = field(default_factory=list)

    # ---- (de)serialisation for storage + LLM exchange ----
    @classmethod
    def from_dict(cls, d: dict) -> "DesignIR":
        return cls(
            name=d["name"], summary=d.get("summary", ""), node_kind=d.get("node_kind", "build"),
            params=[Param(**p) for p in d["params"]],
            materials=[MaterialRole(**m) for m in d["materials"]],
            finish_id=d.get("finish_id", "none"),
            elements=[ElementSpec(
                id=e["id"], kind=e.get("kind", "part"),
                length_expr=str(e["length_expr"]), width_expr=str(e["width_expr"]),
                height_expr=str(e["height_expr"]), z_base_expr=str(e.get("z_base_expr", "0")),
                faces=[FaceSpec(**f) for f in e.get("faces", [])],
                stacks_height=e.get("stacks_height", False),
            ) for e in d["elements"]],
            parts=[PartSpec(
                id=p["id"], name=p["name"], element=p["element"],
                material_role=p["material_role"], length_expr=str(p["length_expr"]),
                width_expr=str(p["width_expr"]), qty_expr=str(p.get("qty_expr", "1")),
                grain=p.get("grain", "length"),
                finished_faces_len=int(p.get("finished_faces_len", 0)),
                finished_faces_wid=int(p.get("finished_faces_wid", 0)),
                joint=p.get("joint", ""),
                box_x=str(p.get("box_x", "")), box_y=str(p.get("box_y", "")),
                box_z=str(p.get("box_z", "")), box_w=str(p.get("box_w", "")),
                box_d=str(p.get("box_d", "")), box_h=str(p.get("box_h", "")),
                step_x=str(p.get("step_x", "0")), step_y=str(p.get("step_y", "0")),
                step_z=str(p.get("step_z", "0")),
                positions=[[str(v) for v in pos][:3]
                           for pos in (p.get("positions") or []) if len(pos) >= 3],
                joint_type=str(p.get("joint_type", "butt") or "butt"),
                joint_depth_expr=str(p.get("joint_depth_expr", "")),
            ) for p in d["parts"]],
            sections=[SectionSpec(tag=str(x.get("tag", f"S{n+1}")), axis=str(x.get("axis", "x")),
                                 at_expr=str(x.get("at_expr", x.get("at", ""))), why=str(x.get("why", "")))
                      for n, x in enumerate(d.get("sections", []))],
            invariants=[InvariantSpec(kind=i["kind"], params=i.get("params", {}))
                        for i in d.get("invariants", [])],
            derived=[DerivedNote(**n) for n in d.get("derived", [])],
            operations=list(d.get("operations", [])),
            fasteners=list(d.get("fasteners", [])),
            warnings=list(d.get("warnings", [])),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name, "summary": self.summary, "node_kind": self.node_kind,
            "params": [vars(p) for p in self.params],
            "materials": [vars(m) for m in self.materials],
            "finish_id": self.finish_id,
            "elements": [{**vars(e), "faces": [vars(f) for f in e.faces]} for e in self.elements],
            "parts": [vars(p) for p in self.parts],
            "sections": [vars(x) for x in self.sections],
            "invariants": [vars(i) for i in self.invariants],
            "derived": [vars(n) for n in self.derived],
            "operations": self.operations, "fasteners": self.fasteners, "warnings": self.warnings,
        }
