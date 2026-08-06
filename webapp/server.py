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
from build_assistant.elicitation.intake import classify

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")

REG = default_registry()
STORE = Store()
BOUNDARY, AI_MODE = get_boundary(REG)


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
        state["turn"] = _turn_json(turn) if turn else None
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
    res = classify(text, BOUNDARY, REG)
    if res.review_queue:
        return {"outcome": "unknown", "message": "We don't have a template for that yet — "
                "it's been sent to our review queue. Try one of the known types.",
                "known": REG.all_leaves()}
    if res.needs_disambiguation():
        options = []
        seen = set()
        for a in res.ambiguities:
            for c in a["constructions"]:
                key = c["construction"]
                if key not in seen:
                    seen.add(key)
                    options.append({"term": a["term"], "value": key, "note": c["note"]})
        cands = [c for c in res.candidates if c["confidence"] >= 0.4]
        for c in cands:
            options.append({"value": c["node"], "note": REG.schema(c["node"])["display_name"]
                            if REG.is_leaf(c["node"]) else c["node"]})
        return {"outcome": "disambiguate", "message":
                "That maps to more than one thing — which did you mean?", "options": options}
    node = res.resolved_node()
    if node:
        STORE.set_node(pid, node)
        return {"outcome": "resolved", "node": node}
    # single candidate fallback
    if res.candidates and res.candidates[0]["node"] in REG.all_leaves():
        node = res.candidates[0]["node"]
        STORE.set_node(pid, node)
        return {"outcome": "resolved", "node": node}
    return {"outcome": "unknown", "message": "Tell us a bit more.", "known": REG.all_leaves()}


def do_generate(pid: str) -> dict:
    from build_assistant.document.engine import build_document, render_pdf
    from build_assistant.gates.gates import run_all_gates, all_passed
    answers = STORE.answers(pid)
    node = answers.get("node")
    STORE.set_status(pid, "generating")
    geo = solve(answers)
    plan = plan_nesting(geo)
    doc = build_document(geo, plan, out_name=f"project_{pid}")
    gates = run_all_gates(geo, plan, doc["html_path"], doc["html"])
    gates_json = [{"name": g.name, "passed": g.passed, "detail": g.detail} for g in gates]
    if not all_passed(gates):
        STORE.set_status(pid, "configuring")
        return {"released": False, "gates": gates_json,
                "message": "Law 5: a release gate failed — not released."}
    pdf_path = os.path.join("out", f"project_{pid}.pdf")
    render_pdf(doc["html_path"], pdf_path)
    from build_assistant.document.engine import render_cover
    render_cover(doc["html_path"], os.path.join("out", f"project_{pid}_cover.png"))
    summary = _summary(geo, plan, doc)
    STORE.save_document(pid, STORE.version_count(pid), doc["page_count"],
                        gates_json, doc["html_path"], pdf_path, summary)
    STORE.set_status(pid, "released")
    return {"released": True, "gates": gates_json, "summary": summary,
            "pdf_url": f"/api/projects/{pid}/document.pdf", "pages": doc["page_count"]}


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
