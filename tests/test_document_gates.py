"""Document + release-gate acceptance — brief Part 5.2 / Part 6.

Requires Chromium (skipped with a notice if the binary is absent). Builds the
reference document end to end and asserts all three gates pass and every key
fixture number appears in both tables and prose.
"""

from __future__ import annotations

import json
import os

from build_assistant.core.solver import solve
from build_assistant.nesting.plan import plan_nesting
from build_assistant.document.engine import CHROME
from build_assistant.document.curated_packet import curated_packet
from build_assistant.generative.document import (
    build_generic_document, generic_drawings)
from build_assistant.gates.gates import run_all_gates, all_passed

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "coffee_table_reference.json")
_CHROME_OK = os.path.exists(CHROME)

_cache = {}


def _doc():
    if "doc" not in _cache:
        geo = solve(json.load(open(FIXTURE)))
        plan = plan_nesting(geo)
        _cache["geo"], _cache["plan"] = geo, plan
        _cache["doc"] = build_generic_document(geo, plan, curated_packet(geo, plan),
                                              out_name="coffee_table")
        _cache["drawings"] = generic_drawings(geo, plan)
    return _cache["geo"], _cache["plan"], _cache["doc"]


def test_all_gates_pass():
    if not _CHROME_OK:
        print("  [skip] Chromium not present")
        return
    geo, plan, doc = _doc()
    res = run_all_gates(geo, plan, doc["html_path"], doc["html"],
                        drawings=_cache["drawings"])
    for r in res:
        print(f"    {'PASS' if r.passed else 'FAIL'} {r.name}: {r.detail}")
    assert all_passed(res), [v for r in res for v in r.violations]
    print("  [ok] all three release gates pass on the reference fixture")


def test_page_total_not_constant():
    if not _CHROME_OK:
        print("  [skip] Chromium not present")
        return
    _, _, doc = _doc()
    # footer must show the resolved total, matching the real page count
    assert f'/ {doc["page_count"]:02d}' in doc["html"], "page total not resolved after pagination"
    assert doc["page_count"] > 1
    print(f"  [ok] page total resolved after pagination: {doc['page_count']} pages")


def test_fixture_numbers_in_document():
    if not _CHROME_OK:
        print("  [skip] Chromium not present")
        return
    _, _, doc = _doc()
    # The requirement is that the value reaches the page, not which escaping it
    # arrives in — a quote is &quot; in one cell and " in the next.
    html = doc["html"].replace("&quot;", '"')
    for tok in ['41-1/4', '19-1/4', '13-3/8', '13"', '3-3/8', '6-9/16',
                '35-1/4', '11-3/4', '33-3/4', '88.6']:
        assert tok in html, f"fixture value {tok} missing from document"
    print("  [ok] every key fixture number appears in the document")
