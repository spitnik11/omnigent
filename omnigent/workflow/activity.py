"""Small deterministic activity normalizer for console and transcript output."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
TOOL = re.compile(r"^(?:[✱→✓✗•]\s*)?(read|write|edit|grep|glob|search|run|bash|shell|tool)\b", re.I)
STATE_DIR = Path.home() / ".omni" / "transcripts"


def clean_line(line: str) -> str:
    return CONTROL.sub("", ANSI.sub("", line or "")).strip()


def normalize(item: dict) -> dict | None:
    if item.get("type") == "output":
        raw = clean_line(item.get("line", ""))
        if not raw:
            return None
        low = raw.lower()
        kind = "tool" if TOOL.match(raw) else "output"
        state = "active"
        if low.startswith(("[error]", "error:")) or " failed" in low:
            kind, state = "error", "failed"
        elif low.startswith(("warning:", "warn ")):
            kind, state = "warning", "warning"
        return {**item, "kind": kind, "summary": raw[:240], "details": [raw],
                "state": state, "collapsible": kind in ("tool", "output"), "line": raw}
    event = item.get("event", "")
    payload = item.get("payload") or {}
    kind = {
        "PLAN_STARTED": "planning", "PLAN_COMPLETED": "planning",
        "TASK_STARTED": "task", "TASK_FAILED": "error", "IMPLEMENTATION_REJECTED": "error",
        "COMMIT_CREATED": "commit", "REVIEW_STARTED": "review",
        "REVIEW_COMPLETED": "review", "REVIEW_SKIPPED": "review",
        "CHANGES_REQUESTED": "revision", "REVISION_STARTED": "revision",
        "VALIDATION_COMPLETED": "validation", "TASK_INTEGRATED": "integration",
        "INTEGRATION_CONFLICT": "error", "RUN_READY": "human_gate",
        "RUN_FAILED": "error",
    }.get(event, "run")
    state = "failed" if kind == "error" else "completed" if event.endswith(("COMPLETED", "CREATED")) else "active"
    if event == "REVIEW_SKIPPED":
        state = "skipped"
    summary = event.replace("_", " ").lower()
    return {**item, "kind": kind, "summary": summary, "details": [], "state": state,
            "collapsible": bool(payload), "payload": payload}


class TranscriptStore:
    """Append-only JSONL audit transcript; recent feed stays separately bounded."""
    def __init__(self, root: Path | str = STATE_DIR):
        self.root = Path(root)
        self._lock = threading.Lock()

    def append(self, run_id: str, item: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{run_id}.jsonl"
        with self._lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    def page(self, run_id: str, before: int | None = None, limit: int = 500) -> dict:
        path = self.root / f"{run_id}.jsonl"
        if not path.exists():
            return {"items": [], "before": None}
        with self._lock:
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        if before is not None:
            rows = [r for r in rows if r.get("seq", -1) < before]
        page = rows[-max(1, min(limit, 1000)):]
        return {"items": page, "before": page[0]["seq"] if page else None}


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
