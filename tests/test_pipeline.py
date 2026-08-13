"""Phase 7-10 acceptance — question graph, intake, persistence, build mode,
and the architecture-extensibility check (Definition of Done, final item)."""

from __future__ import annotations

import json
import os

from build_assistant.core.solver import solve, solve_hash
from build_assistant.schema.registry import default_registry
from build_assistant.elicitation.question_graph import UIContractError, Turn
from build_assistant.elicitation.llm import LLMBoundary, DeterministicStubClient, LLMBoundaryError
from build_assistant.elicitation.intake import classify, completeness_gate, ai_judge
from build_assistant.persistence.answer_set import AnswerSet
from build_assistant.persistence.revisions import revise
from build_assistant.build_mode.runner import start_build
from build_assistant.nesting.plan import plan_nesting

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "coffee_table_reference.json")


# ---- Phase 7: question graph ----

def test_geometric_before_appearance():
    reg = default_registry()
    graph = reg.question_graph("coffee_table")
    turn = graph.next_turn({"node": "coffee_table"})
    fields = [q.field for q in turn.questions]
    # first turn is dimensions (highest downstream_impact), never colour/sheen
    assert "overall_length" in fields
    assert "finish_color" not in fields and "finish_sheen" not in fields
    print(f"  [ok] first turn is geometric: {fields}")


def test_ui_contract_enforced():
    # max 3 questions per turn
    reg = default_registry()
    graph = reg.question_graph("coffee_table")
    turn = graph.next_turn({"node": "coffee_table"})
    assert len(turn.questions) <= 3
    try:
        Turn(turn.questions + turn.questions)   # >3
        raise AssertionError("expected UIContractError")
    except UIContractError:
        pass
    print("  [ok] UI contract enforced in code (<=3 questions/turn)")


def test_conditional_question_opens():
    reg = default_registry()
    graph = reg.question_graph("coffee_table")
    # plinth_inset only appears once base_type == plinth
    base = {"node": "coffee_table", "overall_length": 42, "overall_width": 20,
            "overall_height": 16, "slab_edge_thickness": 3}
    no_plinth = dict(base, base_type="legs", finish_system="paint_buildup", assembly="single_monolith")
    fields = graph.unanswered_required(no_plinth)
    assert "plinth_inset" not in fields, fields
    with_plinth = dict(base, base_type="plinth", finish_system="paint_buildup", assembly="single_monolith")
    assert "plinth_inset" in graph.unanswered_required(with_plinth)
    print("  [ok] conditional question opens on answer (plinth_inset)")


# ---- Phase 8: LLM boundary, intake, completeness ----

def test_llm_boundary_rejects_invalid():
    class BadClient:
        def complete(self, prompt, purpose):
            return "not json"
    b = LLMBoundary(BadClient(), retries=1)
    try:
        b.call("x", "intake", {"type": "object", "required": ["a"], "properties": {}})
        raise AssertionError("expected LLMBoundaryError")
    except LLMBoundaryError:
        pass
    print("  [ok] LLM boundary rejects non-schema output, fails loud")


def test_intake_disambiguation_required():
    reg = default_registry()
    b = LLMBoundary(DeterministicStubClient(reg))
    res = classify("I want a micro concrete top for my living room", b, reg)
    assert res.ambiguities, "micro concrete must be flagged ambiguous"
    terms = [a["term"] for a in res.ambiguities]
    assert "micro concrete" in terms
    assert res.needs_disambiguation()
    print(f"  [ok] intake surfaces ambiguity, never silently picks: {terms}")


def test_unknown_goes_to_review_queue():
    reg = default_registry()
    b = LLMBoundary(DeterministicStubClient(reg))
    res = classify("a flux capacitor housing", b, reg)
    assert res.review_queue, "unknown request must go to review queue"
    print("  [ok] unknown node -> review queue (no improvised schema shipped)")


def test_ai_judge_cannot_approve():
    reg = default_registry()
    b = LLMBoundary(DeterministicStubClient(reg))
    v = ai_judge("coffee_table", {"overall_length": 42}, b)
    assert v.approved is False, "AI judge may request but never approve"
    print("  [ok] AI judge may request, may not approve")


def test_completeness_needs_deterministic_pass():
    reg = default_registry()
    full = json.load(open(FIXTURE))
    answers = {k: v for k, v in full.items() if k != "node"}
    approved, verdicts = completeness_gate("coffee_table", answers, reg)
    assert approved, [v.reasons for v in verdicts]
    # missing a required field -> not approved
    partial = dict(answers); partial.pop("finish_system")
    approved2, _ = completeness_gate("coffee_table", partial, reg)
    assert not approved2
    print("  [ok] completeness approval requires the deterministic judge")


# ---- Phase 9: persistence ----

def test_answer_set_append_only():
    a = AnswerSet("coffee_table")
    a.append_turn({"overall_length": 42})
    try:
        a.append_turn({"overall_length": 48})   # overwrite attempt
        raise AssertionError("append must not overwrite")
    except ValueError:
        pass
    # only revise() can change a value, and it mints a new version + letter
    v = a.revise({"overall_length": 48}, "user changed length")
    assert v.revision_letter == "B" and v.version == 2
    assert len(a.history()) == 3
    print("  [ok] answer sets are append-only; revise() mints a new version/letter")


def test_revision_full_resolve_and_diff():
    a = AnswerSet("coffee_table")
    full = json.load(open(FIXTURE))
    a.append_turn({k: v for k, v in full.items() if k != "node"})
    diff = revise(a, {"overall_length": 48}, "stretch the table")
    assert diff.from_letter == "A" and diff.to_letter == "B"
    assert diff.hash_before != diff.hash_after           # full re-solve changed output
    assert "slab.deck.length" in diff.scalar_changes     # downstream regenerated
    assert diff.scalar_changes["slab.deck.length"] == (41.25, 47.25)
    print(f"  [ok] revision: full re-solve + diff ({len(diff.changelog)} changelog lines)")


# ---- Phase 10: build mode ----

def test_build_mode_timestamped_signoffs():
    geo = solve(json.load(open(FIXTURE)))
    plan = plan_nesting(geo)
    clock = iter(range(1000))
    sess = start_build(geo, plan, clock=lambda: float(next(clock)))
    assert len(sess.steps) >= 18, len(sess.steps)
    while not sess.complete():
        sess.sign_off(True)
    assert all(s.timestamp is not None for s in sess.signoffs)
    durations = sess.phase_durations()
    assert durations, "phase durations derived from timestamps"
    print(f"  [ok] build mode: {len(sess.steps)} timestamped steps, "
          f"phase durations {len(durations)} phases")


def test_build_mode_failed_check_surfaces_troubleshooting():
    geo = solve(json.load(open(FIXTURE)))
    plan = plan_nesting(geo)
    sess = start_build(geo, plan, clock=lambda: 0.0)
    # advance to a step with a troubleshoot ref
    while sess.current() and not sess.current().troubleshoot_ref:
        sess.sign_off(True)
    so = sess.sign_off(False, "check failed")
    assert "troubleshooting" in so.note
    req = sess.report_wrong_dimension("overall_height", 15.5)
    assert req["action"] == "open_revision"
    print("  [ok] failed check surfaces troubleshooting; wrong dim opens a revision")


# ---- Definition of Done: add a node with schema+joinery only ----

def test_new_node_zero_engine_changes():
    """floating_shelf solves and nests through the unchanged solver/nesting engine."""
    ans = {"node": "floating_shelf", "overall_length": 48, "overall_depth": 10,
           "overall_thickness": 2.5, "finish_system": "paint_buildup"}
    geo = solve(ans)                        # same solve() as coffee_table
    assert geo.piece_count() == 9
    h1, h2 = solve_hash(geo), solve_hash(solve(ans))
    assert h1 == h2                          # deterministic
    plan = plan_nesting(geo)                 # same nesting engine
    assert plan.nests, "shelf nested through unchanged engine"
    # and a different node id is registered without touching solver internals
    reg = default_registry()
    assert set(reg.all_leaves()) == {"coffee_table", "floating_shelf"}
    print("  [ok] second leaf node added with schema+joinery only, zero engine changes")


def test_a_failed_design_says_something_a_person_can_act_on():
    """'PlacementError: part P03 has 1 instance(s) touching nothing' is exactly
    right for the repair loop and useless on a screen. The engine keeps its words
    in the log; the person gets a sentence, and the sentence names the move most
    likely to work — these designs are drawn fresh each run, so a failure is often
    just this run."""
    from webapp.server import _plain_failure
    msg = _plain_failure("the design did not resolve — PlacementError: part P03 "
                         "(Right Arm Front Post) has 1 instance(s) touching nothing")
    assert "P03" not in msg and "PlacementError" not in msg, msg
    assert "second run" in msg, msg
    stock = _plain_failure("InvariantError: part D (30.0x130.0) fits no stock size")
    assert "stock that is actually sold" in stock, stock
    # a gate hold is its own case: the package exists but Law 5 refuses to ship it
    gate = _plain_failure("held back by a release check — Gate 3: 1 visual defect(s) "
                          "(joint_d2: geometry (71.1, 57.0, 306.0, 618.7) exceeds "
                          "viewBox 520.0x260.0)")
    assert "viewBox" not in gate and "618.7" not in gate, gate
    assert "not released" in gate, gate
    # anything unrecognised still reaches the user rather than being swallowed
    odd = _plain_failure("sqlite3.OperationalError: database is locked")
    assert "database is locked" in odd, odd
    print("  [ok] a failed design is explained in words, with the move worth making")


def test_coming_back_mid_design_attaches_instead_of_starting_a_second_one():
    """The screen says 'you can leave and come back; it keeps going'. Coming back
    re-enters the generate endpoint, and a design takes twenty minutes — starting a
    second one over the top of the first wastes both and reports whichever finishes
    last."""
    import webapp.server as S

    class FakeStore:
        def __init__(self): self.started = 0; self.state = {"status": "running"}
        def job(self, pid): return self.state
        def start_job(self, pid, n): self.started += 1
        def set_status(self, pid, s): pass
        def answers(self, pid): return {"node": S.GENERATIVE}

    store, real = FakeStore(), S.STORE
    real_worker = S._run_generation
    S.STORE = store
    # The non-attached branch starts the real worker on a thread; this test is
    # about the branch taken, not the design run, and a background thread failing
    # against a stub store prints a traceback into an otherwise clean suite.
    S._run_generation = lambda pid: None
    try:
        res = S.do_generate("p1")
        assert res.get("attached") and store.started == 0, res
        store.state = {"status": "failed"}          # a finished job may be re-run
        S.do_generate("p1")
        assert store.started == 1
    finally:
        S.STORE, S._run_generation = real, real_worker
    print("  [ok] returning to a running design attaches to it, does not restart it")


def test_a_released_project_can_have_a_number_changed_and_be_rebuilt():
    """A released packet used to be final: someone who wanted the 84in sofa at 90
    had to start a new project and answer everything again. The answer store is
    versioned and append-only, so this was always supported underneath — it just
    was not reachable, because every answer was shown read-only."""
    import webapp.server as S
    known = S._known_summary(None, {"node": "__designed__", "overall_width": 84.0,
                                    "wood_species": "poplar"})
    by = {k["label"]: k for k in known}
    assert "Node" not in by
    width = by["Width"]
    assert width["numeric"] and width["field"] == "overall_width", width
    # a choice is not offered as a free-text number to retype
    assert not by["Wood Species"]["numeric"]
    print("  [ok] answers carry their field and type, so a number can be changed")
