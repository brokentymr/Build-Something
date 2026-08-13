"""Generic build packet — reference-grade, for ANY object.

Assembles the editorial packet from three sources: verified numbers (engine),
hero drawings projected from 3D part placement (engine), and the instructional
content authored by the design agent (title, callouts, tolerances, phased steps,
cure, care). Reuses the shared document design system and the release gates.
"""

from __future__ import annotations

import re

from ..core.model import Geometry
from ..nesting.plan import NestingPlan
from ..drawing.primitives import Canvas, fmt_inches
from ..drawing.drawings import nesting_diagram
from ..document.content import Block, _table, _h, _e, _callout
from ..parts.joinery import tool_schedule
from . import draw as gdraw
from . import detail as gdetail


def _svg(c: Canvas) -> str:
    return f'<div class="fig">{c.render()}<div class="figcap">{_e(c.title)} '\
           f'<span class="stage">[{c.stage.replace("_", " ")}]</span></div></div>'


def _split_notes(notes) -> list[str]:
    """Explode semicolon-joined note blobs into individual lines."""
    out: list[str] = []
    for n in notes:
        for piece in str(n).split(";"):
            piece = piece.strip().rstrip(".")
            if len(piece) <= 3:
                continue
            # a clause that opens lowercase is the tail of the previous thought,
            # not a note of its own — rejoin it rather than orphan it
            if out and piece[:1].islower():
                out[-1] = out[-1] + "; " + piece
            else:
                out.append(piece)
    return out


def _split_sentences(text: str) -> list[str]:
    """One instruction per line, without breaking on decimals or abbreviations."""
    parts = re.split(r"(?<=[a-z0-9\)\"])\.\s+(?=[A-Z])", str(text).strip())
    return [p.strip().rstrip(".") for p in parts if len(p.strip()) > 3]


def _human(text: str, geo: Geometry) -> str:
    """Replace internal part ids in agent prose with the part's real name.

    The agent names parts with symbols like ``back_panel_part``; those belong in
    the model, not on a page someone reads in a workshop."""
    # Short ids leak too: "Dado depth in S1 and S2" is a model note, not a workshop
    # instruction. Match whole tokens only, and only ids distinctive enough that a
    # word boundary makes the match safe — never a bare "A" or "C".
    for p in sorted(geo.parts, key=lambda p: -len(p.id)):
        if not p.id:
            continue
        distinctive = ("_" in p.id or len(p.id) > 3
                       or any(ch.isdigit() for ch in p.id)
                       or (len(p.id) >= 2 and p.id.isupper()))   # prose is sentence case
        if distinctive and re.search(rf"\b{re.escape(p.id)}\b", text):
            text = re.sub(rf"\b{re.escape(p.id)}\b", p.name.lower(), text)
    if geo.finish_id and geo.finish_id in text:
        text = text.replace(geo.finish_id, _finish_name(geo).lower())
    # material ids leak the same way: "3/4" birch plywood (ply_075_birch)"
    from ..catalog.materials import get_material
    for mid in sorted({p.material_id for p in geo.parts}, key=len, reverse=True):
        if mid and mid in text:
            try:
                text = text.replace(mid, get_material(mid).display_name)
            except Exception:  # noqa: BLE001 — unknown id stays as written
                pass
    # param ids leak the same way — "seat_height" reached a sofa's page
    for key in sorted((k[6:] for k in geo.scalars if k.startswith("param.")),
                      key=len, reverse=True):
        if "_" in key and re.search(rf"\b{re.escape(key)}\b", text):
            text = re.sub(rf"\b{re.escape(key)}\b", key.replace("_", " "), text)
    text = re.sub(r"\s*\(\s*\)", "", text)          # an emptied parenthetical
    # The agent writes "BACK panel", and the name it stands for is already
    # "Back panel" — substituting leaves "back panel panel". Collapse the stutter,
    # then the longer form of it: "side panels S1 and S2" becomes "side panels left
    # side panel and right side panel", which is correct and unreadable.
    text = _dedupe_words(text)
    return _collapse_lead_in(text, [p.name.lower() for p in geo.parts])


def _dedupe_words(text: str) -> str:
    """Drop an immediately repeated word ("panel panel" -> "panel")."""
    return re.sub(r"\b(\w+)(\s+\1)\b(?!\w)", r"\1", text, flags=re.IGNORECASE)


def _collapse_lead_in(text: str, names: list[str]) -> str:
    """Drop a lead-in phrase the substituted name already says.

    "in side panels left side panel" -> "in left side panel": the words before the
    name are, singularised, a tail of the name itself."""
    for name in sorted(set(n for n in names if n), key=len, reverse=True):
        pattern = re.compile(r"((?:\w+\s+){1,3})" + re.escape(name), re.IGNORECASE)

        def repl(m, name=name):
            lead = m.group(1).split()
            for k in range(len(lead), 0, -1):
                candidate = " ".join(lead[-k:])
                singular = re.sub(r"s\b", "", candidate, flags=re.IGNORECASE)
                if singular and name.endswith(singular.lower()):
                    kept = " ".join(lead[:-k])
                    return (kept + " " if kept else "") + name
            return m.group(0)

        text = pattern.sub(repl, text)
    return text


def _stock_diagram(geo: Geometry, nest, mid: str, i: int) -> Canvas:
    """Sheet nesting for panels; a linear cut run for long board stock."""
    from ..catalog.materials import get_material
    mat = get_material(mid)
    long_stock = mat.category in ("lumber", "hardwood") or \
        max(nest.sheet_w, nest.sheet_h) > 3.2 * min(nest.sheet_w, nest.sheet_h)
    if long_stock:
        return gdetail.board_layout(nest, i)
    items = {k: str(v) for k, v in gdraw.item_numbers(geo).items()}
    return nesting_diagram(nest, i, labels=items, material_name=mat.display_name)


def generic_drawings(geo: Geometry, plan: NestingPlan) -> dict:
    d = dict(gdraw.hero_drawings(geo))
    d.update(gdetail.detail_drawings(geo))
    for mid, nest in plan.nests.items():
        for i in range(1, nest.sheet_count() + 1):
            d[f"nest_{mid}_{i}"] = _stock_diagram(geo, nest, mid, i)
    return d


def build_blocks_generic(geo: Geometry, plan: NestingPlan, packet: dict | None = None) -> list[Block]:
    from ..catalog.materials import get_material
    packet = packet or {}
    hero = gdraw.hero_drawings(geo)
    blocks: list[Block] = []

    def B(bid, kind, html):
        blocks.append(Block(bid, kind, html))

    kind = geo.structure.get("node_kind", geo.node).replace("_", " ")
    title = packet.get("title") or geo.inputs.get("name", kind.title())
    subtitle = packet.get("subtitle") or geo.structure.get("summary", "")
    meta = packet.get("spec_meta", {})

    # ---------- COVER ----------
    B("cover", "cover", _cover(geo, plan, hero, kind, title, subtitle, meta, packet))

    # ---------- design notes / warnings ----------
    # One note per line. Joining them into a paragraph produced a wall of
    # semicolons nobody reads on a shop floor.
    warnings = _split_notes(geo.structure.get("warnings", []))
    if warnings:
        # A note the loop could not resolve outranks any design commentary — and
        # being appended last, it was the first thing an 8-note cap threw away.
        unresolved = [w for w in warnings if w.lower().startswith("unresolved")]
        rest = [w for w in warnings if w not in unresolved]
        items = "".join(f"<li>{_e(_human(w, geo))}</li>"
                        for w in (unresolved + rest)[:8])
        B("warn", "prose", '<div class="notice"><span class="ct">Design notes</span>'
          f'<ul class="tight">{items}</ul></div>')

    # ---------- DESIGN SPECIFICATION (governing dims + hero views) ----------
    B("h_spec", "header", _h("Design specification", "finished dimensions"))
    if packet.get("governing_note"):
        B("govnote", "prose", f'<div class="agent-note"><p>{_e(_human(packet["governing_note"], geo))}</p></div>')
    B("spec", "table", _param_table(geo))
    # A curated node derives a spec of its own — deck sizes, ring width, rib count,
    # the two plinth heights — that the generic parameter table has no slot for.
    for i, extra in enumerate(packet.get("extra_sections") or []):
        if extra.get("where") == "spec" and extra.get("html"):
            B(f"s_h{i}", "header", _h(extra.get("title", ""), extra.get("kicker", "")))
            B(f"s_b{i}", extra.get("kind", "table"), extra["html"])
    for k in ("plan", "front_elevation", "side_elevation"):
        if k in hero:
            B(f"fig_{k}", "figure", _svg(hero[k]))

    # ---------- CRITICAL CONCEPT callouts ----------
    callouts = packet.get("callouts") or []
    if callouts:
        B("h_crit", "header", _h("Before you cut", "read this first"))
        kinds = {"crit": "warn", "warn": "warn", "info": "info"}
        cells = "".join(_callout(_human(c.get("title", ""), geo), _e(_human(c.get("body", ""), geo)),
                                 kinds.get(c.get("kind", "info"), "info")) for c in callouts[:3])
        B("crit", "prose", f'<div class="callouts" style="border:none;padding-top:0">{cells}</div>')

    # ---------- SECTIONS + JOINT DETAILS + PREDRILLS ----------
    details = gdetail.detail_drawings(geo)
    sections = [k for k in details if k.startswith("section_")]
    if sections:
        B("h_sect", "header", _h("Assembly sections", "how it stacks up"))
        for k in sections:
            B(f"fig_{k}", "figure", _svg(details[k]))
    joints = [k for k in details if k.startswith("joint_")]
    if joints:
        B("h_joint", "header", _h("Joint details", "magnified · with fixings"))
        for k in joints:
            B(f"fig_{k}", "figure", _svg(details[k]))
    if "predrill" in details:
        B("h_pre", "header", _h("Pilot holes and drivers", "drill before you drive"))
        B("fig_predrill", "figure", _svg(details["predrill"]))

    # ---------- BILL OF MATERIALS ----------
    B("h_bom", "header", _h("Bill of materials"))
    bom = []
    for mid, n in plan.nests.items():
        m = get_material(mid)
        st = m.stock_sizes[0]
        bom.append([m.display_name, f"{n.sheet_count()} @ {fmt_inches(st.w)}&times;{fmt_inches(st.h)}",
                    _e(m.category.replace("_", " "))])
    B("bom", "table", _table(["Material", "Quantity", "Category"], bom))

    # ---------- TOOL SCHEDULE ----------
    ops = geo.structure.get("operations", set())
    if ops:
        try:
            ts = [[t.tool, t.setting, t.justified_by.replace("_", " ")] for t in tool_schedule(ops)]
            B("h_tool", "header", _h("Tool and bit schedule"))
            B("tool", "table", _table(["Tool / bit", "Setting", "For operation"], ts))
        except Exception:  # noqa: BLE001
            pass

    # ---------- CUT LIST ----------
    B("h_cut", "header", _h("Cut list", "quoted as-cut · item nos. match the balloons"))
    items = gdraw.item_numbers(geo)
    # Quoted to 1/32 — the tolerance budget is +/- 1/32 and nobody can cut 61/64.
    from ..core.glueup import glue_up
    cut = []
    for p in geo.parts:
        gl = glue_up(p)
        # An edge-glued panel is one row, but the shop cuts strips — say both, or
        # the builder walks to the saw with a width no board can give.
        note = _human(p.joint, geo)
        if gl.is_glued:
            note = f"{gl.describe()}, trim to size" + (f"; {note}" if note else "")
        cut.append([str(items.get(p.id, "")), _e(p.name),
                    f'<span class="nowrap">{fmt_inches(p.cut_wh()[0], 32)} &times; '
                    f'{fmt_inches(p.cut_wh()[1], 32)}</span>',
                    str(p.qty), _e(get_material(p.material_id).display_name),
                    f'<span class="agent-note">{_e(note)}</span>'])
    B("cut", "table", _table(["Item", "Part", "As-cut", "Qty", "Material", "Joint"], cut))

    # ---------- SHEET LAYOUTS ----------
    B("h_sheet", "header", _h("Stock layouts, yield and waste"))
    for mid, nest in plan.nests.items():
        for i in range(1, nest.sheet_count() + 1):
            B(f"nest_{mid}_{i}", "figure", _svg(_stock_diagram(geo, nest, mid, i)))

    # ---------- TOLERANCE BUDGET ----------
    tol = packet.get("tolerances") or []
    if tol:
        B("h_tol", "header", _h("Tolerance budget"))
        B("tol", "table", '<div class="agent-note">'+_table(["Check", "Tolerance"], [[_e(_human(t.get("check", ""), geo)), _e(t.get("tolerance", ""))] for t in tol])+'</div>')

    # ---------- BUILD SEQUENCE ----------
    steps = packet.get("steps") or []
    if steps:
        B("h_seq", "header", _h("Build sequence", f"{len(steps)} steps"))
        for i, st in enumerate(steps, 1):
            B(f"step_{i}", "step", _step(i, st, geo))

    # ---------- CURE SCHEDULE ----------
    # ---------- node-specific sections ----------
    # A curated node knows things about its own build that no generic schema has a
    # slot for — why the plinth reads two heights, what to check at final QC. They
    # ride here rather than justifying a second document pipeline.
    for i, extra in enumerate(packet.get("extra_sections") or []):
        if not extra.get("html") or extra.get("where") == "spec":
            continue                       # already placed with the specification
        B(f"x_h{i}", "header", _h(extra.get("title", ""), extra.get("kicker", "")))
        B(f"x_b{i}", extra.get("kind", "prose"), extra["html"])

    cure = packet.get("cure") or []
    if cure:
        B("h_cure", "header", _h("Cure schedule", "mostly waiting"))
        B("cure", "table", '<div class="agent-note">'+_table(["Stage", "Wait", "Note"], [[_e(c.get("stage", "")), _e(c.get("wait", "")), _e(_human(c.get("note", ""), geo))] for c in cure])+'</div>')

    # ---------- CARE ----------
    if packet.get("care"):
        B("h_care", "header", _h("Care and maintenance"))
        # Care arrives as one long paragraph; a wall of semicolons is not something
        # anyone reads standing in a workshop. One line per instruction.
        care = [_e(x) for x in _split_sentences(_human(packet["care"], geo))]
        B("care", "prose", '<div class="agent-note"><ul class="tight">'
          + "".join(f"<li>{x}</li>" for x in care) + "</ul></div>")

    # ---------- DESIGN RECORD ----------
    B("h_rec", "header", _h("Design record", "inputs that generated this packet"))
    rec = [[_e(p.label), fmt_inches(p.value) if p.unit == "in" else f"{p.value:g} {p.unit}",
            _e(p.source)] for p in _param_list(geo)]
    B("rec", "table", _table(["Parameter", "Value", "Source"], rec))

    return blocks


# --------------------------------------------------------------------------

def overall_dims(geo: Geometry) -> tuple[float, float, float] | None:
    """The finished outside dimensions — what a buyer measures.

    Not the bounding box of the placement: those boxes are carcass, and a coated
    piece finishes proud of its substrate. A coffee table whose carcass stacks to
    15-5/8in is a 16in table, and quoting the box height put a number on the cover
    that traces to no solver field at all."""
    try:                                    # agent-authored designs publish these
        return (geo.scalar("overall.width"), geo.scalar("overall.depth"),
                geo.scalar("overall.height"))
    except Exception:  # noqa: BLE001
        pass
    try:                                    # curated nodes carry finished elements
        el = max(geo.elements, key=lambda e: e.finished_length.as_finished)
        return (el.finished_length.as_finished, el.finished_width.as_finished,
                geo.scalar("overall_height"))
    except Exception:  # noqa: BLE001
        pass
    bx = geo.structure.get("boxes") or []
    if not bx:
        return None
    return (max(b["x"] + b["w"] for b in bx) - min(b["x"] for b in bx),
            max(b["y"] + b["d"] for b in bx) - min(b["y"] for b in bx),
            max(b["z"] + b["h"] for b in bx) - min(b["z"] for b in bx))


def _cover(geo, plan, hero, kind, title, subtitle, meta, packet) -> str:
    od = overall_dims(geo)
    dims = (f"{fmt_inches(od[0])} &times; {fmt_inches(od[1])} &times; {fmt_inches(od[2])}"
            if od else "")
    wt = geo.scalars.get("weight_estimate")
    chips = [("Overall", dims or "&mdash;"),
             ("Weight", f"~{wt.value:g} lb" if wt else "&mdash;"),
             ("Skill", meta.get("skill", "Intermediate")),
             ("Shop time", meta.get("shop_time", "&mdash;")),
             ("Parts", f"{geo.part_type_count()} types / {geo.piece_count()} pcs"),
             ("Sheets", str(sum(n.sheet_count() for n in plan.nests.values()))),
             ("Finish", _e(_finish_name(geo))),
             ("Elapsed", meta.get("elapsed", "&mdash;"))]
    chiprows = "".join(f'<div class="row"><span class="k">{k}</span>'
                       f'<span class="v">{v}</span></div>' for k, v in chips)
    calls = ""
    if packet.get("callouts"):
        cells = "".join(f'<div class="callout crit"><span class="ct">{_e(_human(c.get("title",""), geo))}</span>'
                        f'<p>{_e(_human(c.get("body",""), geo))}</p></div>' for c in packet["callouts"][:3])
        calls = f'<div class="callouts">{cells}</div>'
    exploded = _svg(hero["exploded"]) if "exploded" in hero else ""
    return f"""
    <div class="cover">
      <div class="revtag">Build packet / Rev A</div>
      <div class="toprule"></div>
      <div class="coverwrap">
        <div class="lead">
          <div class="eyebrow">{_e(kind)}</div>
          <h1 class="doctitle">{_e(title)}</h1>
          <div class="subtitle">{_e(subtitle)}</div>
        </div>
        <div class="specchips">{chiprows}</div>
      </div>
      {exploded}
      {calls}
    </div>"""


def _finish_name(geo: Geometry) -> str:
    from ..catalog.finishes import get_finish
    try:
        return get_finish(geo.finish_id).display_name
    except Exception:  # noqa: BLE001
        return geo.finish_id.replace("_", " ")


def _param_table(geo: Geometry) -> str:
    rows = [[_e(p.label), fmt_inches(p.value) if p.unit == "in" else f"{p.value:g} {p.unit}"]
            for p in _param_list(geo)]
    return _table(["Parameter", "Value"], rows)


def _param_list(geo: Geometry):
    from .model import Param
    # reconstruct param labels from scalars (param.<id>) — value already in inches
    out = []
    for k, s in sorted(geo.scalars.items()):
        if k.startswith("param."):
            out.append(Param(id=k[6:], label=k[6:].replace("_", " ").title(),
                             value=s.value, unit=s.unit, source="user"))
    return out


def _step(i: int, st: dict, geo=None) -> str:
    chips = "".join(f'<span class="chip tool">{_e(x)}</span>' for x in st.get("tools", []))
    chips += "".join(f'<span class="chip fast">{_e(x)}</span>' for x in st.get("fasteners", []))
    check = f'<div class="stepsign">&#9744; {_e(_human(st.get("check",""), geo) if geo else st.get("check",""))}<span class="ts">time: ____</span></div>' \
        if st.get("check") else ""
    return f"""<div class="step"><div class="stephead">
      <span class="stepn">{i:02d}</span><span class="stepphase">{_e(st.get('phase',''))}</span>
      <span class="steptitle">{_e(_human(st.get('title',''), geo) if geo else st.get('title',''))}</span></div>
      <div class="stepdetail">{_e(_human(st.get('detail',''), geo) if geo else st.get('detail',''))}</div>
      <div class="chips">{chips}</div>{check}</div>"""


def build_generic_document(geo: Geometry, plan: NestingPlan, packet: dict,
                           out_name: str = "packet") -> dict:
    """Two-pass build for an agent-authored design, mirroring build_document.

    Callers were assembling this by hand — measure, paginate, render, name the
    runhead — and each one had to remember that ``node_kind`` is an id: a case_good
    design printed CASE_GOOD across every page and its footer."""
    import os
    from ..document.engine import _measure, _paginate, _render_pages

    blocks = build_blocks_generic(geo, plan, packet)
    heights = _measure(blocks)
    pages = _paginate(blocks, heights)
    kind = str(geo.structure.get("node_kind", geo.node) or "build").replace("_", " ")
    od = overall_dims(geo)
    dims = (f"{fmt_inches(od[0])} x {fmt_inches(od[1])} x {fmt_inches(od[2])}"
            if od else "")
    runhead = f"{kind} &middot; {dims}" if dims else kind
    html = _render_pages(pages, runhead=runhead, footer_left=f"{kind} build packet")
    os.makedirs("out", exist_ok=True)
    html_path = os.path.join("out", f"{out_name}.html")
    with open(html_path, "w") as fh:
        fh.write(html)
    return {"html_path": html_path, "html": html, "pages": pages,
            "page_count": len(pages), "heights": heights, "blocks": blocks}
