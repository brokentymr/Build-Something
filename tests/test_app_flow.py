"""The app's own flow: any description is buildable, questions are tailored to it,
and generation reports where it actually is.

Deterministic — no API key. The agent calls are stubbed; what is under test is the
app's contract around them.
"""

from __future__ import annotations

import os

from webapp.db import Store


def _store(tmp="out/_flowtest.db"):
    if os.path.exists(tmp):
        os.remove(tmp)
    return Store(tmp)


def test_any_description_gets_a_project_not_a_rejection():
    """The app used to answer "we don't have a template for that yet" — to a user
    who had just described exactly what they wanted."""
    from webapp import server
    store = _store()
    server.STORE = store
    pid = store.create_project(None, "shoe bench")
    res = server.do_intake(pid, "a hexagonal plant stand for a corner")
    assert res["outcome"] == "resolved", res
    assert res.get("generative") is True
    assert store.answers(pid)["node"] == server.GENERATIVE
    print("  [ok] a build with no template is accepted, not refused")


def test_a_template_is_offered_never_assumed():
    """"A shoe bench with a lower shelf" keyword-matched the floating shelf and
    would have been built as one — the exact failure the agent exists to end."""
    from webapp import server
    store = _store()
    server.STORE = store
    pid = store.create_project(None, "shoe bench")
    res = server.do_intake(pid, "an entryway shoe bench with a lower shelf")
    assert res["outcome"] == "offer_template", res
    assert res["node"] == "floating_shelf"
    # until they choose, the project belongs to the agent, not the template
    assert store.answers(pid)["node"] == server.GENERATIVE
    print("  [ok] a matching template is offered as a choice, not silently applied")


def test_agent_questions_obey_the_ui_contract():
    """The model writes the question set, so the app enforces its own contract on
    it: at most three a turn, a usable control on each, no repeated fields."""
    from webapp.designer import _clean_turns
    turns = _clean_turns([{"questions": [
        {"field": "width", "prompt": "How wide?", "type": "number", "presets": [24, 32]},
        {"field": "style", "prompt": "Which look?", "type": "choice",
         "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}]},
        {"field": "dead", "prompt": "Only one option?", "type": "choice",
         "options": [{"value": "x", "label": "X"}]},
        {"field": "width", "prompt": "How wide again?", "type": "number", "presets": [1]},
        {"field": "fourth", "prompt": "Too many", "type": "number", "presets": [1]},
    ]}])
    fields = [q["field"] for q in turns[0]["questions"]]
    assert fields == ["width", "style"], fields
    assert all(q["options"] or q["numeric_presets"] for q in turns[0]["questions"])
    print("  [ok] agent-authored questions are clamped to the UI contract")


def test_generative_state_walks_the_agents_turns():
    from webapp import server
    store = _store()
    server.STORE = store
    pid = store.create_project(None, "shoe bench")
    store.set_node(pid, server.GENERATIVE)
    store.save_questions(pid, [
        {"questions": [{"field": "width", "prompt": "How wide?", "type": "number",
                        "required": True, "options": [], "numeric_presets": [40]}]},
        {"questions": [{"field": "finish", "prompt": "Finish?", "type": "choice",
                        "required": True,
                        "options": [{"value": "paint", "label": "Paint"}],
                        "numeric_presets": []}]},
    ])
    st = server.project_state(pid)
    assert st["turn"]["questions"][0]["field"] == "width"
    assert st["can_generate"] is False and st["progress"]["total"] == 2

    store.add_answers(pid, {"width": 40}, "turn")
    st = server.project_state(pid)
    assert st["turn"]["questions"][0]["field"] == "finish", "must advance to turn 2"

    store.add_answers(pid, {"finish": "paint"}, "turn")
    st = server.project_state(pid)
    assert st["turn"] is None and st["can_generate"] is True
    print("  [ok] the agent's question set drives the same three-at-a-time flow")


def test_progress_reports_a_phase_the_worker_reached():
    """The old progress list advanced on a 550ms timer regardless of what was
    happening — fine at four seconds, a lie at eight minutes."""
    store = _store()
    pid = store.create_project(None, "x")
    store.start_job(pid, 7)
    assert store.job(pid)["status"] == "running"
    store.set_job_phase(pid, "repairing", "round 2: parts do not fit together yet")
    job = store.job(pid)
    assert job["phase"] == "repairing" and "round 2" in job["detail"]
    store.finish_job(pid, "a release gate failed")
    assert store.job(pid)["status"] == "failed"
    print("  [ok] the job reports real phases, and failure is reportable")


def test_photos_reach_the_model_as_images():
    from webapp.designer import _image_blocks
    blocks = _image_blocks([
        "data:image/jpeg;base64,AAAA",
        "data:image/tiff;base64,BBBB",       # unsupported type — dropped, not sent
        "not a data url", "",
    ])
    assert len(blocks) == 1
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    print("  [ok] inspiration photos are passed to the model, unusable ones dropped")


def test_a_project_with_no_resolved_node_is_the_agents_to_build():
    """A description that only reached disambiguation left the project with no
    node, and generate then ran the curated completeness audit on it and 500'd."""
    from webapp import server
    store = _store()
    server.STORE = store
    pid = store.create_project(None, "something unusual")
    assert store.answers(pid).get("node") is None
    res = server.do_generate(pid)
    assert res.get("started") is True, res
    assert store.answers(pid)["node"] == server.GENERATIVE
    job = store.job(pid)
    assert job and job["status"] in ("running", "failed", "done")
    print("  [ok] an unresolved project is designed rather than crashing generate")


def test_the_store_survives_concurrent_use():
    """The server is threaded and generation runs on a worker. One shared
    connection had requests interleaving inside a transaction — "cannot start a
    transaction within a transaction", a 500 to whoever lost the race."""
    import threading
    store = _store("out/_concurrent.db")
    pids = [store.create_project(None, f"p{i}") for i in range(4)]
    errors = []

    def hammer(pid, n):
        try:
            for i in range(12):
                store.set_description(pid, f"description {n}-{i}")
                store.add_answers(pid, {f"f{i}": i}, "turn")
                store.start_job(pid, 7)
                store.set_job_phase(pid, "designing", f"round {i}")
                store.answers(pid)
                store.job(pid)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=hammer, args=(pid, n))
               for n, pid in enumerate(pids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[:3]
    print("  [ok] the store takes concurrent readers and writers without collapsing")


def test_a_connection_brings_its_own_schema():
    """The schema was applied once, in the constructing thread, on the assumption
    the file would always already have it. A database that went missing under a
    running server then answered "no such table: projects" to every later thread."""
    import os
    import threading
    path = "out/_schema_probe.db"
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    store = Store(path)
    store.create_project(None, "before")

    for suffix in ("", "-wal", "-shm"):        # the file goes away underneath it
        if os.path.exists(path + suffix):
            os.remove(path + suffix)

    result = {}

    def fresh_thread():
        try:
            result["pid"] = store.create_project(None, "after")
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"

    t = threading.Thread(target=fresh_thread)
    t.start()
    t.join()
    assert "error" not in result, result["error"]
    assert result.get("pid")
    print("  [ok] a new connection creates the schema it needs")


def test_a_reply_cut_off_at_the_ceiling_gets_more_room():
    """A sofa frame is a bigger model than a bookshelf, and synthesis ran out of
    room mid-part. It reported "did not return valid JSON", so the retry asked for
    valid JSON when what it needed was a larger budget."""
    from webapp.designer import DesignAgent
    agent = DesignAgent()
    calls = []

    def fake_llm(system, user, max_tokens=3000, images=None):
        calls.append(max_tokens)
        if len(calls) == 1:                      # truncated mid-object
            agent.last_stop_reason = "max_tokens"
            return '{"name": "sofa", "parts": [{"id": "A"'
        agent.last_stop_reason = "end_turn"
        return '{"name": "sofa", "parts": []}'

    agent._llm = fake_llm
    out = agent._llm_json("sys", "user", 6000)
    assert out["name"] == "sofa"
    assert calls[1] > calls[0], f"the retry must get more room: {calls}"
    print(f"  [ok] a truncated reply is retried with more room ({calls[0]} -> {calls[1]})")


def test_a_design_too_large_to_express_says_so():
    from webapp.designer import DesignAgent
    agent = DesignAgent()

    def always_truncated(system, user, max_tokens=3000, images=None):
        agent.last_stop_reason = "max_tokens"
        return '{"name": "runaway"'

    agent._llm = always_truncated
    try:
        agent._llm_json("sys", "user", 6000)
    except RuntimeError as exc:
        assert "ran past" in str(exc), str(exc)
        print("  [ok] a design that never fits says it ran out of room, not 'bad JSON'")
    else:
        raise AssertionError("expected a truncation error")


def test_an_unresolved_design_is_not_released():
    """A sofa 265 inches long reached a finished 19-page packet with all three
    gates green. The loop had reported it never resolved; the worker built it
    anyway, because it only checked that geometry existed."""
    from webapp import server
    from webapp.designer import DesignResult
    store = _store()
    server.STORE = store
    pid = store.create_project(None, "sofa")
    store.set_node(pid, server.GENERATIVE)

    class Stub:
        def design(self, *a, **k):
            return DesignResult(ir=None, geo=object(), converged=False, rounds=[],
                                error="PlacementError: asked 96in on x, lays out to 265.9in")

        def author_packet(self, *a, **k):
            raise AssertionError("must not write a packet for an unresolved design")

    real, server.DESIGNER = server.DESIGNER, Stub()
    try:
        server._design_generatively(pid, store.answers(pid), lambda *a, **k: None)
    except RuntimeError as exc:
        assert "did not resolve" in str(exc), str(exc)
        assert "265.9in" in str(exc), "the reason must travel with the refusal"
        print("  [ok] a design that never resolved is refused, not published")
    else:
        raise AssertionError("expected the unresolved design to be refused")
    finally:
        server.DESIGNER = real


def test_unresolved_notes_outrank_design_commentary():
    """The unresolved notes are appended last, so an eight-note cap threw away
    exactly the ones that mattered."""
    from build_assistant.generative.model import DesignIR
    from build_assistant.generative.compiler import compile_design
    from build_assistant.generative.document import build_blocks_generic
    from build_assistant.nesting.plan import plan_nesting
    from tests.test_details import _CASE
    spec = {**_CASE, "warnings": [f"design note {i}" for i in range(1, 9)]
                                 + ["Unresolved by the design loop: parts lay out to 265in"]}
    geo = compile_design(DesignIR.from_dict(spec))
    html = "".join(b.html for b in build_blocks_generic(geo, plan_nesting(geo), {}))
    assert "Unresolved by the design loop" in html, "the note that matters was dropped"
    print("  [ok] an unresolved note survives the cap that drops commentary")
