"""HTTP API + SSE streaming for the workflow engine (mounted into the web app).

A Runner drives runs on background threads and funnels EVERYTHING — agent output
lines and state events — into one per-run feed, streamed to the browser over SSE
so the UI reads like a CLI. Token/cost aggregates ride along in the snapshot.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from starlette.responses import JSONResponse
from starlette.routing import Route

try:
    from sse_starlette.sse import EventSourceResponse
except Exception:  # pragma: no cover
    EventSourceResponse = None

from .models import RunStatus, Store
from .service import WorkflowService

TERMINAL = {RunStatus.WAITING_FOR_USER, RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True)


def _demo_repo() -> str:
    """Throwaway git repo so mock/demo runs never touch a real project."""
    d = Path(tempfile.mkdtemp(prefix="omni_demo_")) / "repo"
    d.mkdir(parents=True)
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "demo@omni.dev")
    _git(d, "config", "user.name", "Omni Demo")
    (d / "README.md").write_text("# demo project\n", encoding="utf-8")
    _git(d, "add", "-A"); _git(d, "commit", "-q", "-m", "init")
    return str(d)


class Runner:
    def __init__(self):
        self.store = Store()
        self.store.on_event = self._on_event
        self.svc_real = WorkflowService(store=self.store, mock=False)
        self.svc_mock = WorkflowService(store=self.store, mock=True)
        self.feeds: dict[str, list[dict]] = {}

    def _push(self, run_id, item):
        self.feeds.setdefault(run_id, []).append({**item, "seq": len(self.feeds.get(run_id, []))})

    def _on_event(self, row):
        self._push(row["run_id"], {"type": "event", "event": row["event_type"],
                                   "task": row["task_id"], "agent": row["agent"],
                                   "payload": row["payload"]})

    def start(self, project_path, goal, tasks, mock) -> dict:
        svc = self.svc_mock if mock else self.svc_real
        if not project_path:
            if not mock:
                raise ValueError("project_path required (or enable demo mode)")
            project_path = _demo_repo()
        if not (Path(project_path) / ".git").exists():
            raise ValueError(f"not a git repo: {project_path}")
        proj = next((p for p in self.store.query("projects")
                     if p["repo_path"] == str(project_path)), None)
        if not proj:
            base = _git(project_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
            proj = svc.create_project(Path(project_path).name, str(project_path), default_branch=base)
        run = svc.create_run(proj["id"], goal)
        for t in (tasks or [{"title": goal}]):
            svc.create_task(run["id"], t["title"], description=t.get("description", ""),
                            agent=t.get("agent"), acceptance_criteria=t.get("acceptance", []))

        def on_line(agent, task_id, line):
            self._push(run["id"], {"type": "output", "agent": agent, "task": task_id, "line": line})

        def drive():
            self._push(run["id"], {"type": "output", "agent": "omni",
                                   "line": f"Run started: {goal}"})
            try:
                svc.drive(run["id"], on_line=on_line)
            except Exception as e:  # noqa: BLE001
                self._push(run["id"], {"type": "output", "agent": "system", "line": f"[error] {e}"})

        threading.Thread(target=drive, daemon=True).start()
        return run

    def snapshot(self, run_id) -> dict:
        run = self.store.get("runs", run_id)
        if not run:
            return {}
        tasks = self.store.query("tasks", "run_id=?", (run_id,), order="created_at")
        for t in tasks:
            t["assignments"] = self.store.query("assignments", "task_id=?", (t["id"],))
            t["reviews"] = self.store.query("reviews", "task_id=?", (t["id"],))
        return {"run": run, "tasks": tasks, "summary": self.svc_real.run_summary(run_id)}

    def list_runs(self) -> list[dict]:
        return sorted(self.store.query("runs"), key=lambda r: r["created_at"], reverse=True)


RUNNER = Runner()


# --- routes ---------------------------------------------------------------

async def api_state(_r):
    return JSONResponse({"runs": RUNNER.list_runs(),
                         "projects": RUNNER.store.query("projects")})

async def api_create(request):
    d = await request.json()
    goal = (d.get("goal") or "").strip()
    if not goal:
        return JSONResponse({"error": "goal required"}, status_code=400)
    try:
        run = RUNNER.start(d.get("project_path", "").strip(), goal,
                           d.get("tasks"), bool(d.get("mock")))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(run)

async def api_run(request):
    snap = RUNNER.snapshot(request.path_params["rid"])
    if not snap:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(snap)

async def api_approve(request):
    rid = request.path_params["rid"]
    if not RUNNER.store.get("runs", rid):
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(RUNNER.svc_real.approve_run(rid))

async def api_stream(request):
    rid = request.path_params["rid"]
    if EventSourceResponse is None:
        return JSONResponse({"error": "sse unavailable"}, status_code=500)

    async def gen():
        i = 0
        idle = 0
        while True:
            if await request.is_disconnected():
                break
            feed = RUNNER.feeds.get(rid, [])
            if i < len(feed):
                while i < len(feed):
                    yield {"event": "feed", "data": json.dumps(feed[i])}
                    i += 1
                idle = 0
            else:
                idle += 1
            run = RUNNER.store.get("runs", rid)
            if run and run["status"] in TERMINAL and idle > 2:
                yield {"event": "done", "data": json.dumps(RUNNER.snapshot(rid)["summary"])}
                break
            await asyncio.sleep(0.4)

    return EventSourceResponse(gen())


routes = [
    Route("/api/state", api_state),
    Route("/api/runs", api_create, methods=["POST"]),
    Route("/api/runs/{rid}", api_run),
    Route("/api/runs/{rid}/approve", api_approve, methods=["POST"]),
    Route("/api/runs/{rid}/stream", api_stream),
]
