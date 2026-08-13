"""Stdlib HTTP server for the Build Assistant mobile web app.

Zero third-party dependencies. Serves the mobile SPA and a small JSON API that
drives the existing deterministic engine: intake -> photos -> guided
multiple-choice turns -> generate -> PDF. State lives in SQLite (webapp/db.py).

Run:  python -m webapp.server  [--port 8000]
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from build_assistant.core.solver import solve
from build_assistant.nesting.plan import plan_nesting
from build_assistant.schema.registry import default_registry
from build_assistant.catalog.materials import all_materials
from build_assistant.catalog.finishes import all_finishes
from build_assistant.build_mode.runner import structural_notice
from .db import Store
from .ai import get_boundary
from .agent import BuildAgent
from .designer import DesignAgent

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

#: Node id for a build the agent designs from the description, with no template.
GENERATIVE = "__designed__"

REG = default_registry()
STORE = Store()
BOUNDARY, AI_MODE = get_boundary(REG)
AGENT = BuildAgent(BOUNDARY, REG)
DESIGNER = DesignAgent()


# --------------------------------------------------------------------------
# state assembly
# --------------------------------------------------------------------------

def project_state(pid: str) -> dict:
    proj = STORE.get_project(pid)
    if not proj:
        return {"error": "not found"}
    answers = STORE.answers(pid)
    node = answers.get("node")
    state = {
        "id": pid, "title": proj["title"], "status": proj["status"],
        "node": node, "revision": proj["revision"],
        "answers": {k: v for k, v in answers.items() if k != "node"},
        "photos": STORE.photos(pid),
        "ai_mode": AI_MODE,
    }
    if node == GENERATIVE:
        return _generative_state(pid, proj, state, answers)
    if node:
        schema = REG.schema(node)
        state["node_display"] = schema["display_name"]
        state["structural_notice"] = structural_notice(node, REG)
        graph = REG.question_graph(node)
        req = schema["required_fields"]
        answered_req = [f for f in req if f in answers]
        state["progress"] = {"answered": len(answered_req), "total": len(req)}
        state["can_generate"] = graph.is_complete(answers)
        turn = graph.next_turn(answers)
        if turn:
            tj = _turn_json(turn)
            # tailor each question's wording to the user's description (phrasing only)
            desc = STORE.get_description(pid)
            tailored = AGENT.tailor(node, desc, turn.questions) if desc else {}
            for q in tj["questions"]:
                if q["id"] in tailored:
                    q["prompt"] = tailored[q["id"]]
                    q["tailored"] = True
            state["turn"] = tj
        else:
            state["turn"] = None
        # restate what is already known (Phase 9 resume behaviour)
        state["known"] = _known_summary(node, answers)
        doc = STORE.latest_document(pid)
        if doc:
            state["document"] = {
                "pages": doc["pages"], "pdf_url": f"/api/projects/{pid}/document.pdf",
                "gates": json.loads(doc["gates_json"]),
                "summary": json.loads(doc["summary_json"]),
            }
    return state


def _generative_state(pid: str, proj: dict, state: dict, answers: dict) -> dict:
    """State for a build with no template: the agent's own question set drives it.

    The curated path walks a hand-written question graph. Here the questions were
    authored for this object, stored once, and answered in the same three-at-a-time
    turns — so the screen is identical and only the source of the questions differs.
    """
    state["node_display"] = proj["title"] or "Your build"
    state["generative"] = True
    state["structural_notice"] = None
    turns = STORE.questions(pid)
    if not turns:
        # planned on demand, after photos, so the agent can see them
        state["turn"] = None
        state["progress"] = {"answered": 0, "total": 0}
        state["can_generate"] = False
        state["planning"] = True
        state["known"] = _known_summary(None, answers)
        return _with_document(pid, state)

    asked = [q for t in turns for q in t["questions"]]
    answered = [q for q in asked if q["field"] in answers]
    state["progress"] = {"answered": len(answered), "total": len(asked)}
    pending = next((t for t in turns
                    if any(q["field"] not in answers for q in t["questions"])), None)
    if pending:
        state["turn"] = {"questions": [q for q in pending["questions"]
                                       if q["field"] not in answers]}
    else:
        state["turn"] = None
    required = [q["field"] for q in asked if q.get("required", True)]
    state["can_generate"] = all(f in answers for f in required)
    state["known"] = _known_summary(None, answers)
    return _with_document(pid, state)


def _with_document(pid: str, state: dict) -> dict:
    doc = STORE.latest_document(pid)
    if doc:
        state["document"] = {
            "pages": doc["pages"], "pdf_url": f"/api/projects/{pid}/document.pdf",
            "gates": json.loads(doc["gates_json"]),
            "summary": json.loads(doc["summary_json"]),
        }
    return state


def _turn_json(turn) -> dict:
    return {"questions": [{
        "id": q.id, "field": q.field, "prompt": q.prompt, "type": q.type,
        "required": q.required, "unit": q.unit,
        "options": [{"value": o.value, "label": o.label} for o in q.options],
        "numeric_presets": list(q.numeric_presets),
        "explain": q.explain_on_request,
    } for q in turn.questions]}


_LABELS = {
    "overall_length": "Length", "overall_width": "Width", "overall_depth": "Depth",
    "overall_height": "Height", "overall_thickness": "Thickness",
    "slab_edge_thickness": "Top edge", "base_type": "Base", "finish_system": "Finish",
    "plinth_inset": "Reveal", "assembly": "Assembly", "finish_color": "Colour",
    "finish_sheen": "Sheen",
}


def _known_summary(node: str, answers: dict) -> list[dict]:
    out = []
    for k, v in answers.items():
        if k == "node":
            continue
        label = _LABELS.get(k, k.replace("_", " ").title())
        out.append({"label": label, "value": str(v)})
    return out


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------

def do_intake(pid: str, text: str) -> dict:
    """Measure 1: decompose the description, prefill what was stated, and route."""
    STORE.set_description(pid, text)
    report = AGENT.intake(text)
    # ambiguity must be resolved before we proceed — never silently pick (7.4)
    if report.ambiguities:
        options, seen = [], set()
        for a in report.ambiguities:
            for c in a.get("constructions", []):
                key = c.get("construction")
                if key and key not in seen:
                    seen.add(key)
                    options.append({"term": a.get("term"), "value": key, "note": c.get("note", "")})
        if report.node:
            options.append({"value": report.node, "note": REG.schema(report.node)["display_name"]})
        if options:
            STORE.set_node(pid, GENERATIVE)
            return {"outcome": "disambiguate", "message":
                    "That maps to more than one thing — which did you mean?",
                    "options": options}
    # A template is an offer, never an assumption. "A shoe bench with a lower
    # shelf" keyword-matched the floating shelf and would have been built as one —
    # the exact failure the design agent exists to end. When a template looks like
    # a match we say so and let them choose; the agent designs anything either way.
    if report.node and report.node in REG.all_leaves():
        STORE.set_node(pid, GENERATIVE)
        if report.extracted:
            STORE.add_answers(pid, report.extracted, "prefilled from description")
        return {"outcome": "offer_template", "node": report.node,
                "node_display": REG.schema(report.node)["display_name"],
                "extracted": report.extracted_display, "notes": report.audit_notes,
                "confidence": report.confidence,
                "message": f"We have a verified template for a "
                           f"{REG.schema(report.node)['display_name'].lower()}. "
                           f"Use it, or design yours from your description?"}
    # No template for it — which is the normal case, not the exception. The design
    # agent takes it from here: it works from the description itself, so the app
    # can build things nobody wrote a template for.
    STORE.set_node(pid, GENERATIVE)                            # -> photos stage
    return {"outcome": "resolved", "node": GENERATIVE, "generative": True,
            "node_display": _title_from(text),
            "extracted": report.extracted_display,
            "notes": report.audit_notes + ["designed from your description"],
            "confidence": report.confidence}


def _title_from(text: str) -> str:
    """A short display name taken from what the user typed."""
    words = [w for w in str(text).strip().split() if w]
    if not words:
        return "Your build"
    title = " ".join(words[:6])
    return title[:1].upper() + title[1:]


PLAN_PHASES = ["planning", "designing", "reviewing", "repairing", "writing",
               "drawing", "paginating", "gates"]


def do_plan_questions(pid: str) -> dict:
    """Author the question set for a build with no template."""
    if STORE.questions(pid):
        return {"planned": True}
    description = STORE.get_description(pid)
    photos = [p["data_url"] for p in STORE.photos(pid)]
    try:
        turns = DESIGNER.plan_questions(description, photos=photos)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return {"planned": False, "error": str(exc)}
    if not turns:
        return {"planned": False, "error": "no questions produced"}
    STORE.save_questions(pid, turns)
    return {"planned": True, "turns": len(turns)}


def do_generate(pid: str) -> dict:
    """Start generation and return immediately.

    A curated build takes about four seconds and an agent-authored one takes
    minutes of design rounds, so neither runs inside the request — the client
    follows the job."""
    answers = STORE.answers(pid)
    node = answers.get("node")
    if node not in REG.all_leaves():
        # Anything that is not a registered template is the agent's to design —
        # including a project that never resolved to one. Running the curated
        # completeness audit on it raised a KeyError and 500'd the request.
        node = GENERATIVE
        if answers.get("node") != GENERATIVE:
            STORE.set_node(pid, GENERATIVE)
    if node != GENERATIVE:
        # Measure 2: completeness audit (two judges) before we solve/cut.
        approved, audit = AGENT.audit_ready(
            node, {k: v for k, v in answers.items() if k != "node"})
        if not approved:
            missing = sorted({m for v in audit for m in v["missing"]})
            return {"released": False, "audit": audit, "missing": missing,
                    "message": "Completeness audit found gaps — a few more answers needed."}
    STORE.set_status(pid, "generating")
    STORE.start_job(pid, len(PLAN_PHASES))
    threading.Thread(target=_run_generation, args=(pid,), daemon=True).start()
    return {"started": True, "job": STORE.job(pid)}


def _run_generation(pid: str) -> None:
    """The worker. Every phase it reports is one it has actually reached."""
    from build_assistant.document.engine import render_pdf, render_cover
    from build_assistant.document.curated_packet import curated_packet
    from build_assistant.generative.document import (
        build_generic_document, generic_drawings)
    from build_assistant.gates.gates import run_all_gates, all_passed

    def say(phase, detail=""):
        STORE.set_job_phase(pid, phase, detail)

    try:
        answers = STORE.answers(pid)
        node = answers.get("node")
        if node not in REG.all_leaves():
            geo, packet = _design_generatively(pid, answers, say)
        else:
            say("designing", "solving the geometry")
            geo = solve(answers)
            packet = curated_packet(geo, plan_nesting(geo))

        say("drawing", "plans, sections and joint details")
        plan = plan_nesting(geo)
        drawings = generic_drawings(geo, plan)

        say("paginating", "laying out the document")
        doc = build_generic_document(geo, plan, packet, out_name=f"project_{pid}")

        say("gates", "checking every number, page and drawing")
        gates = run_all_gates(geo, plan, doc["html_path"], doc["html"], drawings=drawings)
        gates_json = [{"name": g.name, "passed": g.passed, "detail": g.detail}
                      for g in gates]
        if not all_passed(gates):
            # Law 5 holds — but "a release gate failed" tells a user nothing. Name
            # the gate and the first thing it caught, so the failure is legible
            # both to them and to whoever has to fix it.
            failed = [g for g in gates if not g.passed]
            why = "; ".join(
                f"{g.name.split('—')[0].strip()}: {g.detail}"
                + (f" ({g.violations[0]})" if g.violations else "")
                for g in failed)
            STORE.set_status(pid, "configuring")
            STORE.finish_job(pid, f"held back by a release check — {why}")
            return

        pdf_path = os.path.join("out", f"project_{pid}.pdf")
        render_pdf(doc["html_path"], pdf_path)
        render_cover(doc["html_path"], os.path.join("out", f"project_{pid}_cover.png"))
        STORE.save_document(pid, STORE.version_count(pid), doc["page_count"],
                            gates_json, doc["html_path"], pdf_path,
                            _summary(geo, plan, doc))
        STORE.set_status(pid, "released")
        STORE.finish_job(pid)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        STORE.set_status(pid, "configuring")
        STORE.finish_job(pid, str(exc)[:300])


def _design_generatively(pid: str, answers: dict, say):
    """Run the design loop, then author the packet, reporting real phases."""
    description = STORE.get_description(pid)
    photos = [p["data_url"] for p in STORE.photos(pid)]
    clean = {k: v for k, v in answers.items() if k != "node"}
    res = DESIGNER.design(description, clean, photos=photos, progress=say)
    if res.geo is None:
        raise RuntimeError(res.error or "the design did not come together")
    if not res.converged:
        # The loop knows it failed and said so; releasing anyway is how a sofa
        # 265 inches long reached a finished packet with every gate green. A
        # design that did not come together is not a document.
        raise RuntimeError(
            "the design did not resolve — " + (res.error or "unknown")[:240])
    # keep the model that produced the packet, so a failure is diagnosable later
    try:
        os.makedirs("out", exist_ok=True)
        with open(os.path.join("out", f"project_{pid}_ir.json"), "w") as fh:
            json.dump(res.ir.to_dict(), fh, indent=1)
    except Exception:  # noqa: BLE001 — persistence must never fail a build
        pass
    say("writing", "writing the build instructions")
    packet = DESIGNER.author_packet(res.ir, res.geo)
    return res.geo, packet


def _summary(geo, plan, doc) -> dict:
    return {
        "part_types": geo.part_type_count(), "pieces": geo.piece_count(),
        "weight": geo.scalars.get("weight_estimate").value if "weight_estimate" in geo.scalars else None,
        "coated_area": geo.scalars.get("coated_area").value if "coated_area" in geo.scalars else None,
        "pages": doc["page_count"],
        "sheets": {mid: n.sheet_count() for mid, n in plan.nests.items()},
        "cut_order": plan.cut_order_constrained(),
        "derived": [{"label": d.label, "value": d.value, "basis": d.basis}
                    for d in geo.derived_decisions],
    }


def catalog_knowledge() -> dict:
    nodes = []
    for leaf in REG.all_leaves():
        s = REG.schema(leaf)
        nodes.append({"id": leaf, "display_name": s["display_name"], "mode": s["mode"]})
    return {
        "nodes": nodes,
        "materials": [{"id": m.id, "name": m.display_name, "actual": m.actual_thickness}
                      for m in all_materials()],
        "finishes": [{"id": f.id, "name": f.display_name, "offset": f.per_face_offset}
                     for f in all_finishes()],
        "ai_mode": AI_MODE,
    }


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "BuildAssistant/1.0"

    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- routing ----
    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/" or path == "/index.html":
                return self._file(os.path.join(STATIC, "index.html"), "text/html")
            if path.startswith("/static/"):
                fn = os.path.basename(path)
                ctype = "text/css" if fn.endswith(".css") else \
                        "application/javascript" if fn.endswith(".js") else "text/plain"
                return self._file(os.path.join(STATIC, fn), ctype)
            if path == "/api/catalog":
                return self._send(200, catalog_knowledge())
            if path == "/api/library":
                return self._send(200, {"projects": STORE.library()})
            if path.startswith("/api/projects/") and path.endswith("/document.pdf"):
                pid = path.split("/")[3]
                doc = STORE.latest_document(pid)
                if not doc or not os.path.exists(doc["pdf_path"]):
                    return self._send(404, {"error": "no document"})
                return self._file(doc["pdf_path"], "application/pdf")
            if path.startswith("/api/projects/") and path.endswith("/cover.png"):
                pid = path.split("/")[3]
                cover = os.path.join("out", f"project_{pid}_cover.png")
                if not os.path.exists(cover):
                    return self._send(404, {"error": "no cover"})
                return self._file(cover, "image/png")
            if path.startswith("/api/projects/") and path.endswith("/job"):
                pid = path.split("/")[3]
                return self._send(200, {"job": STORE.job(pid) or {}})
            if path.startswith("/api/projects/"):
                pid = path.split("/")[3]
                return self._send(200, project_state(pid))
            return self._send(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self._send(500, {"error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/projects/new":
                pid = STORE.create_project(None, body.get("title", "New build"))
                return self._send(200, {"id": pid})
            parts = path.split("/")
            if len(parts) >= 5 and parts[1] == "api" and parts[2] == "projects":
                pid, action = parts[3], parts[4]
                if action == "intake":
                    return self._send(200, do_intake(pid, body.get("text", "")))
                if action == "pick":
                    STORE.set_node(pid, body["node"])
                    return self._send(200, project_state(pid))
                if action == "photos":
                    STORE.add_photo(pid, body.get("mime", "image/jpeg"),
                                    body.get("data_url", ""), body.get("caption", ""))
                    return self._send(200, {"photos": STORE.photos(pid)})
                if action == "photos-done":
                    STORE.set_status(pid, "configuring")
                    return self._send(200, project_state(pid))
                if action == "answer":
                    STORE.add_answers(pid, body.get("answers", {}), "elicitation turn")
                    return self._send(200, project_state(pid))
                if action == "plan":
                    return self._send(200, do_plan_questions(pid))
                if action == "generate":
                    return self._send(200, do_generate(pid))
            return self._send(404, {"error": "not found"})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self._send(500, {"error": str(exc)})

    def _file(self, path, ctype):
        if not os.path.exists(path):
            return self._send(404, {"error": "not found"})
        with open(path, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv):
    port = 8000
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Build Assistant app on http://0.0.0.0:{port}  (AI: {AI_MODE})")
    srv.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
