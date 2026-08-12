"""Placement audit — catches designs that compile but are not real objects.

The invariant checker proves parts are cuttable and spans are safe. It says
nothing about whether the parts are *assembled into anything*. A design can pass
every invariant while its shelves march out of the case into open air: the
expressions evaluate, the parts fit stock, and the cut list looks sane. Only the
placement reveals it.

These checks are deterministic and run inside the design loop, so the agent gets
the exact defect back and repairs it before anyone sees a drawing.

Checks
------
* **Escaped parts** — a part sitting outside the object's own declared envelope.
* **Floating parts** — an instance touching nothing else in the assembly.
* **Interpenetration** — two parts occupying the same space.
* **Duplicate stacking** — repeated instances landing on top of each other.
* **Useless section** — a directed cut plane that reveals fewer than two parts.
"""

from __future__ import annotations

from ..core.model import Geometry

TOL = 0.02
AXES = (("x", "w"), ("y", "d"), ("z", "h"))


def _span(b, lo, ext):
    return b[lo], b[lo] + b[ext]


def _overlap_len(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def _axis_overlap(a, b, i):
    lo, ext = AXES[i]
    return _overlap_len(a[lo], a[lo] + a[ext], b[lo], b[lo] + b[ext])


def _relation(a, b, tol=TOL):
    """(touching, penetration_depth) for two boxes.

    ``penetration_depth`` is how far they actually share space — the smallest
    overlap across the three axes. Zero means they only meet at a face."""
    gaps = []
    for lo, ext in AXES:
        a0, a1 = _span(a, lo, ext)
        b0, b1 = _span(b, lo, ext)
        gaps.append(_overlap_len(a0, a1, b0, b1))
    penetration = min(gaps) if all(g > tol for g in gaps) else 0.0
    touching = False
    for i in range(3):
        others = [gaps[j] for j in range(3) if j != i]
        if all(o > tol for o in others) and abs(gaps[i]) <= 0.06:
            touching = True
            break
    return touching, penetration


def envelope(geo: Geometry):
    """The object's own declared outer box, from its elements."""
    els = geo.elements
    if not els:
        return None
    x1 = max(e.finished_length.as_finished for e in els)
    y1 = max(e.finished_width.as_finished for e in els)
    z0 = min(e.z_base for e in els)
    z1 = max(e.z_base + e.finished_height.as_finished for e in els)
    return (0.0, 0.0, z0, x1, y1, z1)


def audit_placement(geo: Geometry) -> list[str]:
    """Return human-readable defects. Empty list means the assembly hangs together."""
    boxes = geo.structure.get("boxes") or []
    if not boxes:
        return []
    issues: list[str] = []
    names = {p.id: p.name for p in geo.parts}
    joinery = geo.structure.get("joinery", {})

    # ---- 1. parts escaping the declared envelope --------------------------
    env = envelope(geo)
    if env:
        ex0, ey0, ez0, ex1, ey1, ez1 = env
        slack = max(1.0, 0.03 * max(ex1 - ex0, ey1 - ey0, ez1 - ez0))
        escaped: dict[str, list[str]] = {}
        for b in boxes:
            over = []
            if b["x"] + b["w"] > ex1 + slack:
                over.append(f"x reaches {b['x'] + b['w']:.1f} but the piece is only {ex1:.1f} wide")
            if b["x"] < ex0 - slack:
                over.append(f"x starts at {b['x']:.1f}, left of the piece")
            if b["y"] + b["d"] > ey1 + slack:
                over.append(f"y reaches {b['y'] + b['d']:.1f} but the piece is only {ey1:.1f} deep")
            if b["z"] + b["h"] > ez1 + slack:
                over.append(f"z reaches {b['z'] + b['h']:.1f} but the piece is only {ez1:.1f} tall")
            if over:
                escaped.setdefault(b["id"], []).append(over[0])
        for pid, msgs in escaped.items():
            issues.append(
                f"part {pid} ({names.get(pid, pid)}) is placed outside the object: {msgs[0]}. "
                f"{len(msgs)} of its instances escape — check its box_* origin and its "
                f"step_x/step_y/step_z, which should repeat instances INSIDE the piece.")

    # ---- 2. floating instances (touch nothing) ----------------------------
    floating: dict[str, int] = {}
    for i, b in enumerate(boxes):
        rel = [_relation(b, o) for j, o in enumerate(boxes) if i != j]
        if not any(t or pen > 0 for t, pen in rel):
            floating[b["id"]] = floating.get(b["id"], 0) + 1
    for pid, n in floating.items():
        issues.append(
            f"part {pid} ({names.get(pid, pid)}) has {n} instance(s) touching nothing — "
            f"it floats free of the assembly. Place it against the parts it fixes to.")

    # ---- 3. interpenetration ----------------------------------------------
    seen_pairs = set()
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a["id"] == b["id"]:
                continue
            key = tuple(sorted((a["id"], b["id"])))
            if key in seen_pairs:
                continue
            _, pen = _relation(a, b)
            if pen <= 0:
                continue
            # a part housed in a dado/rabbet is SUPPOSED to sit inside its housing,
            # up to the depth of that cut — only flag penetration beyond it
            allowed = 0.06
            for pid in (a["id"], b["id"]):
                j = joinery.get(pid)
                if j:
                    allowed = max(allowed, j.get("depth", 0.0) + 0.06)
            if pen > allowed:
                seen_pairs.add(key)
                # name the axis they collide on and prescribe the fix, so the
                # repair step has something to act on rather than a complaint
                axis_i = min(range(3), key=lambda k: _axis_overlap(a, b, k))
                lo, ext = AXES[axis_i]
                thinner, thicker = (a, b) if a[ext] <= b[ext] else (b, a)
                spanner, obstacle = (a, b) if a[ext] >= b[ext] else (b, a)
                inside = (obstacle[lo] > spanner[lo] + TOL
                          and obstacle[lo] + obstacle[ext] < spanner[lo] + spanner[ext] - TOL)
                if inside:
                    # A shelf running straight through a centre divider cannot be
                    # cured by shortening it — that empties one bay. It has to
                    # become one piece per bay, so say so with the numbers.
                    bay = obstacle[lo] - spanner[lo]
                    step = obstacle[lo] + obstacle[ext] - spanner[lo]
                    issues.append(
                        f"part {spanner['id']} runs straight through {obstacle['id']}, which "
                        f"stands inside its span on {lo}. Do NOT just shorten it — that would "
                        f"leave one bay empty. Make it one piece per bay: keep "
                        f"box_{lo}={spanner[lo]:.3f}, set box_{ext}={bay:.3f} (the bay width), "
                        f"set qty to 2 per level and step_{lo}={step:.3f} so the second piece "
                        f"starts on the far side of {obstacle['id']}. Adjust the cut list "
                        f"length to match.")
                else:
                    start = thicker[lo] + thicker[ext]
                    issues.append(
                        f"parts {a['id']} and {b['id']} pass through each other: they share "
                        f"{pen:.2f}in along {lo}. Fix by shortening one of them on {lo} so it "
                        f"stops at the other's face — e.g. give {thinner['id']} "
                        f"box_{lo}={start:.3f} and reduce its box_{ext} by {pen:.2f}, or start it "
                        f"at {thicker[lo] - thinner[ext]:.3f}. A part spans BETWEEN its "
                        f"neighbours or seats into a dado by that cut's depth — never through "
                        f"solid wood.")

    # ---- 4. repeated instances landing on each other ----------------------
    by_id: dict[str, list] = {}
    for b in boxes:
        by_id.setdefault(b["id"], []).append(b)
    for pid, group in by_id.items():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if all(abs(a[lo] - b[lo]) <= TOL for lo, _ in AXES):
                    issues.append(
                        f"part {pid} ({names.get(pid, pid)}) has instances stacked at the same "
                        f"position — its step_x/step_y/step_z do not separate the copies.")
                    break
            else:
                continue
            break

    # ---- 5. solids drawn at the wrong stock thickness ---------------------
    # A part is cut from real stock, so one of its three box dimensions has to BE
    # that stock's thickness (or a multiple of it, for a lamination). A back panel
    # written as `box_d = rabbet_depth` is 3/4in plywood modelled 1/4in thick: the
    # cut list buys one thing and every drawing shows another.
    parts_by_id = {p.id: p for p in geo.parts}
    for pid, group in by_id.items():
        part = parts_by_id.get(pid)
        if not part or part.thickness <= 0:
            continue
        b = group[0]
        dims = {ext: b[ext] for _, ext in AXES}
        if any(any(abs(v - n * part.thickness) <= 0.04 for n in (1, 2, 3, 4))
               for v in dims.values()):
            continue
        axis_ext = min(dims, key=dims.get)
        axis_lo = next(lo for lo, ext in AXES if ext == axis_ext)
        issues.append(
            f"part {pid} ({names.get(pid, pid)}) is cut from {part.thickness:.3f}in stock "
            f"but its solid is {dims[axis_ext]:.2f}in thick on {axis_lo} — the drawings would "
            f"show a panel the cut list does not buy. Set box_{axis_ext} to the stock "
            f"thickness ({part.thickness:.3f}), and use the joint depth only to seat it.")

    # ---- 6. directed sections that reveal nothing -------------------------
    for spec in geo.structure.get("sections") or []:
        axis = spec.get("axis", "x")
        lo, ext = {"x": ("x", "w"), "y": ("y", "d"), "z": ("z", "h")}[axis]
        at = spec.get("at")
        hit = {b["id"] for b in boxes if b[lo] - 1e-6 < at < b[lo] + b[ext] + 1e-6}
        if len(hit) < 2:
            issues.append(
                f"section {spec.get('tag')} cuts at {at} on {axis} but passes through "
                f"{len(hit)} part(s) — move it to a plane that reveals the structure.")

    return issues
