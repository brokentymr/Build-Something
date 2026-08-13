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


def _long_axis(b):
    """The axis a part *runs* along — its length direction."""
    return max(AXES, key=lambda ax: b[ax[1]])[0]


def _joint_shaped(a, b, lo, pen):
    """The part whose end is in the other, when an overlap is a joint's worth deep.

    A rail whose end sits inside a post overlaps it by one board thickness — that
    overlap *is* the joint. Two panels lying broadside into each other overlap by
    exactly the same amount and mean something completely different, and no
    geometry tells the two apart: they are the same boxes. An earlier version of
    this tried, using which axis the parts collided on, and got it wrong for a
    corner block meeting an arm panel face-on — three rounds of a live run went to
    a pair the audit was describing backwards.

    So this no longer classifies. Any overlap within one board thickness is
    reported as *possibly* a joint, with both remedies and the numbers for each,
    and the model — which knows whether it meant a tenon there — picks. Deeper
    than a board is a collision on any reading, and only one remedy applies.
    """
    if pen > min(_stock_of(a), _stock_of(b)) + TOL:
        return None
    # Whichever part is arriving end-on gets the advice; the one whose length runs
    # along the collision axis is the better guess, else the thinner of the two.
    ends_on = [p for p in (a, b) if _long_axis(p) == lo]
    if ends_on:
        return ends_on[0]
    ext = dict(AXES)[lo]
    return a if a[ext] <= b[ext] else b


def _stock_of(b):
    """A part's own board thickness — the smallest of its three extents."""
    return min(b[ext] for _, ext in AXES)


def _butt_remedy(arriving, host, lo, ext, pen):
    """How to back a buried end out to the host's face — from the correct end.

    Which end of the arriving part is inside decides the fix. A shelf whose left
    end is in the side panel moves right and loses that much length; a side panel
    whose top is sunk into the lid keeps its origin and loses the length off the
    top. Translating the wrong end drags the part through the floor.
    """
    a_c = arriving[lo] + arriving[ext] / 2.0
    h_c = host[lo] + host[ext] / 2.0
    shorter = arriving[ext] - pen
    if shorter <= 0.02:
        # Nothing to trim: the part lies wholly inside the other on this axis. It
        # has not been pushed a board too far, it has been put in the wrong place —
        # and "reduce box_d by 0.20" on a 0.20in overlap deletes it.
        low, high = host[lo] - arriving[ext], host[lo] + host[ext]
        pick = low if abs(low - arriving[lo]) <= abs(high - arriving[lo]) else high
        return (f"set box_{lo}={pick:.3f} — it sits wholly within {host['id']} on "
                f"{lo}, so there is nothing to shorten; it has to move clear")
    if h_c > a_c:                      # the far end is buried — trim it back
        return (f"keep box_{lo}={arriving[lo]:.3f} and set box_{ext}={shorter:.3f} "
                f"({pen:.2f} shorter) so it stops under {host['id']}")
    return (f"set box_{lo}={host[lo] + host[ext]:.3f} and box_{ext}={shorter:.3f} "
            f"so it starts at {host['id']}'s face instead of inside it")


def _flush_remedy(b, boxes, names):
    """Name the coordinate that seats a floating instance against its neighbour.

    'Place it against the parts it fixes to' is true and useless: the repair
    guesses a coordinate, overshoots into the neighbour, gets an interpenetration
    error, pulls back, floats again. Handing over the arithmetic ends that.
    """
    # Seating one loose part against another loose part fixes nothing, and a
    # sibling instance of the same part is not what it fastens to.
    floaters = {id(x) for x in boxes if not any(
        t or pen > 0 for t, pen in (_relation(x, o) for o in boxes if o is not x))}
    anchored = [o for o in boxes if id(o) not in floaters]
    hosts = [o for o in anchored if o["id"] != b["id"]]
    if not hosts:
        return ("Nothing in the assembly is anchored for it to sit against — the "
                "placement has come apart. Rebuild the boxes from the ground up: one "
                "part on z=0, everything else referenced to a part already placed.")

    def centre_gap(o):
        return sum(abs((b[lo] + b[ext] / 2) - (o[lo] + o[ext] / 2)) for lo, ext in AXES)

    best = None
    # Rather than reason about which axis can be closed, propose the move and test
    # it: a candidate is only advice worth giving if the moved part actually ends
    # up touching something and inside nothing.
    for o in sorted(hosts, key=centre_gap)[:24]:
        for i, (lo, ext) in enumerate(AXES):
            for new in (o[lo] - b[ext], o[lo] + o[ext], o[lo], o[lo] + o[ext] - b[ext]):
                delta = new - b[lo]
                if abs(delta) < TOL:
                    continue
                moved = {**b, lo: new}
                touches = clear = False
                for other in anchored:
                    t, pen = _relation(moved, other)
                    if pen > 0.06:
                        clear = False
                        break
                    touches = touches or t
                else:
                    clear = touches
                if clear and (best is None or abs(delta) < abs(best[0])):
                    best = (delta, o, lo, new)
    if best is None:
        return ("Nothing in the assembly lines up with it — it is off on its own, not "
                "merely loose. Give it a box_x/box_y/box_z that shares two axes with "
                "the parts it fastens to.")
    delta, o, lo, new = best
    return (f"Set box_{lo}={new:.3f} (a move of {delta:+.2f}in) and it lands flush "
            f"against {o['id']} ({names.get(o['id'], o['id'])}). Flush is contact, not "
            f"overlap — do not push past that face, and do not leave a gap short of it.")


# Words that name hardware rather than a piece of wood. "Dowel" and "biscuit" are
# deliberately absent: they name real joinery members the engine does place.
_HARDWARE = ("screw", "nail", "brad", "staple", "bolt", "washer", "lag ",
             "hinge", "bracket", "anchor", "t-nut", "threaded insert")


def _hardware_parts(geo: Geometry, boxes) -> list[tuple[str, int]]:
    """Parts that are really fasteners: named as hardware and too small to be wood.

    Both tests have to hold. "Screw block" is a wooden part and stays one; a 1-1/4in
    solid named "Pocket screws" is a box of screws that wandered into the cut list.
    """
    counts: dict[str, int] = {}
    sizes: dict[str, float] = {}
    for b in boxes:
        counts[b["id"]] = counts.get(b["id"], 0) + 1
        sizes[b["id"]] = max(sizes.get(b["id"], 0.0), max(b["w"], b["d"], b["h"]))
    out = []
    for p in geo.parts:
        name = p.name.lower()
        if any(w in name for w in _HARDWARE) and sizes.get(p.id, 99.0) <= 6.0:
            out.append((p.id, counts.get(p.id, p.qty)))
    return out


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

    # ---- 0. hardware modelled as joinery ----------------------------------
    # A live run put "Pocket screws 1-1/4 inch" in the cut list with a 3D box and
    # a quantity of 48, and the placement checks below did what they are for: 48
    # instances touching nothing. Chasing that is chasing the wrong thing — the
    # screws are not badly placed, they are not parts. Say so before the geometry
    # checks run, so the repair fixes the category rather than the coordinates.
    hardware = _hardware_parts(geo, boxes)
    if hardware:
        for pid, n in hardware:
            issues.append(
                f"part {pid} ({names.get(pid, pid)}) is hardware, not a part: it "
                f"belongs in `fasteners`, not in `parts`. Remove it from the parts "
                f"list — with its box and its qty of {n} — and add it to fasteners "
                f"as {{fastener_id, seam_expr, spacing}}. The cut list is wood to "
                f"cut; screws are bought by the box and drawn on the joint details.")
        return issues

    # ---- 1. parts escaping the declared envelope --------------------------
    env = envelope(geo)
    if env:
        ex0, ey0, ez0, ex1, ey1, ez1 = env
        slack = max(1.0, 0.03 * max(ex1 - ex0, ey1 - ey0, ez1 - ez0))
        escaped: dict[str, list[str]] = {}
        for b in boxes:
            over, over_axis = [], []
            if b["x"] + b["w"] > ex1 + slack:
                over.append(f"x reaches {b['x'] + b['w']:.1f} but the piece is only {ex1:.1f} wide"); over_axis.append("x")
            if b["x"] < ex0 - slack:
                over.append(f"x starts at {b['x']:.1f}, left of the piece"); over_axis.append("x")
            if b["y"] + b["d"] > ey1 + slack:
                over.append(f"y reaches {b['y'] + b['d']:.1f} but the piece is only {ey1:.1f} deep"); over_axis.append("y")
            if b["z"] + b["h"] > ez1 + slack:
                over.append(f"z reaches {b['z'] + b['h']:.1f} but the piece is only {ez1:.1f} tall"); over_axis.append("z")
            if over:
                escaped.setdefault(b["id"], []).append((over[0], over_axis[0]))
        # Group every instance of a part so the correct step can be worked out from
        # how many there are.
        all_by_id: dict[str, list] = {}
        for b in boxes:
            all_by_id.setdefault(b["id"], []).append(b)
        # Two checks can disagree about which end of this is wrong. A part escapes
        # the envelope; the envelope is also smaller than the size the user asked
        # for. Told to move the part in, the model shrinks the piece; told the piece
        # is too small, it grows the element and the parts escape again. Say which.
        undersized = {
            axis: asked for axis, ext, asked in _asked_dimensions(geo)
            if {"x": ex1 - ex0, "y": ey1 - ey0, "z": ez1 - ez0}[axis] < asked - 1.0}
        for pid, msgs in escaped.items():
            axis = msgs[0][1]
            group = all_by_id.get(pid, [])
            head = (f"part {pid} ({names.get(pid, pid)}) is placed outside the object: "
                    f"{msgs[0][0]}. {len(msgs)} of its {len(group)} instance(s) escape. ")
            if axis in undersized:
                have = {"x": ex1 - ex0, "y": ey1 - ey0, "z": ez1 - ez0}[axis]
                issues.append(
                    head + f"The part is not what is wrong here: the object's own "
                    f"element declares only {have:.1f}in on {axis} when the brief asks "
                    f"for {undersized[axis]:g}in. Fix the ELEMENT first — its "
                    f"{'length' if axis == 'x' else 'width' if axis == 'y' else 'height'}"
                    f"_expr should evaluate to {undersized[axis]:g} — and leave the "
                    f"parts where they are. Shrinking them to fit an undersized "
                    f"envelope builds the wrong piece.")
            else:
                issues.append(head + _step_remedy(group, axis, env))

    # ---- 2. floating instances (touch nothing) ----------------------------
    floating: dict[str, list] = {}
    for i, b in enumerate(boxes):
        rel = [_relation(b, o) for j, o in enumerate(boxes) if i != j]
        if not any(t or pen > 0 for t, pen in rel):
            floating.setdefault(b["id"], []).append(b)
    for pid, group in floating.items():
        issues.append(
            f"part {pid} ({names.get(pid, pid)}) has {len(group)} instance(s) touching "
            f"nothing — it floats free of the assembly. "
            + _flush_remedy(group[0], boxes, names))

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
                # "Split it into bays" only makes sense when the obstacle really
                # divides the part: it must sit inside the span AND block the whole
                # of it on the other two axes. Without that second test a top panel
                # capping two sides reads as a shelf crossing a divider, and the
                # repair loop is sent to split the top in half.
                divides = all(
                    obstacle[o_lo] <= spanner[o_lo] + TOL
                    and obstacle[o_lo] + obstacle[o_ext] >= spanner[o_lo] + spanner[o_ext] - TOL
                    for o_lo, o_ext in AXES if o_lo != lo)
                inside = (obstacle[lo] > spanner[lo] + TOL
                          and obstacle[lo] + obstacle[ext] < spanner[lo] + spanner[ext] - TOL
                          and divides)
                if inside:
                    # A shelf running straight through a centre divider cannot be
                    # cured by shortening it — that empties one bay. It has to
                    # become one piece per bay, so say so with the numbers.
                    bay = obstacle[lo] - spanner[lo]
                    step = obstacle[lo] + obstacle[ext] - spanner[lo]
                    # Two things look identical here and want opposite fixes. A
                    # shelf crossing a centre divider becomes one shelf per bay. A
                    # leg passing through a shelf does not become two legs — the
                    # shelf is notched around it. A live run was told to split a
                    # leg into bays, which is how you get a sofa with eight
                    # half-legs. The geometry cannot tell these apart, so both are
                    # offered and the model, which knows which member is
                    # continuous, chooses.
                    issues.append(
                        f"part {spanner['id']} ({names.get(spanner['id'], spanner['id'])}) "
                        f"runs straight through {obstacle['id']} "
                        f"({names.get(obstacle['id'], obstacle['id'])}), which stands inside "
                        f"its span on {lo}. Do NOT simply shorten it — that leaves one side "
                        f"empty. Either (1) {spanner['id']} is interrupted, and becomes one "
                        f"piece per bay: keep box_{lo}={spanner[lo]:.3f}, set "
                        f"box_{ext}={bay:.3f} (the bay), qty 2 per level and "
                        f"step_{lo}={step:.3f} so the second starts past {obstacle['id']}, "
                        f"adjusting the cut list length to match; or (2) {spanner['id']} runs "
                        f"continuously — a post through a shelf, a rail through a divider — "
                        f"and it is {obstacle['id']} that must give way: notch it by declaring "
                        f"joint_type on {obstacle['id']} with joint_depth_expr of at least "
                        f"{min(spanner[ext], obstacle[ext]):.3f}, or split {obstacle['id']} "
                        f"instead.")
                elif _joint_shaped(a, b, lo, pen):
                    # One board thickness of overlap. Told only to "shorten one of
                    # them", the repair shortens until the part touches nothing,
                    # gets a floating error, pushes it back, and oscillates: there
                    # is no legal position while the audit denies the joint could be
                    # deliberate. Give both ways out and let the model — which knows
                    # whether it meant a tenon there — choose.
                    arriving = _joint_shaped(a, b, lo, pen)
                    host = b if arriving is a else a
                    flush = _butt_remedy(arriving, host, lo, ext, pen)
                    issues.append(
                        f"{arriving['id']} ({names.get(arriving['id'], arriving['id'])}) and "
                        f"{host['id']} ({names.get(host['id'], host['id'])}) overlap by "
                        f"{pen:.2f}in along {lo} — one board thickness, so this is either a "
                        f"joint you have not declared or a part pushed one board too far. "
                        f"Decide which, and do NOT shorten one until it floats free: "
                        f"(1) if they are jointed — on part {arriving['id']} set joint_type to "
                        f"one of tenon, dowel, domino, half_lap or bridle (exactly those "
                        f"words) and joint_depth_expr to at least {pen:.3f}, which tells the "
                        f"cut list and the joint details to expect it; or (2) if they should "
                        f"merely meet — on part {arriving['id']}, {flush}. Meeting means "
                        f"touching, not entering: do not pull it back past the face either, "
                        f"or it will float.")
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

    # ---- 4b. the cut list buys a different number than the drawing shows ---
    # `positions` names an origin per instance, so it can disagree with qty. Six
    # legs bought and four placed is not a placement error the other checks can
    # see: every leg drawn is in the right place, there are just two more on the
    # invoice.
    parts_by_id = {p.id: p for p in geo.parts}
    for pid, group in by_id.items():
        part = parts_by_id.get(pid)
        if part and part.qty != len(group):
            issues.append(
                f"part {pid} ({names.get(pid, pid)}) is bought {part.qty} time(s) but "
                f"placed {len(group)} time(s) — the cut list and the drawings disagree. "
                f"Make qty_expr equal the number of `positions` entries, or drop "
                f"`positions` and let the step repeat qty instances.")

    # ---- 5. solids drawn at the wrong stock thickness ---------------------
    # A part is cut from real stock, so one of its three box dimensions has to BE
    # that stock's thickness (or a multiple of it, for a lamination). A back panel
    # written as `box_d = rabbet_depth` is 3/4in plywood modelled 1/4in thick: the
    # cut list buys one thing and every drawing shows another.
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

    # ---- 6. the piece is not the size that was asked for ------------------
    # An 84in sofa was placed as a 237in row of parts. Every other check passed —
    # nothing escaped its envelope, nothing floated, nothing interpenetrated —
    # because the design was internally consistent about being the wrong object.
    # The release gates cannot see this either: they check provenance, overflow and
    # bounds, not whether the thing matches the brief.
    for axis_lo, ext, asked in _asked_dimensions(geo):
        built = (max(b[axis_lo] + b[ext] for b in boxes)
                 - min(b[axis_lo] for b in boxes))
        slack = max(3.0, 0.12 * asked)          # frames are built deliberately under
        if abs(built - asked) > slack:
            issues.append(
                f"the piece was asked to be {asked:g}in on {axis_lo} and the parts "
                f"lay out to {built:.1f}in — {'far larger' if built > asked else 'far smaller'} "
                f"than the brief. Parts are probably placed side by side rather than "
                f"assembled: every box_{axis_lo} should put its part where it belongs in "
                f"the finished piece, not in a row.")

    # ---- 6. declared size the parts do not add up to -----------------------
    # The height-stack invariant checks declared layers against the declared
    # overall — both numbers can agree while the actual parts build to something
    # else. A shelf ordered 2-1/2in thick whose deck/core/deck stack is 2-1/4in
    # passes every invariant and arrives an eighth of an inch shy on each face.
    declared = _declared_height(geo)
    if declared:
        built = max(b["z"] + b["h"] for b in boxes) - min(b["z"] for b in boxes)
        shortfall = declared - built
        offset = getattr(geo, "per_face_offset", 0.0) or 0.0
        faces = shortfall / offset if offset > 0.01 else (0.0 if abs(shortfall) < 0.02 else 99)
        if abs(faces - round(faces)) > 0.05 or round(faces) not in (0, 1, 2):
            issues.append(
                f"the piece is declared {declared:.3f}in tall but its parts stack to "
                f"{built:.3f}in — a difference of {shortfall:.3f}in, which is not a whole "
                f"number of {offset:.3f}in finish faces. Either the members are sized "
                f"wrong for the height asked for, or the height is not one this stack "
                f"can build. Resize the core members so the stack reaches it.")

    # ---- 7. directed sections that reveal nothing -------------------------
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


def _declared_height(geo: Geometry) -> float | None:
    """The overall height the design claims, from whichever path authored it."""
    for key in ("overall.height", "overall_height"):
        try:
            return float(geo.scalar(key))
        except Exception:  # noqa: BLE001
            continue
    return None


#: Param ids that plainly name an overall dimension, and the axis each governs.
#: Matched whole, so `arm_width` or `plinth_height` never counts as the outside.
_ASKED = {
    "x": ("overall_length", "overall_width", "length", "width"),
    "y": ("overall_depth", "depth"),
    "z": ("overall_height", "height", "total_height"),
}


def _asked_dimensions(geo: Geometry):
    """(axis, extent, value) for each outside dimension the user actually stated."""
    out = []
    for axis, names in _ASKED.items():
        ext = dict(AXES)[axis]
        for name in names:
            field = geo.scalars.get(f"param.{name}")
            if field and field.value and float(field.value) > 0:
                out.append((axis, ext, float(field.value)))
                break                            # first match wins, most specific first
    return out


def _step_remedy(group: list, axis: str, env) -> str:
    """The step that would put every instance inside the piece, as a number.

    A sofa spent six of eight rounds on this one defect — slats, blocks and braces
    marching out past the end — because the message said to check the step without
    ever saying what it should be. Telling the loop the count fixed the span
    invariant in one round; this does the same for repeats."""
    lo, ext = dict(AXES)[axis], dict(AXES)[axis]
    lo = axis
    ext = {"x": "w", "y": "d", "z": "h"}[axis]
    limit = {"x": env[3], "y": env[4], "z": env[5]}[axis]
    inside = {"x": env[0], "y": env[1], "z": env[2]}[axis]
    n = len(group)
    if n < 2:
        return (f"With one instance there is no step to blame: move it inside by "
                f"setting box_{lo} so box_{lo} + box_{ext} stays under {limit:.1f}.")
    first = min(b[lo] for b in group)
    size = max(b[ext] for b in group)
    travel = (limit - size) - first
    if travel <= 0:
        return (f"Even the first instance does not fit: box_{lo}={first:.2f} plus "
                f"box_{ext}={size:.2f} is past {limit:.1f}. Start it inside the piece.")
    step = travel / (n - 1)
    if step < size - 0.02:
        # The arithmetic has an answer here but it is not advice worth taking:
        # spacing them that closely would overlap them. They do not go side by side
        # on this axis at all.
        return (f"{n} instances of a part {size:.2f}in across do not fit along {lo} "
                f"between {first:.2f} and {limit:.1f} — spacing them to fit would "
                f"overlap them. Either they repeat on a different axis (shelves go up "
                f"in z, not across in x), or they do not lie on a line at all: corner "
                f"blocks and legs sit at corners, so drop step_* and give `positions`, "
                f"one [x, y, z] triple per instance.")
    return (f"For {n} instances starting at box_{lo}={first:.2f}, the last one must "
            f"end at {limit:.1f}, so step_{lo} = {step:.3f} — the travel "
            f"({travel:.2f}in) divided by {n - 1} gap(s), NOT the full width of the "
            f"piece. Set step_{lo}={step:.3f} and leave box_{lo} where it is. If these "
            f"are corner blocks or legs, they do not lie on a line at all — drop "
            f"step_* and give `positions`, one [x, y, z] triple per instance.")
