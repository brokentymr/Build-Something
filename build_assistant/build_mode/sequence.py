"""Phased build sequence generator — Part 5.2 / Phase 10.

Emits ~21 steps, each with tools, materials, fasteners, a tolerance and a
sign-off check (the checklist is instrumentation — Lesson 14: sign-offs are
timestamped in build mode). The generator:

* injects a **cut-order constraint** as a hard step when nesting utilisation is
  high (Lesson 4 / Part 4), and
* **claims a named offcut** as a mandatory finish-technique practice panel
  (Lesson 12).

Steps are derived from the solved geometry, joinery and nesting — never authored
as a constant list.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.model import Geometry
from ..nesting.plan import NestingPlan
from ..drawing.primitives import fmt_inches


@dataclass
class Step:
    n: int
    phase: str
    title: str
    detail: str
    tools: list[str]
    materials: list[str]
    fasteners: list[str]
    tolerance: str
    sign_off: str
    troubleshoot_ref: str = ""
    # Which parts this step puts in place, so the packet can draw the assembly as
    # it stands at that point. The agent-authored path gets these from the packet
    # writer; a hand-written recipe has to say so itself.
    parts: tuple = ()


def build_sequence(geo: Geometry, plan: NestingPlan) -> list[Step]:
    steps: list[Step] = []
    n = [0]

    def add(**kw):
        n[0] += 1
        steps.append(Step(n=n[0], **kw))

    ring = geo.scalar("slab.core_ring_width")
    deck_l = fmt_inches(geo.scalar("slab.deck.length"))
    deck_w = fmt_inches(geo.scalar("slab.deck.width"))
    edges = [fmt_inches(e) for e in geo.structure.get("rib_left_edges", [])]
    plinth_cut = fmt_inches(geo.scalar("plinth.carcass_height.as_cut"))
    inset_asm = fmt_inches(geo.scalar("plinth.inset.as_assembled"))

    # ---- PREP ----
    add(phase="Prep", title="Verify stock and acclimate",
        detail="Confirm plywood actual thickness and let cement board acclimate flat for 24h.",
        tools=["calipers"], materials=["3/4 plywood", "1/4 cement board"], fasteners=[],
        tolerance="plywood actual within ±0.015 of 0.75", sign_off="thickness logged")

    # ---- CUT (with cut-order constraint if high utilisation) ----
    if plan.cut_order_constrained():
        add(phase="Cut", title="CUT ORDER IS A SPEC (high utilisation)",
            detail=("Plywood nests at >85% on a single sheet — there is no recovery from a "
                    "bad cut. Cut the two full-length decks first, then the long core rails, "
                    "then crosscut the balance. Do not free-cut."),
            tools=["track saw", "table saw"], materials=["3/4 plywood sheet"], fasteners=[],
            tolerance="follow nesting map exactly; ±1/32 on every rip",
            sign_off="decks and long rails cut before any crosscut",
            troubleshoot_ref="oversize_part")
    add(phase="Cut", title="Cut slab decks and core",
        detail=f"Two decks at {deck_l} x {deck_w}; core ring {fmt_inches(ring)} wide; "
               f"end rails and {len([e for e in edges])} ribs to width.",
        tools=["track saw", "table saw"], materials=["3/4 plywood"], fasteners=[],
        tolerance="±1/32 on length, square within 1/64", sign_off="parts A–E match cut list")
    add(phase="Cut", title="Cut plinth panels",
        detail=f"Long sides, end panels and platforms; all walls at {plinth_cut} tall.",
        tools=["track saw"], materials=["3/4 plywood"], fasteners=[],
        tolerance="±1/32; opposite panels identical", sign_off="parts F–H match cut list")
    add(phase="Cut", title="Cut cement board skin panels",
        detail="Score-and-snap the skin panels per the cement-board nesting map.",
        tools=["carbide scoring knife", "P100 respirator"], materials=["1/4 cement board"], fasteners=[],
        tolerance="±1/16", sign_off="skin panels cut, dust contained",
        troubleshoot_ref="cement_dust")

    # ---- CORE / SLAB ----
    add(phase="Core", title="Lay out rib positions",
        detail="Mark rib left edges from a single datum: " + ", ".join(edges) + ".",
        tools=["tape", "square"], materials=[], fasteners=[],
        tolerance="cumulative from one datum, not tip-to-tip; ±1/32",
        sign_off="rib lines match layout drawing")
    add(phase="Core", title="Assemble core ring and ribs",
        detail="Glue and brad the ring and ribs into a flat grid on the bottom deck.",
        tools=["18ga brad nailer", "glue"], materials=["parts B–E"],
        fasteners=["18ga x 1in brad @ 4in o.c."],
        tolerance="frame flat within 1/32 across diagonal", sign_off="core square and flat",
        parts=("C", "D", "E"))
    add(phase="Slab", title="Close the torsion box",
        detail="Glue and brad the top deck to the core; clamp until flat.",
        tools=["clamps", "18ga brad nailer"], materials=["part A"],
        fasteners=["18ga x 1in brad @ 4in o.c."],
        tolerance="no light gap at any rib; box flat within 1/32",
        sign_off="slab rings solid when tapped", troubleshoot_ref="slab_rattle",
        parts=("A", "B"))

    # ---- PLINTH ----
    add(phase="Plinth", title="Assemble plinth box",
        detail="Butt-join long sides to end panels (mesh-reinforced corners), pilot and screw.",
        tools=["drill/driver", "impact driver"], materials=["parts F, G"],
        fasteners=["#8 x 2in cabinet screw, pilot 7/64, countersink"],
        tolerance="corners square within 1/64; diagonals equal",
        sign_off="plinth square, no racking", parts=("F", "G"))
    add(phase="Plinth", title="Install platforms",
        detail="Pocket-screw top and bottom platforms into the plinth walls.",
        tools=["pocket-hole jig", "drill/driver"], materials=["part H"],
        fasteners=["1-1/4in pocket screw @ 6in o.c."],
        tolerance="platforms flush and level", sign_off="platforms fixed, box rigid",
        parts=("H",))

    # ---- DRY FIT ----
    add(phase="Dry fit", title="Dry-fit slab on plinth",
        detail=f"Center the slab; confirm the plinth sits inset {inset_asm} as-assembled per side.",
        tools=["tape"], materials=[], fasteners=[],
        tolerance=f"inset {inset_asm} ± 1/32 all four sides, symmetric",
        sign_off="reveal even on all sides", troubleshoot_ref="uneven_reveal")

    # ---- SUBSTRATE ----
    add(phase="Substrate", title="Fasten cement board — slab",
        detail="Skin every exposed slab face; continuous backing behind the underside reveal band.",
        tools=["drill/driver"], materials=["1/4 cement board"],
        fasteners=["1-1/4in cement-board screw @ 6in o.c. — NO drywall screws"],
        tolerance="boards tight, seams < 1/16", sign_off="slab fully backed",
        troubleshoot_ref="drywall_screw")
    add(phase="Substrate", title="Fasten cement board — plinth",
        detail="Skin the four plinth sides; leave the concealed top and floor-bearing bottom bare.",
        tools=["drill/driver"], materials=["1/4 cement board"],
        fasteners=["1-1/4in cement-board screw @ 6in o.c."],
        tolerance="boards tight, corners meshed", sign_off="plinth sides backed")
    add(phase="Substrate", title="Tape and mesh all seams",
        detail="Alkali-resistant mesh tape and thin-set over every seam and corner.",
        tools=["margin trowel"], materials=["mesh tape", "thin-set"], fasteners=[],
        tolerance="seams filled flush, no ridges", sign_off="seams invisible under a straightedge")

    # ---- OFFCUT-CLAIMED PRACTICE PANEL (Lesson 12) ----
    claimed = _claim_practice_panel(plan)
    if claimed:
        add(phase="Finish", title="Practice panel FIRST (claimed offcut)",
            detail=(f"Trowel a full microcement cycle on the claimed {claimed} cement-board "
                    "offcut before touching the table. The first panel anyone trowels is the "
                    "worst they will ever trowel — spend it here."),
            tools=["stainless trowel", "orbital sander"], materials=["claimed offcut", "microcement"],
            fasteners=[], tolerance="two base coats + top coat, sanded 220/400",
            sign_off="practice panel complete before table finish begins")

    # ---- FINISH ----
    add(phase="Finish", title="Base coats",
        detail="Two thin microcement base coats over the whole piece, sanding between.",
        tools=["stainless trowel", "orbital sander"], materials=["microcement base"], fasteners=[],
        tolerance="even build, no trowel chatter", sign_off="base coats uniform",
        troubleshoot_ref="trowel_chatter")
    add(phase="Finish", title="Top coat",
        detail="Final microcement top coat; feather the underside reveal band cleanly.",
        tools=["stainless trowel"], materials=["microcement top"], fasteners=[],
        tolerance="consistent color and texture", sign_off="top coat complete")
    add(phase="Finish", title="Seal",
        detail="Two coats of penetrating sealer, then a matte topcoat.",
        tools=["foam applicator"], materials=["sealer"], fasteners=[],
        tolerance="no pinholes or holidays", sign_off="sealed and cured to touch")

    # ---- CURE / QC ----
    add(phase="Cure", title="Full cure",
        detail="Hold the piece undisturbed per the cure schedule before use.",
        tools=[], materials=[], fasteners=[],
        tolerance="ambient 65–75°F, moderate humidity", sign_off="cure clock complete")
    add(phase="QC", title="Final QC and sign-off",
        detail="Walk the QC checklist: reveal symmetry, overall height, finish integrity.",
        tools=["tape", "straightedge"], materials=[], fasteners=[],
        tolerance=f"overall height {fmt_inches(geo.scalar('overall_height'))} ± 1/16",
        sign_off="all QC items pass", troubleshoot_ref="qc_fail")

    return steps


def _claim_practice_panel(plan: NestingPlan) -> str:
    for o in plan.offcut_manifest():
        if min(o["w"], o["h"]) >= 9.0 and o["w"] * o["h"] >= 9 * 18:
            return f'{fmt_inches(o["w"])} x {fmt_inches(o["h"])}'
    return ""
