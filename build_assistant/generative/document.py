"""Generic build document — works from ANY solved Geometry.

The coffee-table document is bespoke; this one assumes nothing about the object.
It renders: cover + spec (parameters), a proportional elevation/plan from the
element bounding boxes, bill of materials, cut lists, sheet nesting diagrams with
yield, a build sequence (supplied by the agent or a generic fallback), derived
decisions with basis, and any warnings. Reuses the two-pass engine and the gates.
"""

from __future__ import annotations

from ..core.model import Geometry
from ..nesting.plan import NestingPlan
from ..drawing.primitives import Canvas, fmt_inches
from ..drawing.drawings import nesting_diagram
from ..document.content import Block, _table, _h, _e
from ..parts.joinery import tool_schedule

W = 520.0
MARGIN = 56.0


def _box_elevation(geo: Geometry, title: str) -> Canvas:
    """A proportional front elevation from the union of element bounding boxes."""
    c = Canvas(W, 320, title=title, stage="as_finished")
    els = geo.elements
    if not els:
        return c
    maxL = max(e.finished_length.as_finished for e in els)
    maxH = max((e.z_base + e.finished_height.as_finished) for e in els) or 1
    s = min((W - 2 * MARGIN) / maxL, (320 - 2 * MARGIN - 20) / maxH)
    ox = MARGIN
    oy = 320 - MARGIN
    shades = ["#e9e4da", "#d8d0c4", "#efe9dd", "#e5ded1", "#f0ece3"]
    for i, e in enumerate(els):
        L = e.finished_length.as_finished
        H = e.finished_height.as_finished
        z = e.z_base
        c.rect(ox + (maxL - L) * s / 2, oy - (z + H) * s, L * s, H * s,
               fill=shades[i % len(shades)], sw=1.1)
    c.dim_horizontal(ox, ox + maxL * s, oy + 20, fmt_inches(maxL))
    c.dim_vertical(oy - maxH * s, oy, ox - 14, fmt_inches(maxH))
    return c


def generic_drawings(geo: Geometry, plan: NestingPlan) -> dict:
    """The canvases used by the generic document — also handed to the visual gate."""
    d = {"elevation": _box_elevation(geo, "Proportional elevation")}
    for mid, nest in plan.nests.items():
        for i in range(1, nest.sheet_count() + 1):
            d[f"nest_{mid}_{i}"] = nesting_diagram(nest, i)
    return d


def build_blocks_generic(geo: Geometry, plan: NestingPlan, sequence: list) -> list[Block]:
    from ..catalog.materials import get_material
    blocks: list[Block] = []

    def B(bid, kind, html):
        blocks.append(Block(bid, kind, html))

    summary = geo.structure.get("summary", "")
    kind = geo.structure.get("node_kind", geo.node)

    # cover
    cover = f"""<div class="cover"><div class="revtag">Revision A</div>
      <h1 class="doctitle">{_e(geo.inputs.get('name', kind))}</h1>
      <div class="subtitle">{_e(summary)}</div>
      <div class="specsummary">
        <div><span class="k">Type</span><span class="v">{_e(kind)}</span></div>
        <div><span class="k">Parts</span><span class="v">{geo.part_type_count()} types / {geo.piece_count()} pieces</span></div>
        <div><span class="k">Sheets</span><span class="v">{sum(n.sheet_count() for n in plan.nests.values())}</span></div>
        <div><span class="k">Finish</span><span class="v">{_e(geo.finish_id)}</span></div>
      </div>{_fig(_box_elevation(geo,'Proportional elevation'))}</div>"""
    B("cover", "cover", cover)

    warnings = geo.structure.get("warnings", [])
    if warnings:
        B("warn", "prose", '<div class="notice"><b>Design notes:</b> ' +
          "; ".join(_e(w) for w in warnings) + "</div>")

    # spec (parameters)
    B("h_spec", "header", _h("Dimensions"))
    prm = [[_e(s.field_id.replace("param.", "")), fmt_inches(s.value) if s.unit == "in" else f"{s.value:g} {s.unit}"]
           for k, s in sorted(geo.scalars.items()) if k.startswith("param.")]
    B("spec", "table", _table(["Parameter", "Value"], prm) if prm else "<p>—</p>")

    # BOM
    B("h_bom", "header", _h("Bill of materials"))
    counts: dict[str, int] = {}
    for mid, n in plan.nests.items():
        counts[mid] = n.sheet_count()
    bom = []
    for mid, sheets in counts.items():
        m = get_material(mid)
        st = m.stock_sizes[0]
        bom.append([m.display_name, f"{sheets} @ {fmt_inches(st.w)}&times;{fmt_inches(st.h)}",
                    _e(m.category)])
    B("bom", "table", _table(["Material", "Quantity", "Category"], bom))

    # tool schedule (from operations)
    ops = geo.structure.get("operations", set())
    if ops:
        try:
            ts = [[t.tool, t.setting, t.justified_by] for t in tool_schedule(ops)]
            B("h_tool", "header", _h("Tools"))
            B("tool", "table", _table(["Tool / bit", "Setting", "For"], ts))
        except Exception:  # noqa: BLE001
            pass

    # cut list
    B("h_cut", "header", _h("Cut list (as-cut)"))
    cut = [[p.id, _e(p.name), f"{fmt_inches(p.cut_wh()[0])} &times; {fmt_inches(p.cut_wh()[1])}",
            str(p.qty), _e(p.material_id.replace('_', ' ')), _e(p.joint)] for p in geo.parts]
    B("cut", "table", _table(["ID", "Part", "As-cut", "Qty", "Material", "Joint"], cut))

    # sheet layouts
    B("h_sheet", "header", _h("Sheet layouts"))
    for mid, nest in plan.nests.items():
        for i in range(1, nest.sheet_count() + 1):
            B(f"nest_{mid}_{i}", "figure", _fig(nesting_diagram(nest, i)))

    # build sequence
    B("h_seq", "header", _h("Build sequence"))
    for i, st in enumerate(sequence, 1):
        chips = "".join(f'<span class="chip tool">{_e(x)}</span>' for x in st.get("tools", []))
        chips += "".join(f'<span class="chip fast">{_e(x)}</span>' for x in st.get("fasteners", []))
        B(f"step_{i}", "step", f"""<div class="step"><div class="stephead">
          <span class="stepn">{i}</span><span class="stepphase">{_e(st.get('phase',''))}</span>
          <span class="steptitle">{_e(st.get('title',''))}</span></div>
          <div class="stepdetail">{_e(st.get('detail',''))}</div>
          <div class="chips">{chips}</div>
          <div class="steptol"><b>Check:</b> {_e(st.get('check',''))}</div>
          <div class="stepsign">&#9744; Sign-off<span class="ts">time: ____</span></div></div>""")

    # derived decisions
    if geo.derived_decisions:
        B("h_der", "header", _h("Derived, not asked"))
        der = [[_e(d.label), _e(d.value), _e(d.basis)] for d in geo.derived_decisions]
        B("der", "table", _table(["Decision", "Value", "Basis"], der))

    return blocks


def _fig(canvas: Canvas) -> str:
    return f'<div class="fig">{canvas.render()}<div class="figcap">{_e(canvas.title)} '\
           f'<span class="stage">[{canvas.stage}]</span></div></div>'
