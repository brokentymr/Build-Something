"""The allowance layer — Phase 1, section 2.2.

A finish system imposes a per-face offset between substrate and finished surface.
This module is the *only* place that transform lives. Three facts the brief
insists on, each encoded as an explicit primitive:

* Faces are exposed or concealed by **assembly, not geometry** (Lesson 3). The
  caller passes which faces are exposed; this module never inspects a bounding
  box.
* Direction matters and is **not always subtractive** (Lesson 2). ``substrate``
  can be larger *or* smaller than finished. Both occur in the reference fixture.
* Some substrate is cut **larger** because its face is occluded by a neighbour's
  finish sitting proud of it (the plinth top, Lesson 2).

Every function is pure arithmetic over floats.
"""

from __future__ import annotations

ADDITIVE_OUTWARD = "additive_outward"
ADDITIVE_INWARD = "additive_inward"
SUBTRACTIVE = "subtractive"
_VALID = {ADDITIVE_OUTWARD, ADDITIVE_INWARD, SUBTRACTIVE}


def substrate_from_finished(
    finished: float, offset: float, exposed_faces: int, direction: str
) -> float:
    """Substrate (as-cut) size needed to reach ``finished`` after the finish.

    ``exposed_faces`` is the number of skinned faces along this axis (0, 1 or 2).
    A concealed face contributes nothing — that is the whole point of Lesson 3.

    * ``additive_outward``: finish grows outward, so the substrate is cut
      *smaller* by ``offset`` per exposed face.
    * ``additive_inward``: finish grows into a cavity, substrate *larger*.
    * ``subtractive``: finished surface is machined into the substrate; the
      substrate must start *larger*.
    """
    if direction not in _VALID:
        raise ValueError(f"unknown allowance direction: {direction!r}")
    if exposed_faces < 0 or exposed_faces > 2:
        raise ValueError(f"exposed_faces must be 0..2, got {exposed_faces}")
    total = offset * exposed_faces
    if direction == ADDITIVE_OUTWARD:
        return finished - total
    return finished + total          # additive_inward, subtractive both add stock


def finished_from_substrate(
    substrate: float, offset: float, exposed_faces: int, direction: str
) -> float:
    """Inverse of :func:`substrate_from_finished`."""
    if direction not in _VALID:
        raise ValueError(f"unknown allowance direction: {direction!r}")
    total = offset * exposed_faces
    if direction == ADDITIVE_OUTWARD:
        return substrate + total
    return substrate - total


def visible_after_occlusion(cut_value: float, occluded_depth: float) -> float:
    """Visible (as-finished) size of a face partly hidden by a neighbour's finish.

    The plinth is cut 3/8 *taller* than it reads on the finished piece because the
    slab edge occludes its top 3/8 (Lesson 2). ``occluded_depth`` is positive and
    is present in ``as_cut`` but absent from ``as_finished``.
    """
    if occluded_depth < 0:
        raise ValueError("occluded_depth must be >= 0")
    return cut_value - occluded_depth


def carcass_inset_from_reveal(reveal: float, offset: float, exposed_faces: int = 1) -> float:
    """Carcass (as-assembled) inset that yields a finished ``reveal``.

    The inset element grows outward by its own skin, so it must be set in
    *further* than the visible reveal (fixture: 3.375 as-assembled -> 3.0 finished).
    """
    return reveal + offset * exposed_faces


def reveal_from_carcass_inset(carcass_inset: float, offset: float, exposed_faces: int = 1) -> float:
    """Inverse of :func:`carcass_inset_from_reveal`."""
    return carcass_inset - offset * exposed_faces
