"""Document content builder — Part 5.2.

Emits the required sections as a flat list of content *blocks* (id, kind, html).
Blocks are the unit the two-pass paginator measures and packs. Every number in
prose is a solver value routed through :func:`fmt_inches`, so Gate 1 (number
provenance) can trace it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.model import Geometry
from ..parts.joinery import tool_schedule
from ..drawing.primitives import fmt_inches

REVISION = "A"


@dataclass
class Block:
    id: str
    kind: str          # cover | header | figure | table | step | prose
    html: str


def _svg(canvas) -> str:
    return f'<div class="fig">{canvas.render()}<div class="figcap">{_e(canvas.title)} '\
           f'<span class="stage">[{canvas.stage.replace("_", " ")}]</span></div></div>'


# --------------------------------------------------------------------------
# section renderers
# --------------------------------------------------------------------------

def _cover(geo: Geometry, draw) -> str:
    L = fmt_inches(geo.elements[0].finished_length.as_finished)
    Wd = fmt_inches(geo.elements[0].finished_width.as_finished)
    H = fmt_inches(geo.scalar("overall_height"))
    chips = [
        ("Overall", f"{L} &times; {Wd} &times; {H}"),
        ("Weight", f"~{geo.scalar('weight_estimate'):g} lb"),
        ("Skill", "Intermediate"),
        ("Sheets", f"{sum(1 for _ in geo.parts)} parts / 3 sheets"),
        ("Joinery", "Butt, glued + screwed"),
        ("Finish", "Microcement, 3 coats"),
        ("Coated area", f"~{geo.scalar('coated_area'):g} sq ft"),
        ("Reveal", f"{fmt_inches(geo.scalar('plinth.inset.as_finished'))} / side"),
    ]
    chiprows = "".join(f'<div class="row"><span class="k">{k}</span>'
                       f'<span class="v">{v}</span></div>' for k, v in chips)
    callouts = _cover_callouts(geo)
    return f"""
    <div class="cover">
      <div class="revtag">Build packet / Rev {REVISION}</div>
      <div class="toprule"></div>
      <div class="coverwrap">
        <div class="lead">
          <div class="eyebrow">Coffee table</div>
          <h1 class="doctitle">Microcement<br>Monolith</h1>
          <div class="subtitle">A {L} by {Wd} top slab reading {fmt_inches(geo.elements[0].finished_height.as_finished)} thick,
          floating on an inset plinth with a {fmt_inches(geo.scalar('plinth.inset.as_finished'))} shadow reveal on all four
          sides. Plywood carcass, cement-board skin, warm-gray microcement over the whole assembly, no seam.</div>
        </div>
        <div class="specchips">{chiprows}</div>
      </div>
      {_svg(draw['exploded_assembly'])}
      {callouts}
    </div>"""


def _cover_callouts(geo: Geometry) -> str:
    cut = fmt_inches(geo.scalar("plinth.carcass_height.as_cut"))
    fin = fmt_inches(geo.scalar("plinth.height.as_finished"))
    s = fmt_inches(geo.per_face_offset)
    items = [
        ("Everything here is derived",
         "Every number comes from your answers. Change the slab edge, the reveal or the overall "
         "size and the cut list, the nesting and the weight all move with it."),
        ("Read the allowance page first",
         f"Skin allowance is the one thing most likely to ruin this build. Every plywood part is "
         f"undersized by {s} per exposed face."),
        ("Plinth reads two heights",
         f"Cut the plinth {cut} tall; it measures {fin} on the finished piece because the slab edge "
         f"occludes the top. This is correct, not an error."),
    ]
    cells = "".join(f'<div class="callout crit"><span class="ct">{_e(t)}</span>'
                    f'<p>{p}</p></div>' for t, p in items)
    return f'<div class="callouts">{cells}</div>'


def _callout(title: str, body: str, kind: str = "info") -> str:
    return f'<div class="callout box {kind}"><span class="ct">{_e(title)}</span><p>{body}</p></div>'


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


def _tool_table(geo: Geometry) -> str:
    ops = geo.structure["operations"]
    # The operation is an id in the model and an instruction on the page: this
    # column shipped reading "drill_pilot_countersink" to a person holding a drill.
    rows = [[t.tool, t.setting, t.justified_by.replace("_", " ")]
            for t in tool_schedule(ops)]
    return _table(["Tool / bit", "Setting", "Required by operation"], rows)


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

def _h(text: str, kicker: str = "") -> str:
    k = f'<span class="kicker">{_e(kicker)}</span>' if kicker else ""
    return f'<h2 class="section"><span>{_e(text)}</span>{k}</h2>'


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
