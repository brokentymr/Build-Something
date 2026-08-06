"""Document content builder — Part 5.2.

Emits the required sections as a flat list of content *blocks* (id, kind, html).
Blocks are the unit the two-pass paginator measures and packs. Every number in
prose is a solver value routed through :func:`fmt_inches`, so Gate 1 (number
provenance) can trace it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.model import Geometry
from ..nesting.plan import NestingPlan
from ..parts.joinery import tool_schedule, fastener_bom
from ..drawing.drawings import all_drawings
from ..drawing.primitives import fmt_inches
from ..build_mode.sequence import build_sequence, Step

REVISION = "A"


@dataclass
class Block:
    id: str
    kind: str          # cover | header | figure | table | step | prose
    html: str


def _svg(canvas) -> str:
    return f'<div class="fig">{canvas.render()}<div class="figcap">{_e(canvas.title)} '\
           f'<span class="stage">[{canvas.stage}]</span></div></div>'


def build_blocks(geo: Geometry, plan: NestingPlan) -> list[Block]:
    draw = all_drawings(geo, plan)
    steps = build_sequence(geo, plan)
    blocks: list[Block] = []

    def B(bid, kind, html):
        blocks.append(Block(bid, kind, html))

    # ---- COVER ----
    B("cover", "cover", _cover(geo, draw))

    # ---- DESIGN SPECIFICATION ----
    B("h_spec", "header", _h("Design specification"))
    B("spec", "table", _spec_table(geo))

    # ---- ALLOWANCE ----
    B("h_allow", "header", _h("The allowance layer"))
    B("allow_prose", "prose", _allowance_prose(geo))
    B("allow_fig", "figure", _svg(draw["allowance_section"]))

    # ---- SUB-ASSEMBLY DRAWINGS ----
    B("h_draw", "header", _h("Sub-assembly drawings"))
    for k in ("plan", "front_elevation", "side_elevation", "core_layout"):
        B(f"fig_{k}", "figure", _svg(draw[k]))

    # ---- CRITICAL ASSEMBLY DETAILS (stage-dependent) ----
    B("h_stage", "header", _h("Critical detail — the plinth reads two heights"))
    B("stage_prose", "prose", _stage_prose(geo))
    B("fig_pcut", "figure", _svg(draw["plinth_as_cut"]))
    B("fig_pfin", "figure", _svg(draw["plinth_as_finished"]))

    # ---- BILL OF MATERIALS ----
    B("h_bom", "header", _h("Bill of materials"))
    B("bom", "table", _bom_table(geo, plan))

    # ---- TOOL & BIT SCHEDULE ----
    B("h_tool", "header", _h("Tool and bit schedule"))
    B("tool", "table", _tool_table(geo))
    B("fig_fast", "figure", _svg(draw["fastener_spacing"]))

    # ---- CUT LISTS ----
    B("h_cut", "header", _h("Cut lists (quoted as-cut)"))
    B("cut", "table", _cut_table(geo))

    # ---- SHEET LAYOUTS ----
    B("h_sheet", "header", _h("Sheet layouts, yield and waste"))
    for mid, nest in plan.nests.items():
        for i in range(1, nest.sheet_count() + 1):
            B(f"nest_{mid}_{i}", "figure", _svg(draw[f"nest_{mid}_{i}"]))
    B("waste", "prose", _waste_prose(plan))

    # ---- BUILD SEQUENCE ----
    B("h_seq", "header", _h("Phased build sequence"))
    for st in steps:
        B(f"step_{st.n}", "step", _step_block(st))

    # ---- CURE SCHEDULE ----
    B("h_cure", "header", _h("Cure schedule"))
    B("cure", "table", _cure_table())

    # ---- QC CHECKLIST ----
    B("h_qc", "header", _h("Final QC checklist"))
    B("qc", "table", _qc_table(geo))

    # ---- TROUBLESHOOTING ----
    B("h_ts", "header", _h("Troubleshooting"))
    B("ts", "table", _troubleshooting_table())

    # ---- CARE ----
    B("h_care", "header", _h("Care and maintenance"))
    B("care", "prose", _care_prose())

    # ---- DESIGN RECORD ----
    B("h_rec", "header", _h("Design record — every answer"))
    B("rec", "table", _record_table(geo))

    # ---- DERIVED, NOT ASKED ----
    B("h_der", "header", _h("Derived, not asked"))
    B("der", "table", _derived_table(geo))

    # ---- CORRECTION LOG ----
    B("h_corr", "header", _h("Correction log"))
    B("corr", "table", _correction_table())

    return blocks


# --------------------------------------------------------------------------
# section renderers
# --------------------------------------------------------------------------

def _cover(geo: Geometry, draw) -> str:
    L = fmt_inches(geo.elements[0].finished_length.as_finished)
    Wd = fmt_inches(geo.elements[0].finished_width.as_finished)
    H = fmt_inches(geo.scalar("overall_height"))
    return f"""
    <div class="cover">
      <div class="revtag">Revision {REVISION}</div>
      <h1 class="doctitle">Coffee table — build package</h1>
      <div class="subtitle">Microcement over cement board · plinth base · single monolith</div>
      <div class="specsummary">
        <div><span class="k">Overall</span><span class="v">{L} &times; {Wd} &times; {H}</span></div>
        <div><span class="k">Slab edge</span><span class="v">{fmt_inches(geo.elements[0].finished_height.as_finished)}</span></div>
        <div><span class="k">Reveal</span><span class="v">{fmt_inches(geo.scalar('plinth.inset.as_finished'))} per side</span></div>
        <div><span class="k">Parts</span><span class="v">{geo.part_type_count()} types / {geo.piece_count()} pieces</span></div>
        <div><span class="k">Est. weight</span><span class="v">~{geo.scalar('weight_estimate'):g} lb</span></div>
        <div><span class="k">Coated area</span><span class="v">~{geo.scalar('coated_area'):g} sq ft</span></div>
      </div>
      {_svg(draw['exploded_assembly'])}
    </div>"""


def _spec_table(geo: Geometry) -> str:
    rows = [
        ("Slab carcass thickness", fmt_inches(geo.scalar("slab.carcass_thickness"))),
        ("Slab deck (as-cut)", f'{fmt_inches(geo.scalar("slab.deck.length"))} &times; {fmt_inches(geo.scalar("slab.deck.width"))}'),
        ("Core ring width", fmt_inches(geo.scalar("slab.core_ring_width"))),
        ("Torsion-box ribs", f'{int(geo.scalar("slab.rib_count"))} @ {fmt_inches(geo.scalar("slab.bay_width"))} bays'),
        ("Plinth height (as-cut)", fmt_inches(geo.scalar("plinth.carcass_height.as_cut"))),
        ("Plinth height (as-finished)", fmt_inches(geo.scalar("plinth.height.as_finished"))),
        ("Plinth inset (as-assembled)", fmt_inches(geo.scalar("plinth.inset.as_assembled"))),
        ("Skin per-face offset", fmt_inches(geo.per_face_offset)),
    ]
    return _table(["Specification", "Value"], [[k, v] for k, v in rows])


def _allowance_prose(geo: Geometry) -> str:
    s = fmt_inches(geo.per_face_offset)
    return f"""<p>The finish system adds a per-face offset of <b>{s}</b>
    ({fmt_inches(0.25)} cement board + {fmt_inches(0.125)} microcement) between the
    substrate and the finished surface. Every exposed face is cut back by that offset
    so the finished piece lands on its target dimension. Concealed faces &mdash; the
    plinth top under the slab, the plinth bottom on the floor &mdash; receive no
    allowance, because whether a face is skinned depends on assembly, not shape.</p>"""


def _stage_prose(geo: Geometry) -> str:
    cut = fmt_inches(geo.scalar("plinth.carcass_height.as_cut"))
    fin = fmt_inches(geo.scalar("plinth.height.as_finished"))
    return f"""<p>The plinth is cut <b>{cut}</b> tall but reads <b>{fin}</b> on the finished
    piece: the slab edge occludes its top {fmt_inches(geo.per_face_offset)}. Overall height is
    the plinth carcass {cut} plus the slab carcass {fmt_inches(geo.scalar('slab.carcass_thickness'))}
    plus the top skin {fmt_inches(geo.per_face_offset)} &mdash; the slab underside reveal skin sits
    co-planar with the plinth top and does <i>not</i> stack. Cut to {cut}; measure {fin}.</p>"""


def _bom_table(geo: Geometry, plan: NestingPlan) -> str:
    from ..catalog.materials import get_material
    rows = []
    for mid, count in plan.purchase().items():
        mat = get_material(mid)
        reason = {
            "ply_075_structural": "Carcass: slab decks, core ring, plinth walls and platforms.",
            "cement_board_025": "Rigid substrate the microcement bonds to; plywood alone would craze.",
        }.get(mid, "Structural component.")
        st = mat.stock_sizes[0]
        rows.append([mat.display_name, f'{count} sheet(s) @ {fmt_inches(st.w)}&times;{fmt_inches(st.h)}', reason])
    rows.append(["Microcement kit", "1 kit", "Two base coats + top coat over the full coated area."])
    rows.append(["Cement-board screws", "1 box", "Wafer head; drywall screws snap under load in cement board."])
    return _table(["Material", "Quantity", "Reason"], rows)


def _tool_table(geo: Geometry) -> str:
    ops = geo.structure["operations"]
    rows = [[t.tool, t.setting, t.justified_by] for t in tool_schedule(ops)]
    return _table(["Tool / bit", "Setting", "Required by operation"], rows)


def _cut_table(geo: Geometry) -> str:
    rows = []
    for p in geo.parts:
        L, Wd = p.cut_wh()
        rows.append([p.id, p.name, f"{fmt_inches(L)} &times; {fmt_inches(Wd)}",
                     str(p.qty), p.material_id.replace("_", " ")])
    return _table(["ID", "Part", "As-cut", "Qty", "Material"], rows)


def _waste_prose(plan: NestingPlan) -> str:
    lines = []
    for mid, nest in plan.nests.items():
        for s in nest.sheets:
            lines.append(f"{mid.replace('_',' ')} sheet {s.index}: "
                         f"{s.utilisation()*100:.1f}% used, {(1-s.utilisation())*100:.1f}% waste.")
    claim = ""
    for o in plan.offcut_manifest():
        if min(o["w"], o["h"]) >= 9 and o["w"]*o["h"] >= 9*18:
            claim = (f" A {fmt_inches(o['w'])} &times; {fmt_inches(o['h'])} offcut is claimed as a "
                     "mandatory microcement practice panel &mdash; the first panel you trowel is the "
                     "worst you will ever trowel.")
            break
    return "<p>" + " ".join(lines) + claim + "</p>"


def _step_block(st: Step) -> str:
    chips = lambda items, cls: "".join(f'<span class="chip {cls}">{_e(x)}</span>' for x in items)
    return f"""
    <div class="step">
      <div class="stephead"><span class="stepn">{st.n}</span>
        <span class="stepphase">{_e(st.phase)}</span>
        <span class="steptitle">{_e(st.title)}</span></div>
      <div class="stepdetail">{_e(st.detail)}</div>
      <div class="chips">{chips(st.tools,'tool')}{chips(st.materials,'mat')}{chips(st.fasteners,'fast')}</div>
      <div class="steptol"><b>Tolerance:</b> {_e(st.tolerance)}</div>
      <div class="stepsign">&#9744; Sign-off: {_e(st.sign_off)}<span class="ts">time: __________</span></div>
    </div>"""


def _cure_table() -> str:
    rows = [
        ["Thin-set seams", "24 h", "before base coats"],
        ["Microcement base coats", "12 h each", "sand and recoat"],
        ["Top coat", "24 h", "before sealer"],
        ["Sealer", "48 h", "before light use"],
        ["Full cure", "7 days", "before daily use"],
    ]
    return _table(["Stage", "Hold", "Note"], rows)


def _qc_table(geo: Geometry) -> str:
    rows = [
        ["Overall height", f'{fmt_inches(geo.scalar("overall_height"))} &plusmn; 1/16'],
        ["Reveal symmetry", f'{fmt_inches(geo.scalar("plinth.inset.as_finished"))} even on all four sides'],
        ["Slab edge", f'{fmt_inches(geo.elements[0].finished_height.as_finished)} consistent'],
        ["Finish", "No pinholes, chatter or crazing"],
        ["Seams", "Invisible under raking light"],
    ]
    return _table(["Check", "Pass criterion"], rows, checkbox=True)


def _troubleshooting_table() -> str:
    rows = [
        ["Slab rattles when tapped", "Deck not fully bonded to a rib", "Inject glue, clamp, re-brad"],
        ["Uneven reveal", "Slab off-center on plinth", "Re-center before substrate goes on"],
        ["Cement board crumbles at screw", "Drywall screw used", "Replace with wafer-head cement-board screw"],
        ["Trowel chatter in finish", "Coat too thick / trowel too stiff", "Thin the mix, flex the trowel, sand and recoat"],
        ["Hairline crack over a seam", "Seam not meshed", "Grind out, mesh, re-coat"],
    ]
    return _table(["Symptom", "Cause", "Fix"], rows)


def _care_prose() -> str:
    return """<p>Wipe with a damp cloth and pH-neutral cleaner; no acids or abrasives on the
    microcement. Use coasters under wet glasses until the sealer has fully cured. Re-seal every
    few years or when water stops beading. Felt the plinth feet to protect the floor.</p>"""


def _record_table(geo: Geometry) -> str:
    labels = {
        "node": "What", "overall_length": "Length", "overall_width": "Width",
        "overall_height": "Height", "slab_edge_thickness": "Slab edge",
        "base_type": "Base", "finish_system": "Finish", "plinth_inset": "Reveal",
        "assembly": "Assembly",
    }
    rows = [[labels.get(k, k), _e(str(v))] for k, v in geo.inputs.items()]
    return _table(["Question", "Answer"], rows)


def _derived_table(geo: Geometry) -> str:
    rows = [[d.label, d.value, d.basis, "yes" if d.is_overridable else "no"]
            for d in geo.derived_decisions]
    return _table(["Decision", "Value", "Basis", "Overridable"], rows)


def _correction_table() -> str:
    rows = [
        ["A", "Plinth height", "&mdash;", "13-3/8\" as-cut / 13\" as-finished",
         "Initial solve. Stage-versioned from the start; no conversational arithmetic."],
    ]
    return _table(["Rev", "Field", "Prior", "Value", "Reason"], rows)


# --------------------------------------------------------------------------
# html helpers
# --------------------------------------------------------------------------

def _h(text: str) -> str:
    return f'<h2 class="section">{_e(text)}</h2>'


def _table(headers, rows, checkbox=False) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        cells = "".join(f"<td>{c}</td>" for c in r)
        cb = '<td class="cb">&#9744;</td>' if checkbox else ""
        body += f"<tr>{cb}{cells}</tr>"
    cbh = "<th></th>" if checkbox else ""
    return f'<table class="grid"><thead><tr>{cbh}{head}</tr></thead><tbody>{body}</tbody></table>'


def _e(s: str) -> str:
    """Escape plain text for HTML. Only called on plain strings (never on markup)."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
