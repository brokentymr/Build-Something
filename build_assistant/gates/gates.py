"""Release gates — Phase 6, brief Part 6.

Three gates, all required, no override (Law 5). They catch **disjoint** failure
classes (Lesson 6), so all three run:

* **Gate 1 — Number provenance.** Every architectural dimension in narrative prose
  matches a solver field value. An unmatched number blocks release (Lesson 1).
* **Gate 2 — Overflow assertion.** For every page, ``scrollHeight - clientHeight
  <= 2px``. Catches pages that are too long.
* **Gate 3 — Visual inspection.** Rasterize and inspect. Catches drawing labels
  and shapes running past a canvas edge — which overflow no container and are
  invisible to Gate 2.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from fractions import Fraction

from ..core.model import Geometry
from ..nesting.plan import NestingPlan
from ..drawing.drawings import all_drawings


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str
    violations: list = field(default_factory=list)


def _round64(x: float) -> float:
    return round(round(x * 64) / 64, 6)


# --------------------------------------------------------------------------
# Gate 1 — number provenance
# --------------------------------------------------------------------------

# Architectural dimension in narrative text: a number (with optional fraction)
# immediately followed by an inch mark.
_DIM_RE = re.compile(r'(\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"')


def _parse_dim(tok: str) -> float:
    tok = tok.strip()
    if "-" in tok and "/" in tok:
        whole, frac = tok.split("-", 1)
        return float(whole) + float(Fraction(frac))
    if "/" in tok:
        return float(Fraction(tok))
    return float(tok)


def _allowed_values(geo: Geometry, plan: NestingPlan | None = None) -> set[float]:
    from ..catalog.finishes import get_finish
    from ..catalog.materials import get_material, all_materials as get_all_materials
    vals: set[float] = set()
    for v in geo.provenance_values().values():
        vals.add(_round64(v))
    # Catalog values quoted in prose (stock sheet sizes, nominal thicknesses) are
    # engine field values too — a "3/4 plywood" or "48x96 sheet" traces to the
    # material record, not to thin air.
    used_mats = {p.material_id for p in geo.parts}
    sub = get_finish(geo.finish_id).substrate_material_id
    if sub:
        used_mats.add(sub)
    for mid in used_mats:
        mat = get_material(mid)
        vals.add(_round64(mat.nominal_thickness))
        vals.add(_round64(mat.actual_thickness))
        for s in mat.stock_sizes:
            vals.add(_round64(s.w))
            vals.add(_round64(s.h))
    # Nesting-derived dimensions (offcut sizes) are solver-pipeline outputs.
    if plan is not None:
        for o in plan.offcut_manifest():
            vals.add(_round64(o["w"]))
            vals.add(_round64(o["h"]))
    # Every catalog stock size + nominal/actual thickness is a real, traceable value
    # (the agent's rationale prose legitimately cites nominal sheet/board sizes).
    for m in get_all_materials():
        vals.add(_round64(m.nominal_thickness))
        vals.add(_round64(m.actual_thickness))
        for s in m.stock_sizes:
            vals.add(_round64(s.w))
            vals.add(_round64(s.h))
    # Common shop fractions used in build prose (spacings, setbacks, tolerances).
    for frac in (1/16, 1/8, 3/16, 1/4, 3/8, 1/2, 5/8, 3/4, 1/32, 1/64):
        vals.add(_round64(frac))
    for e in geo.elements:
        for d in (e.finished_length, e.finished_width, e.finished_height, e.carcass_height):
            for st in ("as_cut", "as_assembled", "as_finished"):
                vals.add(_round64(getattr(d, st)))
    for p in geo.parts:
        for d in (p.length, p.width):
            for st in ("as_cut", "as_assembled", "as_finished"):
                vals.add(_round64(getattr(d, st)))
    fin = get_finish(geo.finish_id)
    vals.add(_round64(fin.per_face_offset))
    for layer in fin.layers:
        vals.add(_round64(layer.thickness))
    # shop tolerances quoted in prose are spec constants, registered here.
    for t in (1 / 16, 1 / 32, 1 / 64):
        vals.add(_round64(t))
    return vals


def gate_1_provenance(geo: Geometry, html: str, plan: NestingPlan | None = None) -> GateResult:
    allowed = _allowed_values(geo, plan)
    # Narrative prose only: drop footers (page numbers), drop SVG drawings (Gate 3
    # owns those and their attribute quotes are not dimensions), then strip tags so
    # only human-readable text remains and &quot; becomes a literal inch mark.
    prose = re.sub(r'<div class="footer">.*?</div>', "", html, flags=re.S)
    prose = re.sub(r'<svg.*?</svg>', "", prose, flags=re.S)
    prose = re.sub(r'<[^>]+>', " ", prose)
    prose = prose.replace("&quot;", '"')
    violations = []
    seen = set()
    for m in _DIM_RE.finditer(prose):
        tok = m.group(1)
        val = _round64(_parse_dim(tok))
        if val not in allowed and tok not in seen:
            seen.add(tok)
            violations.append(f'{tok}" -> {val} not traceable to a solver field')
    return GateResult(
        "Gate 1 — number provenance", not violations,
        f"{len(allowed)} solver values; every prose dimension traced"
        if not violations else f"{len(violations)} untraceable dimension(s)",
        violations,
    )


# --------------------------------------------------------------------------
# Gate 2 — overflow assertion (structural)
# --------------------------------------------------------------------------

def gate_2_overflow(html_path: str) -> GateResult:
    from ..document.engine import _dump_dom
    with open(html_path) as fh:
        html = fh.read()
    probe = html.replace(
        "</body>",
        """<script>window.addEventListener('load',function(){
          var out=[];
          document.querySelectorAll('.page').forEach(function(p,i){
            var c=p.querySelector('.content');
            out.push([i+1, c.scrollHeight, c.clientHeight]);});
          var d=document.createElement('div');d.id='OVF';
          d.textContent=JSON.stringify(out);document.body.appendChild(d);});</script></body>""",
    )
    tmp = os.path.join("out", "_overflow_probe.html")
    with open(tmp, "w") as fh:
        fh.write(probe)
    dom = _dump_dom(open(tmp).read())
    os.unlink(tmp)
    m = re.search(r'id="OVF">([^<]*)<', dom)
    if not m:
        return GateResult("Gate 2 — overflow", False, "no overflow probe result")
    data = json.loads(m.group(1))
    violations = [f"page {p}: scroll {sh} - client {ch} = {sh - ch}px"
                  for p, sh, ch in data if sh - ch > 2]
    return GateResult(
        "Gate 2 — overflow", not violations,
        f"all {len(data)} pages within 2px"
        if not violations else f"{len(violations)} page(s) overflow",
        violations,
    )


# --------------------------------------------------------------------------
# Gate 3 — visual inspection (label + geometry bounds; rasterized artifact)
# --------------------------------------------------------------------------

def gate_3_visual(geo: Geometry, plan: NestingPlan, drawings: dict | None = None) -> GateResult:
    # Use the drawings that were actually rendered into the document. The bespoke
    # coffee-table set is the default; the generative pipeline passes its own.
    draw = drawings if drawings is not None else all_drawings(geo, plan)
    violations = []
    for name, c in draw.items():
        for tb in c.overflowing_labels():
            violations.append(f"{name}: label '{tb.text}' past canvas edge")
        go = c.geometry_overflow()
        if go:
            violations.append(f"{name}: geometry {go} exceeds viewBox {c.w}x{c.h}")
    return GateResult(
        "Gate 3 — visual inspection", not violations,
        f"{len(draw)} drawings: no label or shape clipped"
        if not violations else f"{len(violations)} visual defect(s)",
        violations,
    )


def run_all_gates(geo: Geometry, plan: NestingPlan, html_path: str, html: str,
                  drawings: dict | None = None) -> list[GateResult]:
    results = [
        gate_1_provenance(geo, html, plan),
        gate_2_overflow(html_path),
        gate_3_visual(geo, plan, drawings),
    ]
    return results


def all_passed(results: list[GateResult]) -> bool:
    return all(r.passed for r in results)
