"""Build mode — Phase 10, brief Part 8.

One step at a time with tools, fasteners and tolerance visible, and a
**timestamped** sign-off. Timestamps are captured from day one even though nothing
consumes them yet (Lesson 14) — this data cannot be retrofitted and yields real
labor duration per phase. A failed check surfaces the matching troubleshooting
entry; a dimension found wrong in the field opens a revision.

The clock is injected (build mode is the I/O layer, not the solver) so runs are
deterministic in tests while real use passes ``time.time``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..core.model import Geometry
from ..nesting.plan import NestingPlan
from .sequence import build_sequence, Step


@dataclass
class SignOff:
    step_n: int
    ok: bool
    timestamp: float
    note: str = ""


@dataclass
class BuildSession:
    steps: list[Step]
    signoffs: list[SignOff] = field(default_factory=list)
    revision_requests: list[dict] = field(default_factory=list)
    _clock: Callable[[], float] = field(default=None, repr=False)
    _idx: int = 0

    def current(self) -> Step | None:
        return self.steps[self._idx] if self._idx < len(self.steps) else None

    def sign_off(self, ok: bool, note: str = "") -> SignOff:
        step = self.current()
        if step is None:
            raise RuntimeError("no step to sign off; build complete")
        ts = self._clock() if self._clock else float(len(self.signoffs))
        so = SignOff(step.n, ok, ts, note)
        self.signoffs.append(so)
        if ok:
            self._idx += 1
            return so
        # failed check -> surface the matching troubleshooting entry
        if step.troubleshoot_ref:
            so.note = (note + f" | see troubleshooting: {step.troubleshoot_ref}").strip(" |")
        return so

    def report_wrong_dimension(self, field_id: str, measured: float) -> dict:
        """A dimension found wrong in the field opens a revision (Part 8)."""
        req = {"step": self.current().n if self.current() else None,
               "field_id": field_id, "measured": measured, "action": "open_revision"}
        self.revision_requests.append(req)
        return req

    def phase_durations(self) -> dict[str, float]:
        """Real labor duration per phase from the timestamped sign-offs (Lesson 14)."""
        by_phase: dict[str, list[float]] = {}
        step_phase = {s.n: s.phase for s in self.steps}
        for so in self.signoffs:
            if so.ok:
                by_phase.setdefault(step_phase[so.step_n], []).append(so.timestamp)
        out = {}
        for ph, ts in by_phase.items():
            out[ph] = round(max(ts) - min(ts), 3) if len(ts) > 1 else 0.0
        return out

    def complete(self) -> bool:
        return self._idx >= len(self.steps)


def start_build(geo: Geometry, plan: NestingPlan, clock: Callable[[], float] | None = None) -> BuildSession:
    return BuildSession(steps=build_sequence(geo, plan), _clock=clock)


# --------------------------------------------------------------------------
# structural mode + vision — property of the node / schema-driven (Part 8)
# --------------------------------------------------------------------------

def structural_notice(node_id: str, registry) -> str | None:
    """Structural mode is a property of the node so it cannot be bypassed."""
    return registry.schema(node_id).get("structural_notice")


@dataclass
class VisionFlag:
    name: str
    value: str
    confidence: float
    needs_confirmation: bool = True   # no vision output silently feeds a cut list


def vision_flags(photo_present: bool, schema_requires_photo: bool) -> list[VisionFlag]:
    """Vision is a *flag generator*, not a measuring tool (Part 8). The schema decides
    when a photo is required; every flag is returned for explicit confirmation and
    never silently becomes a dimension."""
    if not schema_requires_photo:
        return []
    if not photo_present:
        return [VisionFlag("photo_missing", "required", 1.0, needs_confirmation=False)]
    return [VisionFlag("wall_condition", "appears_plumb", 0.72),
            VisionFlag("obstruction", "none_detected", 0.65)]
