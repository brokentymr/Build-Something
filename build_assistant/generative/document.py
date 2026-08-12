"""Generic build packet — reference-grade, for ANY object.

Assembles the editorial packet from three sources: verified numbers (engine),
hero drawings projected from 3D part placement (engine), and the instructional
content authored by the design agent (title, callouts, tolerances, phased steps,
cure, care). Reuses the shared document design system and the release gates.
"""

from __future__ import annotations

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
           f'<span class="stage">[{c.stage}]</span></div></div>'


def _stock_diagram(geo: Geometry, nest, mid: str, i: int) -> Canvas:
    """Sheet nesting for panels; a linear cut run for long board stock."""
    from ..catalog.materials import get_material
    mat = get_material(mid)
    long_stock = mat.category in ("lumber", "hardwood") or \
        max(nest.sheet_w, nest.sheet_h) > 3.2 * min(nest.sheet_w, nest.sheet_h)
    return gdetail.board_layout(nest, i) if long_stock else nesting_diagram(nest, i)


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
    warnings = geo.structure.get("warnings", [])
    if warnings:
        B("warn", "prose", '<div class="notice"><b>Design notes:</b> '
          + "; ".join(_e(w) for w in warnings) + "</div>")

    # ---------- DESIGN SPECIFICATION (governing dims + hero views) ----------
    B("h_spec", "header", _h("Design specification", "finished dimensions"))
    if packet.get("governing_note"):
        B("govnote", "prose", f'<div class="agent-note"><p>{_e(packet["governing_note"])}</p></div>')
    B("spec", "table", _param_table(geo))
    for k in ("plan", "front_elevation", "side_elevation"):
        if k in hero:
            B(f"fig_{k}", "figure", _svg(hero[k]))

    # ---------- CRITICAL CONCEPT callouts ----------
    callouts = packet.get("callouts") or []
    if callouts:
        B("h_crit", "header", _h("Before you cut", "read this first"))
        kinds = {"crit": "warn", "warn": "warn", "info": "info"}
        cells = "".join(_callout(c.get("title", ""), _e(c.get("body", "")),
                                 kinds.get(c.get("kind", "info"), "info")) for c in callouts[:3])
        B("crit", "prose", f'<div class="callouts" style="border:none;padding-top:0">{cells}</div>')

    # ---------- SECTIONS + JOINT DETAILS + PREDRILLS ----------
    details = gdetail.detail_drawings(geo)
    sections = [k for k in ("section_aa", "section_bb") if k in details]
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
    cut = [[str(items.get(p.id, "")), _e(p.name),
            f"{fmt_inches(p.cut_wh()[0])} &times; {fmt_inches(p.cut_wh()[1])}",
            str(p.qty), _e(p.material_id.replace('_', ' ')),
            f'<span class="agent-note">{_e(p.joint)}</span>'] for p in geo.parts]
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
        B("tol", "table", '<div class="agent-note">'+_table(["Check", "Tolerance"], [[_e(t.get("check", "")), _e(t.get("tolerance", ""))] for t in tol])+'</div>')

    # ---------- BUILD SEQUENCE ----------
    steps = packet.get("steps") or []
    if steps:
        B("h_seq", "header", _h("Build sequence", f"{len(steps)} steps"))
        for i, st in enumerate(steps, 1):
            B(f"step_{i}", "step", _step(i, st))

    # ---------- CURE SCHEDULE ----------
    cure = packet.get("cure") or []
    if cure:
        B("h_cure", "header", _h("Cure schedule", "mostly waiting"))
        B("cure", "table", '<div class="agent-note">'+_table(["Stage", "Wait", "Note"], [[_e(c.get("stage", "")), _e(c.get("wait", "")), _e(c.get("note", ""))] for c in cure])+'</div>')

    # ---------- CARE ----------
    if packet.get("care"):
        B("h_care", "header", _h("Care and maintenance"))
        B("care", "prose", f'<div class="agent-note"><p>{_e(packet["care"])}</p></div>')

    # ---------- DESIGN RECORD ----------
    B("h_rec", "header", _h("Design record", "inputs that generated this packet"))
    rec = [[_e(p.label), fmt_inches(p.value) if p.unit == "in" else f"{p.value:g} {p.unit}",
            _e(p.source)] for p in _param_list(geo)]
    B("rec", "table", _table(["Parameter", "Value", "Source"], rec))

    return blocks


# --------------------------------------------------------------------------

def _cover(geo, plan, hero, kind, title, subtitle, meta, packet) -> str:
    dims = ""
    if "boxes" in geo.structure and geo.structure["boxes"]:
        bx = geo.structure["boxes"]
        xs = [b["x"] for b in bx] + [b["x"] + b["w"] for b in bx]
        ys = [b["y"] for b in bx] + [b["y"] + b["d"] for b in bx]
        zs = [b["z"] for b in bx] + [b["z"] + b["h"] for b in bx]
        dims = f"{fmt_inches(max(xs)-min(xs))} &times; {fmt_inches(max(ys)-min(ys))} &times; {fmt_inches(max(zs)-min(zs))}"
    wt = geo.scalars.get("weight_estimate")
    chips = [("Overall", dims or "&mdash;"),
             ("Weight", f"~{wt.value:g} lb" if wt else "&mdash;"),
             ("Skill", meta.get("skill", "Intermediate")),
             ("Shop time", meta.get("shop_time", "&mdash;")),
             ("Parts", f"{geo.part_type_count()} types / {geo.piece_count()} pcs"),
             ("Sheets", str(sum(n.sheet_count() for n in plan.nests.values()))),
             ("Finish", _e(geo.finish_id.replace("_", " "))),
             ("Elapsed", meta.get("elapsed", "&mdash;"))]
    chiprows = "".join(f'<div class="row"><span class="k">{k}</span>'
                       f'<span class="v">{v}</span></div>' for k, v in chips)
    calls = ""
    if packet.get("callouts"):
        cells = "".join(f'<div class="callout crit"><span class="ct">{_e(c.get("title",""))}</span>'
                        f'<p>{_e(c.get("body",""))}</p></div>' for c in packet["callouts"][:3])
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


def _step(i: int, st: dict) -> str:
    chips = "".join(f'<span class="chip tool">{_e(x)}</span>' for x in st.get("tools", []))
    chips += "".join(f'<span class="chip fast">{_e(x)}</span>' for x in st.get("fasteners", []))
    check = f'<div class="stepsign">&#9744; {_e(st.get("check",""))}<span class="ts">time: ____</span></div>' \
        if st.get("check") else ""
    return f"""<div class="step"><div class="stephead">
      <span class="stepn">{i:02d}</span><span class="stepphase">{_e(st.get('phase',''))}</span>
      <span class="steptitle">{_e(st.get('title',''))}</span></div>
      <div class="stepdetail">{_e(st.get('detail',''))}</div>
      <div class="chips">{chips}</div>{check}</div>"""
