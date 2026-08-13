"""Detail drawings — sections, joint closeups, predrills, board layouts.

Everything here is derived from the part placement the design already carries, so
it works for any object. Three families:

* **Cross-section** — cut a plane through the assembly; every part the plane
  passes through is drawn as a section rectangle with material-appropriate poché
  and a leader label. The cut position is chosen where it reveals the most parts.
* **Joint detail** — contacts between parts are found geometrically (two boxes
  overlapping on two axes and touching on the third). Each distinct contact is
  drawn magnified, in the plane containing the contact normal, with the fastener,
  its pilot hole and countersink dimensioned from the fastener catalog.
* **Board layout** — long stock drawn as a linear cut run with cumulative marks.

No object-specific logic, and no numbers from a language model.
"""

from __future__ import annotations

from ..catalog.materials import get_material
from ..catalog.fasteners import get_fastener, all_fasteners
from ..core.model import Geometry
from ..drawing.primitives import Canvas, fmt_inches
from .model import joint_roles

W = 520.0
MARGIN = 60.0
AXES = {"x": ("x", "w"), "y": ("y", "d"), "z": ("z", "h")}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _mat_of(geo: Geometry, part_id: str):
    for p in geo.parts:
        if p.id == part_id:
            return get_material(p.material_id)
    return None


def _part_of(geo: Geometry, part_id: str):
    for p in geo.parts:
        if p.id == part_id:
            return p
    return None


def _overlap(a0, a1, b0, b1):
    lo, hi = max(a0, b0), min(a1, b1)
    return (lo, hi) if hi - lo > 1e-6 else None


# Leader labels live in a fixed right-hand gutter. Geometry is drawn to the left
# of LABEL_X; label type is sized (and clipped) so it always fits the gutter —
# a label can never run off the canvas (Gate 3 / Lesson 9).
LABEL_X = 306.0
LABEL_MAXW = W - LABEL_X - 10.0


def _fit(labels: list[str], base=9.0, maxw: float | None = None) -> tuple[float, int]:
    """Font size and character cap so the longest label fits the gutter."""
    avail = LABEL_MAXW if maxw is None else maxw
    longest = max((len(s) for s in labels), default=1)
    size = max(6.0, min(base, avail / (longest * 0.6)))
    cap = max(8, int(avail / (size * 0.6)))
    return size, cap


def _clip(s: str, cap: int) -> str:
    return s if len(s) <= cap else s[: max(1, cap - 1)] + "…"


# A section frame is sized to its cut, between these bounds: tall enough for a
# 54in bookcase to read, short enough that the figure and its caption still fit
# on one page.
SEC_MIN_H, SEC_MAX_H = 260.0, 540.0


def _section_label(geo: Geometry, pid: str, items: dict) -> str:
    part = _part_of(geo, pid)
    mat = _mat_of(geo, pid)
    thick = fmt_inches(mat.nominal_thickness) if mat else ""
    return f"{items.get(pid, '?')} · {part.name if part else pid} · {thick}"


def _section_labels(geo: Geometry, pids, items: dict) -> list[str]:
    return [_section_label(geo, p, items) for p in pids]


# --------------------------------------------------------------------------
# cross-section
# --------------------------------------------------------------------------

def best_cut(boxes, axis="x"):
    """Cut position that yields the most informative section.

    Candidates are restricted to the interior of the piece. A plane grazing the
    very back would technically cut the most parts — the back panel plus every
    full-depth panel — but it stacks them all on one another and reads as a solid
    mass. Cutting through the middle instead separates the carcass members, which
    is what a section is for.
    """
    lo_key, ext_key = AXES[axis]
    lo = min(b[lo_key] for b in boxes)
    hi = max(b[lo_key] + b[ext_key] for b in boxes)
    mid = (lo + hi) / 2
    span = hi - lo
    inner_lo, inner_hi = lo + 0.2 * span, hi - 0.2 * span
    cands = [b[lo_key] + b[ext_key] / 2 for b in boxes] + [mid]
    cands = [v for v in cands if inner_lo <= v <= inner_hi] or [mid]
    best, best_score = mid, -1
    for c in sorted(set(round(v, 4) for v in cands)):
        n = sum(1 for b in boxes if b[lo_key] - 1e-6 < c < b[lo_key] + b[ext_key] + 1e-6)
        if n > best_score or (n == best_score and abs(c - mid) < abs(best - mid)):
            best, best_score = c, n
    return best


def cross_section(geo: Geometry, axis: str = "x", cut: float | None = None,
                  tag: str | None = None, why: str = "") -> Canvas | None:
    """Section through the assembly, poché'd by material, with leader labels.

    ``cut`` lets the DESIGNER place the plane (and say why in ``why``); when it is
    None the engine falls back to picking the most informative cut itself."""
    boxes = geo.structure.get("boxes") or []
    if not boxes:
        return None
    if cut is None:
        cut = best_cut(boxes, axis)
    lo_key, ext_key = AXES[axis]
    # the two axes that remain form the section plane; z is always drawn upward
    plane = [a for a in ("x", "y", "z") if a != axis]
    ha, va = plane[0], plane[1]                     # horizontal, vertical
    hit = [b for b in boxes
           if b[lo_key] - 1e-6 < cut < b[lo_key] + b[ext_key] + 1e-6]
    if not hit:
        return None
    hl, hk = AXES[ha]
    vl, vk = AXES[va]
    hmin = min(b[hl] for b in hit); hmax = max(b[hl] + b[hk] for b in hit)
    vmin = min(b[vl] for b in hit); vmax = max(b[vl] + b[vk] for b in hit)
    rw, rh = hmax - hmin, vmax - vmin
    if rw <= 0 or rh <= 0:
        return None

    tag = tag or ("A-A" if axis == "x" else "B-B")
    plane_name = {"x": "looking along the length",
                  "y": "looking along the depth",
                  "z": "looking down"}[axis]

    # Size the frame to the cut rather than forcing every section into one box. A
    # bookcase sliced across its depth is four times taller than it is wide; in a
    # fixed 340-tall frame it shrinks to a sliver and leaves half the page blank.
    # Scale to the width the labels leave free, then let the height follow — capped
    # so the figure still fits a page with its caption.
    from .draw import item_numbers          # same keys as the balloons / cut list
    items = item_numbers(geo)
    label_texts = _section_labels(geo, {b["id"] for b in hit}, items)
    want = max((len(t) for t in label_texts), default=20) * 0.6 * 9.0 + 8
    label_x_pref = min(LABEL_X, max(210.0, W - 10.0 - want))
    avail_w = label_x_pref - MARGIN - 46
    s = min(avail_w / rw, (SEC_MAX_H - 2 * MARGIN - 10) / rh)
    hgt = max(SEC_MIN_H, min(SEC_MAX_H, rh * s + 2 * MARGIN + 10))

    # The tag alone titles the figure; the designer's reason for cutting here rides
    # on the caption line below it, where there is room to read it whole rather
    # than have it clipped to an ellipsis under the stage badge.
    c = Canvas(W, hgt, stage="as_cut", title=f"Section {tag}")

    # Drawing and gutter are laid out first, then the pair is centred as one
    # composition — otherwise a narrow section hugs the left edge and leaves a
    # band of blank paper down the right.
    label_x = min(label_x_pref, max(MARGIN + rw * s + 46.0, 150.0))
    fs, cap = _fit(label_texts, maxw=W - label_x - 10.0)
    text_w = max((len(_clip(t, cap)) for t in label_texts), default=0) * 0.6 * fs
    pad = max(0.0, (W - 10.0 - (label_x + text_w)) / 2)
    label_x += pad
    ox = MARGIN + pad
    oy = hgt - MARGIN - 6                            # baseline; v grows upward

    def sx(v): return ox + (v - hmin) * s
    def sy(v): return oy - (v - vmin) * s

    # Machined joinery reads the same here as in the joint details: a part housed
    # in a dado/rabbet is drawn seated into its housing by the cut depth, and the
    # groove walls are struck in. Housing members draw first so the housed member
    # sits over them.
    joinery = geo.structure.get("joinery", {})
    hit_ids = {b["id"] for b in hit}
    seats: dict[str, list] = {}
    if joinery:
        for ct in find_contacts(geo):
            ha_id, hb_id = ct["a"]["id"], ct["b"]["id"]
            if ha_id not in hit_ids or hb_id not in hit_ids:
                continue
            hid, housed_id = joint_roles(joinery, ha_id, hb_id)
            if not hid:
                continue
            seats.setdefault(housed_id, []).append(
                {"at": ct["at"], "axis": ct["axis"],
                 "depth": joinery[ha_id if ha_id in joinery else hb_id]["depth"]})

    seen = {}
    # housing members draw first so the member seated into them sits over the top
    order = sorted(hit, key=lambda b: (b["id"] in seats, b[vl], b[hl]))
    for b in order:
        lo_h, hi_h = b[hl], b[hl] + b[hk]
        lo_v, hi_v = b[vl], b[vl] + b[vk]
        seated = 0.0
        for st in seats.get(b["id"], []):
            # extend the housed part into its groove along whichever in-plane
            # axis the joint's contact normal runs
            if st["axis"] == va:
                seated = st["depth"]
                if (b[vl] + b[vk] / 2) > st["at"]:
                    lo_v -= seated
                else:
                    hi_v += seated
            elif st["axis"] == ha:
                seated = st["depth"]
                if (b[hl] + b[hk] / 2) > st["at"]:
                    lo_h -= seated
                else:
                    hi_h += seated
        x0, y0 = sx(lo_h), sy(hi_v)
        bw, bh = (hi_h - lo_h) * s, (hi_v - lo_v) * s
        mat = _mat_of(geo, b["id"])
        cat = mat.category if mat else "sheet_good"
        c.rect(x0, y0, bw, bh, fill="#f4f0e6", sw=1.4)
        c.material_hatch(x0, y0, bw, bh, cat)
        if seated > 0:                       # strike the groove walls
            c.line(x0, y0, x0 + bw, y0, 1.0, color="#3a352c")
            c.line(x0, y0 + bh, x0 + bw, y0 + bh, 1.0, color="#3a352c")
        seen.setdefault(b["id"], (x0 + bw / 2, y0 + bh / 2, b))

    # Leader labels in the right gutter. Sorted by the vertical position of their
    # TARGET, so leaders never cross each other, and evenly spaced so they never
    # collide with one another.
    ids = sorted(seen.items(), key=lambda kv: kv[1][1])
    texts = [_section_label(geo, pid, items) for pid, _ in ids]
    top, bot = MARGIN + 4, hgt - MARGIN + 4
    stepn = max(1, len(ids))
    for i, ((pid, (px, py, b)), txt) in enumerate(zip(ids, texts)):
        ly = top + (bot - top) * (i + 0.5) / stepn
        c.elbow_leader(px, py, label_x, ly, _clip(txt, cap), side="right", size=fs)
    # overall section dimensions + where the plane cuts (inside the drawing, so it
    # sits under Gate 3's bounds check rather than in scanned caption prose)
    c.dim_horizontal(sx(hmin), sx(hmax), oy + 20, fmt_inches(rw))
    caption = f"cut {fmt_inches(cut)} along {axis}"
    if why:
        caption += f" · {why}"
    elif plane_name:
        caption += f" · {plane_name}"
    # The designer's reason moved here so it could read whole rather than clip under
    # the stage badge — but nothing bounded it, and a long one ran off the canvas.
    # Gate 3 caught it on a live build. Step the type down to fit, then clip.
    avail = W - MARGIN - 10
    size = 8.5
    if len(caption) * size * 0.6 > avail:
        size = max(6.5, avail / (len(caption) * 0.6))
    cap_chars = max(8, int(avail / (size * 0.6)))
    c.text(MARGIN, MARGIN - 16, _clip(caption, cap_chars), size=size,
           anchor="start", color="#a4632e")
    return c


# --------------------------------------------------------------------------
# contacts and joint details
# --------------------------------------------------------------------------

def find_contacts(geo: Geometry, tol: float = 0.06) -> list[dict]:
    """Distinct part-to-part contacts: overlap on two axes, touching on the third."""
    boxes = geo.structure.get("boxes") or []
    out: dict[tuple, dict] = {}
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a["id"] == b["id"]:
                continue
            for axis in ("x", "y", "z"):
                lo, ext = AXES[axis]
                a0, a1 = a[lo], a[lo] + a[ext]
                b0, b1 = b[lo], b[lo] + b[ext]
                touching = abs(a1 - b0) <= tol or abs(b1 - a0) <= tol
                if not touching:
                    continue
                others = [ax for ax in ("x", "y", "z") if ax != axis]
                ov = []
                for ax in others:
                    l2, e2 = AXES[ax]
                    o = _overlap(a[l2], a[l2] + a[e2], b[l2], b[l2] + b[e2])
                    if not o:
                        break
                    ov.append((ax, o))
                if len(ov) != 2:
                    continue
                key = tuple(sorted((a["id"], b["id"]))) + (axis,)
                if key in out:
                    continue
                out[key] = {"a": a, "b": b, "axis": axis,
                            "at": (a1 if abs(a1 - b0) <= tol else a0),
                            "overlap": dict(ov)}
    # Collapse structurally identical joints (e.g. left and right side panels to
    # the same back) into one representative marked "typical of N" — a shop drawing
    # details a joint once, not once per mirror image.
    def area(rec):
        (ax1, o1), (ax2, o2) = list(rec["overlap"].items())
        return (o1[1] - o1[0]) * (o2[1] - o2[0])

    grouped: dict[tuple, dict] = {}
    for rec in sorted(out.values(), key=area, reverse=True):
        ma = _mat_of(geo, rec["a"]["id"])
        mb = _mat_of(geo, rec["b"]["id"])
        pa, pb = _part_of(geo, rec["a"]["id"]), _part_of(geo, rec["b"]["id"])
        lo, ext = AXES[rec["axis"]]
        key = (
            tuple(sorted([ma.id if ma else "", mb.id if mb else ""])),
            rec["axis"],
            round(rec["a"][ext], 3), round(rec["b"][ext], 3),
            tuple(sorted([(pa.joint if pa else ""), (pb.joint if pb else "")])),
        )
        if key in grouped:
            grouped[key]["count"] += 1
        else:
            grouped[key] = {**rec, "count": 1}
    return sorted(grouped.values(), key=area, reverse=True)


def pick_fastener(through_t: float, into_cat: str):
    """Deterministic fastener choice: catalog entry legal for the substrate whose
    length best reaches ~2x the thickness it passes through."""
    target = max(1.0, through_t * 2.4)
    best, best_d = None, 1e9
    for f in all_fasteners():
        if into_cat in f.substrate_forbidden:
            continue
        if into_cat not in f.substrate_ok:
            continue
        d = abs(f.length - target)
        if d < best_d:
            best, best_d = f, d
    return best


def joint_detail(geo: Geometry, contact: dict, tag: str) -> Canvas | None:
    """Magnified section through one joint, with fastener, pilot and countersink."""
    a, b, axis = contact["a"], contact["b"], contact["axis"]
    # Section PERPENDICULAR to the seam: the seam runs along the larger overlap
    # axis, so the cut plane holds the contact normal and the SMALLER overlap axis.
    # That is what makes a corner/dado read as an L instead of one merged block.
    others = sorted(contact["overlap"].items(), key=lambda kv: kv[1][1] - kv[1][0])
    ha = others[0][0]                       # in-plane horizontal (across the seam)
    va = axis                               # contact normal drawn vertically
    hl, hk = AXES[ha]
    vl, vk = AXES[va]

    def _window(lo_key, ext_key, centre, cap):
        lo = min(a[lo_key], b[lo_key])
        hi = max(a[lo_key] + a[ext_key], b[lo_key] + b[ext_key])
        if hi - lo > cap:                   # crop around the joint, keep context
            lo, hi = centre - cap / 2, centre + cap / 2
        pad = (hi - lo) * 0.12
        return lo - pad, hi + pad

    ov = contact["overlap"][ha]
    cmid = (ov[0] + ov[1]) / 2
    hmin, hmax = _window(hl, hk, cmid, 7.0)
    at = contact["at"]
    vmin, vmax = _window(vl, vk, at, 4.5)

    hgt = 260.0
    typ = f" · typical of {contact['count']}" if contact.get("count", 1) > 1 else ""
    from .draw import item_numbers                # never expose raw part ids
    _it = item_numbers(geo)
    c = Canvas(W, hgt, stage="as_cut",
               title=f"Detail {tag} — item {_it.get(a['id'], a['id'])} to "
                     f"item {_it.get(b['id'], b['id'])}, magnified{typ}")
    # Each drawn member gets a thickness dimension in a column to its left, and the
    # label hangs further left still, right-anchored. Size that gutter from the
    # actual labels: a constant tuned for 3/4" put 1-1/2" off the canvas, and Gate 3
    # held real builds back for it.
    from ..drawing.primitives import FONT
    thick_labels = [fmt_inches(m.nominal_thickness)
                    for m in (_mat_of(geo, a["id"]), _mat_of(geo, b["id"])) if m]
    widest = max((len(t) for t in thick_labels), default=4) * FONT * 0.6
    dim_gutter = max(68.0, widest + 26.0 + 14.0)   # label + second column + air
    s = min((LABEL_X - dim_gutter - 24) / (hmax - hmin), (hgt - 2 * MARGIN) / (vmax - vmin))
    ox, oy = dim_gutter, hgt - MARGIN

    def sx(v): return ox + (v - hmin) * s
    def sy(v): return oy - (v - vmin) * s

    # Machined joinery: if one member is housing the other (dado / groove /
    # rabbet), cut the real profile instead of drawing a butt contact. The housed
    # member is shown seated in it by the housing depth.
    joinery = geo.structure.get("joinery", {})
    housing_id, housed_id = joint_roles(joinery, a["id"], b["id"])
    declarer = a["id"] if a["id"] in joinery else b["id"] if b["id"] in joinery else None
    housing = joinery.get(declarer) if housing_id else None
    dado_w = 0.0
    if housing:
        other = a if a["id"] == housed_id else b
        dado_w = other[hk]

    housed = a if (housed_id and a["id"] == housed_id) else b
    depth_in = housing["depth"] if housing else 0.0

    parts_drawn = []
    for box in (a, b):
        mat = _mat_of(geo, box["id"])
        cat = mat.category if mat else "sheet_good"
        lo_v, hi_v = box[vl], box[vl] + box[vk]
        if housing and box["id"] == housed["id"] and depth_in > 0:
            # seat the housed member into the groove by the housing depth
            if (box[vl] + box[vk] / 2) > at:
                lo_v -= depth_in
            else:
                hi_v += depth_in
        x0 = sx(max(box[hl], hmin))
        x1 = sx(min(box[hl] + box[hk], hmax))
        y1 = sy(max(lo_v, vmin))
        y0 = sy(min(hi_v, vmax))
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            continue
        if housing and box["id"] == housing_id and dado_w > 0:
            # cut the real housing profile into the section
            nx0 = sx(max(hmin, housed[hl]))
            nx1 = sx(min(hmax, housed[hl] + housed[hk]))
            from_top = (box[vl] + box[vk] / 2) < at    # housing lies below the seam
            c.notched_rect(x0, y0, x1 - x0, y1 - y0, nx0, nx1,
                           depth_in * s, from_top=from_top)
        else:
            c.rect(x0, y0, x1 - x0, y1 - y0, fill="#f4f0e6", sw=1.1)
        c.material_hatch(x0, y0, x1 - x0, y1 - y0, cat)
        parts_drawn.append((box, x0, y0, x1 - x0, y1 - y0, mat))

    if not parts_drawn:
        return None

    # Fastener rule: you drive through the member that is THINNER across the seam
    # into the one behind it — head on the outer face, tip buried in the other.
    through = min(parts_drawn, key=lambda t: t[0][vk])
    into = [t for t in parts_drawn if t[0]["id"] != through[0]["id"]]
    into = into[0] if into else through
    through_t = through[0][vk]
    fast = pick_fastener(through_t, (into[5].category if into[5] else "sheet_good"))

    seam_y = sy(at)
    c.line(sx(hmin), seam_y, sx(hmax), seam_y, 1.2, color="#3a352c")

    if fast:
        fx = sx(cmid)
        head_out = 1 if (through[0][vl] + through[0][vk] / 2) > at else -1
        head_y = sy(at + head_out * through_t)
        tip_y = sy(at - head_out * min(fast.length - through_t, 1.6))
        # shank + pilot hole (dashed) + countersink cone
        c.line(fx, head_y, fx, tip_y, 1.6, color="#7a3f22")
        c.line(fx, seam_y, fx, tip_y, 0.7, dash="3 2", color="#a4632e")
        cs = max(3.0, (fast.countersink_diameter or 0.3) * s)
        c.polygon([(fx - cs / 2, head_y), (fx + cs / 2, head_y), (fx, head_y + head_out * -cs * 0.7)],
                  fill="#7a3f22", sw=0.6)
        c.centerline(fx, head_y - head_out * 12, fx, tip_y + head_out * 12)
        pilot = (f"pilot {_frac(fast.pilot_diameter)}" if fast.pilot_diameter
                 else "no pilot (self-drilling)")
        rows = [(fx, (head_y + tip_y) / 2, fast.display_name),
                (fx, sy(at - head_out * 0.4), pilot)]
        if fast.countersink_diameter:
            rows.append((fx, head_y, f"countersink {_frac(fast.countersink_diameter)}"))
        rows.append((sx(cmid + (hmax - hmin) * 0.16), seam_y, f"drive: {fast.driver_bit}"))
        fs, cap = _fit([r[2] for r in rows], base=8.5)
        for i, (px, py, txt) in enumerate(rows):
            c.elbow_leader(px, py, LABEL_X, MARGIN + 16 + i * 20,
                           _clip(txt, cap), side="right", size=fs)

    # part tags + nominal thickness (what the builder buys; actual is in the BOM)
    for i, (box, x0, y0, bw, bh, mat) in enumerate(parts_drawn):
        c.text(x0 + bw / 2, y0 + bh / 2 + 3, str(_it.get(box["id"], box["id"])), size=11, weight="bold")
        # The thickness dimensions stack leftward, one column per part. A part
        # drawn hard against the left margin pushed its column off the canvas, so
        # the stack is clamped to stay on the page.
        if mat and bh > 6:
            # never left of the gutter the labels were sized to fit
            dim_x = max(dim_gutter - 26.0 * (len(parts_drawn) - 1 - i),
                        x0 - 10 - i * 26)
            c.dim_vertical(y0, y0 + bh, dim_x,
                           fmt_inches(mat.nominal_thickness))
    if housing:
        c.elbow_leader(sx(cmid), sy(at - (0.5 if (housed[vl] + housed[vk] / 2) > at else -0.5)),
                       LABEL_X, hgt - MARGIN + 6,
                       f"{housing['type']} {_frac(housing['depth'])} deep", side="right",
                       size=8.5)
    # The note belongs to a PART, not to this seam — the same shelf turns up in
    # several details, and an unattributed line reads as if it described whichever
    # joint it sits under. Name whose note it is.
    part_a = _part_of(geo, a["id"])
    if part_a and part_a.joint:
        c.text(MARGIN, hgt - 14, _clip(f"{part_a.name}: {part_a.joint}", 82),
               size=9, anchor="start", color="#6a655b")
    return c


def _frac(v: float) -> str:
    return fmt_inches(v) if v else "—"


# --------------------------------------------------------------------------
# predrill / fastener schedule diagram
# --------------------------------------------------------------------------

def predrill_chart(geo: Geometry) -> Canvas | None:
    """Every fastener the design uses, drawn to relative scale with its bits."""
    used: list = []
    for contact in find_contacts(geo)[:8]:
        a = contact["a"]
        mat = _mat_of(geo, a["id"])
        f = pick_fastener(a[AXES[contact["axis"]][1]], mat.category if mat else "sheet_good")
        if f and f.id not in [u.id for u in used]:
            used.append(f)
    if not used:
        return None
    sched = {str(f.get("fastener_id")): f.get("spacing") for f in geo.structure.get("fasteners", [])}
    row_h = 74.0
    c = Canvas(W, 40 + row_h * len(used), stage="as_assembled",
               title="Pilot holes, countersinks and drivers")
    y = 42.0
    for f in used:
        spacing = sched.get(f.id)
        spacing = float(spacing) if isinstance(spacing, (int, float)) else None
        c.text(14, y - 8, f.display_name, size=10, anchor="start", weight="bold")
        # screw profile drawn to scale (1in = 46px)
        sc = 46.0
        x0 = 200.0
        tip = x0 + f.length * sc
        c.line(x0, y, tip, y, 2.2, color="#7a3f22")          # shank
        c.line(x0, y - 5.5, x0, y + 5.5, 2.4, color="#7a3f22")  # head, left
        c.polygon([(tip - 8, y - 4), (tip - 8, y + 4), (tip, y)],
                  fill="#7a3f22", sw=0.6)                    # point, right
        c.dim_horizontal(x0, x0 + f.length * sc, y + 18, fmt_inches(f.length))
        bits = []
        if f.pilot_diameter:
            bits.append(f"pilot {_frac(f.pilot_diameter)}")
        if f.countersink_diameter:
            bits.append(f"c'sink {_frac(f.countersink_diameter)}")
        bits.append(f.driver_bit)
        if spacing:
            bits.append(f"{fmt_inches(spacing)} o.c.")
        c.text(14, y + 8, " · ".join(bits), size=8.5, anchor="start", color="#6a655b")
        # spacing run: marks along a seam at the specified interval
        if spacing:
            rx, rw = 200.0, W - 240.0
            ry = y + 30
            c.line(rx, ry, rx + rw, ry, 0.9, color="#3a352c")
            step = max(14.0, min(46.0, rw / 8))
            n = int(rw // step)
            for k in range(n + 1):
                mx = rx + k * step
                c.line(mx, ry - 4, mx, ry + 4, 0.8, color="#7a3f22")
            if n >= 1:
                c.dim_horizontal(rx, rx + step, ry + 16, fmt_inches(spacing))
        y += row_h
    return c


# --------------------------------------------------------------------------
# linear board layout (lumber / long stock)
# --------------------------------------------------------------------------

def board_layout(nest, sheet_index: int) -> Canvas:
    """Long stock as a linear cut run with cumulative cut marks."""
    sheet = nest.sheets[sheet_index - 1]
    length = max(sheet.sheet_w, sheet.sheet_h)
    rows = sorted(sheet.placements, key=lambda p: (p.y, p.x))
    hgt = 60.0 + 46.0 * max(1, len(rows))
    c = Canvas(W, hgt, stage="as_cut",
               title=f"{nest.material_id} — board {sheet_index}, "
                     f"{fmt_inches(length)} stock")
    s = (W - 2 * 30.0) / length
    y = 46.0
    for p in rows:
        run = max(p.w, p.h)
        c.rect(30.0, y, length * s, 20.0, fill="#fbfaf7", sw=1.0)
        c.rect(30.0, y, run * s, 20.0, fill="#eae4d7", sw=1.0)
        pid = p.part_id.rstrip("0123456789")
        c.text(30.0 + run * s / 2, y + 14, pid, size=9, weight="bold")
        c.dim_horizontal(30.0, 30.0 + run * s, y + 34, fmt_inches(run))
        if run < length - 0.5:
            c.text(30.0 + (run + (length - run) / 2) * s, y + 14,
                   f"offcut {fmt_inches(length - run)}", size=7.5, color="#a29b8f")
        y += 46.0
    return c


# --------------------------------------------------------------------------

def detail_drawings(geo: Geometry, max_joints: int = 3) -> dict:
    """Section + the most significant joint details + the predrill chart."""
    out: dict[str, Canvas] = {}
    directed = geo.structure.get("sections") or []
    if directed:
        # the designer said where to look and why
        for i, spec in enumerate(directed[:3], 1):
            sec = cross_section(geo, spec.get("axis", "x"), cut=spec.get("at"),
                                tag=spec.get("tag") or f"S{i}", why=spec.get("why", ""))
            if sec:
                out[f"section_{i}"] = sec
    else:
        sec = cross_section(geo, "x")
        if sec:
            out["section_aa"] = sec
        sec2 = cross_section(geo, "y")
        if sec2:
            out["section_bb"] = sec2
    for i, contact in enumerate(find_contacts(geo)[:max_joints], 1):
        d = joint_detail(geo, contact, f"D{i}")
        if d:
            out[f"joint_d{i}"] = d
    pc = predrill_chart(geo)
    if pc:
        out["predrill"] = pc
    return out
