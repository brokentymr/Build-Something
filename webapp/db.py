"""SQLite persistence — projects library, append-only answer versions, photos.

This is the database and knowledge-of-state layer for the app. Answer versions are
append-only (Law 3): a project's answers are reconstructed by folding its version
rows; changing a value writes a new version, never an UPDATE of an old one.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid

DB_PATH = os.environ.get("BUILD_ASSISTANT_DB", os.path.join("out", "build_assistant.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, node TEXT, title TEXT, status TEXT,
  revision TEXT DEFAULT 'A', created REAL, updated REAL
);
CREATE TABLE IF NOT EXISTS answer_versions (
  project_id TEXT, version INTEGER, answers_json TEXT, note TEXT, created REAL,
  PRIMARY KEY (project_id, version)
);
CREATE TABLE IF NOT EXISTS photos (
  id TEXT PRIMARY KEY, project_id TEXT, mime TEXT, data_url TEXT,
  caption TEXT, created REAL
);
CREATE TABLE IF NOT EXISTS documents (
  project_id TEXT, version INTEGER, pages INTEGER, gates_json TEXT,
  html_path TEXT, pdf_path TEXT, summary_json TEXT, created REAL,
  PRIMARY KEY (project_id, version)
);
"""


def _now() -> float:
    return time.time()


class Store:
    def __init__(self, path: str = DB_PATH):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.executescript(_SCHEMA)
        self._c.commit()

    # ---- projects ----
    def create_project(self, node: str | None, title: str) -> str:
        pid = uuid.uuid4().hex[:12]
        t = _now()
        self._c.execute(
            "INSERT INTO projects (id,node,title,status,revision,created,updated) "
            "VALUES (?,?,?,?,?,?,?)",
            (pid, node, title, "intake", "A", t, t))
        base = {"node": node} if node else {}
        self._c.execute(
            "INSERT INTO answer_versions (project_id,version,answers_json,note,created) "
            "VALUES (?,?,?,?,?)", (pid, 0, json.dumps(base), "created", t))
        self._c.commit()
        return pid

    def set_node(self, pid: str, node: str) -> None:
        self._append_answers(pid, {"node": node}, "node resolved")
        self._touch(pid, status="photos")

    def set_status(self, pid: str, status: str) -> None:
        self._touch(pid, status=status)

    def set_revision(self, pid: str, letter: str) -> None:
        self._c.execute("UPDATE projects SET revision=?, updated=? WHERE id=?",
                        (letter, _now(), pid))
        self._c.commit()

    def _touch(self, pid: str, status: str | None = None) -> None:
        if status:
            self._c.execute("UPDATE projects SET status=?, updated=? WHERE id=?",
                            (status, _now(), pid))
        else:
            self._c.execute("UPDATE projects SET updated=? WHERE id=?", (_now(), pid))
        self._c.commit()

    def get_project(self, pid: str) -> dict | None:
        row = self._c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None

    def library(self) -> list[dict]:
        rows = self._c.execute(
            "SELECT * FROM projects ORDER BY updated DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["answers"] = self.answers(r["id"])
            d["photo_count"] = self.photo_count(r["id"])
            out.append(d)
        return out

    # ---- append-only answers ----
    def _append_answers(self, pid: str, new: dict, note: str) -> int:
        cur = self.answers(pid)
        merged = {**cur, **new}
        ver = self._next_version(pid)
        self._c.execute(
            "INSERT INTO answer_versions (project_id,version,answers_json,note,created) "
            "VALUES (?,?,?,?,?)", (pid, ver, json.dumps(merged), note, _now()))
        self._c.commit()
        self._touch(pid)
        return ver

    def add_answers(self, pid: str, new: dict, note: str = "turn") -> dict:
        self._append_answers(pid, new, note)
        return self.answers(pid)

    def _next_version(self, pid: str) -> int:
        row = self._c.execute(
            "SELECT MAX(version) m FROM answer_versions WHERE project_id=?", (pid,)).fetchone()
        return (row["m"] or 0) + 1

    def answers(self, pid: str) -> dict:
        row = self._c.execute(
            "SELECT answers_json FROM answer_versions WHERE project_id=? "
            "ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
        return json.loads(row["answers_json"]) if row else {}

    def version_count(self, pid: str) -> int:
        return self._c.execute(
            "SELECT COUNT(*) c FROM answer_versions WHERE project_id=?", (pid,)).fetchone()["c"]

    # ---- photos ----
    def add_photo(self, pid: str, mime: str, data_url: str, caption: str = "") -> str:
        phid = uuid.uuid4().hex[:12]
        self._c.execute(
            "INSERT INTO photos (id,project_id,mime,data_url,caption,created) VALUES (?,?,?,?,?,?)",
            (phid, pid, mime, data_url, caption, _now()))
        self._c.commit()
        self._touch(pid)
        return phid

    def photos(self, pid: str) -> list[dict]:
        rows = self._c.execute(
            "SELECT id,mime,data_url,caption FROM photos WHERE project_id=? ORDER BY created",
            (pid,)).fetchall()
        return [dict(r) for r in rows]

    def photo_count(self, pid: str) -> int:
        return self._c.execute(
            "SELECT COUNT(*) c FROM photos WHERE project_id=?", (pid,)).fetchone()["c"]

    # ---- documents ----
    def save_document(self, pid: str, version: int, pages: int, gates: list,
                      html_path: str, pdf_path: str, summary: dict) -> None:
        self._c.execute(
            "INSERT OR REPLACE INTO documents "
            "(project_id,version,pages,gates_json,html_path,pdf_path,summary_json,created) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, version, pages, json.dumps(gates), html_path, pdf_path,
             json.dumps(summary), _now()))
        self._c.commit()

    def latest_document(self, pid: str) -> dict | None:
        row = self._c.execute(
            "SELECT * FROM documents WHERE project_id=? ORDER BY version DESC LIMIT 1",
            (pid,)).fetchone()
        return dict(row) if row else None
