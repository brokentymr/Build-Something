#!/usr/bin/env python3
"""End-to-end Build Assistant pipeline driver.

Runs the deterministic core on a fixture and, unless ``--no-render`` is passed,
renders the PDF and runs all three release gates. Law 5: no document releases with
a failing gate — this driver refuses to emit a PDF path as "released" unless every
gate passed.

    python build.py [fixtures/coffee_table_reference.json] [--no-render]
"""

from __future__ import annotations

import json
import os
import sys

from build_assistant.core.solver import solve, solve_hash
from build_assistant.nesting.plan import plan_nesting


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    flags = {a for a in argv[1:] if a.startswith("--")}
    fixture = args[0] if args else "fixtures/coffee_table_reference.json"
    answers = json.load(open(fixture))

    print(f"== Build Assistant :: {answers['node']} ==\n")

    # ---- Phases 1-3: solve + parts + nesting (pure, no LLM) ----
    geo = solve(answers)
    print(f"Solve hash        : {solve_hash(geo)[:16]}")
    print(f"Parts             : {geo.part_type_count()} types / {geo.piece_count()} pieces")
    print(f"Per-face offset   : {geo.per_face_offset}")
    if "plinth.carcass_height.as_cut" in geo.scalars:
        print(f"Overall height    : {geo.scalar('overall_height')}  "
              f"(plinth {geo.scalar('plinth.carcass_height.as_cut')} as_cut / "
              f"{geo.scalar('plinth.height.as_finished')} as_finished)")
    else:
        print(f"Overall height    : {geo.scalar('overall_height')}")
    plan = plan_nesting(geo)
    for mid, n in plan.nests.items():
        print(f"Nest {mid:22s}: {n.sheet_count()} sheet(s), "
              f"{n.total_utilisation()*100:.1f}% util, cut-order={n.cut_order_constrained()}")
    print(f"Claimable offcuts : {len(plan.offcut_manifest())}")
    print("\nDerived (not asked):")
    for d in geo.derived_decisions:
        print(f"  - {d.label}: {d.value}")

    if "--no-render" in flags:
        print("\n[--no-render] skipping document + gates")
        return 0

    # ---- Phases 4-6: drawings + document + gates ----
    from build_assistant.document.engine import build_document, render_pdf
    from build_assistant.gates.gates import run_all_gates, all_passed
    print("\nBuilding document (two-pass layout via Chromium)...")
    doc = build_document(geo, plan)
    print(f"Pages             : {doc['page_count']}")
    results = run_all_gates(geo, plan, doc["html_path"], doc["html"])
    print("\nRelease gates:")
    for r in results:
        print(f"  [{'PASS' if r.passed else 'FAIL'}] {r.name}: {r.detail}")
        for v in r.violations[:5]:
            print(f"       - {v}")

    if not all_passed(results):
        print("\nLaw 5: a gate failed — document is NOT released.")
        return 1

    pdf = render_pdf(doc["html_path"], os.path.join("out", "coffee_table.pdf"))
    print(f"\nAll gates passed. Released: {pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
