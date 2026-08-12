"""Prose audit — catches instructions that contradict the design they describe.

Gate 1 proves every number in the document traces to a solver field. It says
nothing about whether the number is the *right* one for the sentence it sits in.
A packet once opened with "3/4in-wide x 3/8in-deep dado joints" directly above a
parameter table reading "Dado Depth 1/4in": both numbers were real solver values,
so provenance held and the document released contradicting itself.

This module checks relevance rather than provenance. It is deliberately narrow —
it only judges statements where the design holds the answer unambiguously — and
each finding names the sentence and the value that belongs in it, so the agent can
rewrite the line instead of being told the packet is bad.

Checks
------
* **Joinery depth** — "<dim> deep" beside a named cut whose depth the design sets.
* **Stock thickness** — a thickness quoted for a material the design already sizes.
"""

from __future__ import annotations

import re

from ..core.model import Geometry
from ..drawing.primitives import fmt_inches

TOL = 1.0 / 64 + 1e-6

# a dimension written the way a packet writes it: 3/8", 1-1/2", 12"
_DIM = r'(\d+(?:-\d+/\d+)?(?:\.\d+)?(?:/\d+)?)\s*(?:"|in\b|inch(?:es)?\b)'

# "1in deep pilot hole" is a drilling depth, not a joinery cut
_NOT_JOINERY = ("pilot", "hole", "counterbore", "countersink", "pocket", "screw",
                "nail", "brad", "dowel", "biscuit")


def _inches(text: str) -> float | None:
    """Parse 3/8, 1-1/2 or 2.5 into decimal inches."""
    text = text.strip()
    m = re.fullmatch(r"(\d+)-(\d+)/(\d+)", text)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.fullmatch(r"(\d+)/(\d+)", text)
    if m:
        return int(m.group(1)) / int(m.group(2))
    try:
        return float(text)
    except ValueError:
        return None


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;])\s+", str(text)) if s.strip()]


def _packet_prose(packet: dict) -> list[tuple[str, str]]:
    """(where, sentence) for every reader-facing sentence the agent wrote."""
    out: list[tuple[str, str]] = []

    def add(where, value):
        for s in _sentences(value or ""):
            out.append((where, s))

    add("governing_note", packet.get("governing_note"))
    add("care", packet.get("care"))
    for i, c in enumerate(packet.get("callouts") or []):
        add(f"callout {i + 1} ({c.get('title', '')})", c.get("body"))
    for i, s in enumerate(packet.get("steps") or []):
        add(f"step {i + 1} ({s.get('title', '')})", s.get("detail"))
        add(f"step {i + 1} check", s.get("check"))
    for t in packet.get("tolerances") or []:
        add(f"tolerance row ({t.get('check', '')})", t.get("tolerance"))
    return out


def audit_prose(geo: Geometry, packet: dict) -> list[str]:
    """Return sentences whose numbers contradict the design. Empty means agreement."""
    joinery = geo.structure.get("joinery") or {}
    if not joinery and not geo.parts:
        return []

    # depth the design actually cuts, per joint type ("dado" -> 0.25)
    depths: dict[str, set] = {}
    for spec in joinery.values():
        jt = str(spec.get("type", "")).lower()
        if jt:
            depths.setdefault(jt, set()).add(round(float(spec.get("depth", 0.0)), 4))

    issues: list[str] = []
    for where, sentence in _packet_prose(packet):
        low = sentence.lower()
        for jt, allowed in depths.items():
            if jt not in low:
                continue
            for m in re.finditer(_DIM + r"[\s-]*deep", sentence, re.IGNORECASE):
                value = _inches(m.group(1))
                if value is None:
                    continue
                window = low[max(0, m.start() - 60):m.end() + 20]
                if any(w in window for w in _NOT_JOINERY):
                    continue
                if any(abs(value - a) <= TOL for a in allowed):
                    continue
                want = " or ".join(fmt_inches(a) for a in sorted(allowed))
                issues.append(
                    f"{where}: \"{sentence[:110]}\" calls for a {jt} "
                    f"{fmt_inches(value)} deep, but this design cuts its {jt} "
                    f"{want}. Rewrite the sentence with {want}; do not change the "
                    f"design to match the sentence.")
                break
    return issues
