"""Data model + SQLite persistence for the workflow engine.

Six entities (per the plan): Project, Run, Task, Assignment, Review, RunEvent.
Plain relational tables via stdlib sqlite3 — no ORM. JSON columns for the few
list fields. Portable enough to swap SQLite -> Postgres later.

# ponytail: stdlib sqlite3 + dict rows. No ORM, no migrations framework; the
# schema is created if missing. Add Alembic only if the schema starts churning.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "omni.db"


# --- state constants -------------------------------------------------------

class RunStatus:
    PLANNING = "PLANNING"; RUNNING = "RUNNING"; REVIEWING = "REVIEWING"
    INTEGRATING = "INTEGRATING"; WAITING_FOR_USER = "WAITING_FOR_USER"
    COMPLETED = "COMPLETED"; FAILED = "FAILED"; CANCELLED = "CANCELLED"


class TaskStatus:
    PLANNED = "PLANNED"; READY = "READY"; RUNNING = "RUNNING"
    REVIEW_READY = "REVIEW_READY"; REVIEWING = "REVIEWING"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"; APPROVED = "APPROVED"; FAILED = "FAILED"
    CANCELLED = "CANCELLED"; WAITING_FOR_REVIEW = "WAITING_FOR_REVIEW"


class AssignmentStatus:
    ASSIGNED = "ASSIGNED"; RUNNING = "RUNNING"; DONE = "DONE"
    FAILED = "FAILED"; CANCELLED = "CANCELLED"


class Role:
    IMPLEMENT = "IMPLEMENT"; REVIEW = "REVIEW"; EXPLORE = "EXPLORE"; VALIDATE = "VALIDATE"


class Verdict:
    APPROVED = "APPROVED"; CHANGES_REQUESTED = "CHANGES_REQUESTED"; BLOCKED = "BLOCKED"
    ABSTAIN = "ABSTAIN"   # reviewer gave no parseable verdict — does NOT count as a rejection


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT, repo_path TEXT, repository_url TEXT,
  default_branch TEXT DEFAULT 'main', test_command TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, project_id TEXT, goal TEXT, status TEXT,
  base_branch TEXT, integration_branch TEXT, mode TEXT DEFAULT 'local',
  created_at TEXT, completed_at TEXT);
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, run_id TEXT, title TEXT, description TEXT, status TEXT,
  priority INTEGER DEFAULT 0, depends_on TEXT DEFAULT '[]',
  acceptance_criteria TEXT DEFAULT '[]', ownership TEXT DEFAULT '[]',
  do_not_modify TEXT DEFAULT '[]', validation TEXT DEFAULT '',
  assigned_agent TEXT, revisions INTEGER DEFAULT 0, created_at TEXT);
CREATE TABLE IF NOT EXISTS assignments (
  id TEXT PRIMARY KEY, task_id TEXT, agent TEXT, role TEXT, status TEXT,
  session_id TEXT, worktree_path TEXT, branch TEXT,
  started_at TEXT, finished_at TEXT, commit_sha TEXT, files_changed INTEGER DEFAULT 0,
  tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY, task_id TEXT, assignment_id TEXT, reviewer_agent TEXT,
  reviewed_commit_sha TEXT, verdict TEXT, summary TEXT, findings TEXT DEFAULT '[]',
  created_at TEXT);
CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, task_id TEXT, agent TEXT,
  event_type TEXT, payload TEXT DEFAULT '{}', created_at TEXT);
"""

_JSON_COLS = {"depends_on", "acceptance_criteria", "ownership", "do_not_modify", "findings", "payload"}


class Store:
    """Thin DAO. Rows in/out as dicts; JSON columns encoded transparently."""

    def __init__(self, db_path: Path | str = DEFAULT_DB):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        # additive migrations — add columns to older DBs; harmless if already present
        for stmt in ("ALTER TABLE runs ADD COLUMN mode TEXT DEFAULT 'local'",):
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()
        self.on_event = None   # optional callback(row) for live streaming

    # -- generic helpers --
    def _enc(self, d: dict) -> dict:
        return {k: (json.dumps(v) if k in _JSON_COLS else v) for k, v in d.items()}

    def _dec(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in list(d):
            if k in _JSON_COLS and isinstance(d[k], str):
                try: d[k] = json.loads(d[k])
                except Exception: pass
        return d

    def insert(self, table: str, row: dict) -> dict:
        row = self._enc(row)
        cols = ",".join(row); ph = ",".join("?" * len(row))
        with self._lock:
            self._conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})", list(row.values()))
            self._conn.commit()
        return row

    def update(self, table: str, id_: str, **fields) -> None:
        fields = self._enc(fields)
        sets = ",".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*fields.values(), id_])
            self._conn.commit()

    def get(self, table: str, id_: str) -> dict | None:
        cur = self._conn.execute(f"SELECT * FROM {table} WHERE id=?", [id_])
        r = cur.fetchone()
        return self._dec(r) if r else None

    def query(self, table: str, where: str = "", args: tuple = (), order: str = "") -> list[dict]:
        sql = f"SELECT * FROM {table}"
        if where: sql += f" WHERE {where}"
        if order: sql += f" ORDER BY {order}"
        return [self._dec(r) for r in self._conn.execute(sql, args).fetchall()]

    def event(self, run_id: str, event_type: str, task_id: str = None,
              agent: str = None, payload: dict = None) -> None:
        row = {"run_id": run_id, "task_id": task_id, "agent": agent,
               "event_type": event_type, "payload": payload or {}, "created_at": now()}
        self.insert("run_events", row)
        if self.on_event:
            try: self.on_event(row)
            except Exception: pass
