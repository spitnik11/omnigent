"""In-memory store of runs for the web UI — supervision state Omnigent can back today.

Each run: a task dispatched to one harness, executed on a background thread with
live output. This is the small, honest amount of orchestration state that exists
now (one harness per run). Workflows/tasks/worktrees come with the Phase-2 engine.

# ponytail: in-memory + per-process. Add SQLite persistence only if runs need to
# survive a server restart.
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field

_ids = itertools.count(1)


@dataclass
class Run:
    id: str
    task: str
    project: str = ""
    forced: str | None = None
    status: str = "queued"        # queued | running | ok | failed | stopped
    chosen: str = ""
    started: float = 0.0
    ended: float = 0.0
    lines: list[str] = field(default_factory=list)
    proc: object = None           # Popen handle, for stop

    @property
    def seconds(self) -> float:
        if not self.started:
            return 0.0
        end = self.ended or time.monotonic()
        return round(end - self.started, 1)

    def to_dict(self, full: bool = False) -> dict:
        d = {
            "id": self.id, "task": self.task, "project": self.project,
            "forced": self.forced, "status": self.status, "chosen": self.chosen,
            "seconds": self.seconds, "line_count": len(self.lines),
        }
        if full:
            d["output"] = "\n".join(self.lines)
        return d


class RunStore:
    def __init__(self):
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def create(self, task: str, project: str | None, forced: str | None) -> Run:
        with self._lock:
            rid = f"r{next(_ids)}"
            r = Run(id=rid, task=task, project=project or "", forced=forced)
            self._runs[rid] = r
            return r

    def get(self, rid: str) -> Run | None:
        with self._lock:
            return self._runs.get(rid)

    def list(self) -> list[Run]:
        with self._lock:
            # newest first
            return sorted(self._runs.values(), key=lambda r: r.id, reverse=True)


STORE = RunStore()
