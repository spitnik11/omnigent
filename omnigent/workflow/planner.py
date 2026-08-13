"""Auto-planning — turn one goal into a small DAG of parallelizable tasks.

v1 is a single planning call by a cloud lead (per the plan: don't build 3-agent
voting first). Deterministic JSON parse; always falls back to a single task if the
planner is unavailable or returns nothing — so a goal never fails to run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..harness import load_config, load_harnesses
from ..harness import run as run_harness

PLAN_LEAD = "claude"          # strongest planner; cloud (planning is cheap vs implementation)
MAX_TASKS = 5


def _repo_context(repo_path: str) -> str:
    try:
        names = sorted(p.name for p in Path(repo_path).iterdir()
                       if not p.name.startswith(".") and p.name != ".worktrees")[:40]
        return ", ".join(names)
    except Exception:
        return ""


def _prompt(goal: str, ctx: str) -> str:
    return (
        "You are a software planning lead. Break the GOAL into 2–5 INDEPENDENT, "
        "parallelizable implementation tasks for a team of coding agents. Prefer tasks "
        "that touch DIFFERENT files/areas so they run concurrently without conflicts; "
        "only use dependencies when one task truly needs another's output first.\n\n"
        f"GOAL: {goal}\n\n"
        f"PROJECT top-level: {ctx or '(empty repo)'}\n\n"
        "Return ONLY a JSON array (no prose, no code fences) of task objects:\n"
        '[{"title": "...", "description": "what to build, and which files/paths it owns", '
        '"acceptance": ["checkable criterion", "..."], "depends_on": []}]\n'
        "depends_on holds 0-based indices of EARLIER tasks in this array that must finish "
        "first ([] = independent). Keep it to 2–5 focused tasks."
    )


def _parse(output: str) -> list[dict]:
    if not output:
        return []
    # strip code fences, grab the outermost JSON array
    m = re.search(r"\[\s*\{.*\}\s*\]", output, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    tasks = []
    for i, t in enumerate(data):
        if not isinstance(t, dict) or not t.get("title"):
            continue
        deps = [d for d in (t.get("depends_on") or []) if isinstance(d, int) and 0 <= d < i]
        tasks.append({"title": str(t["title"])[:120],
                      "description": str(t.get("description", "")),
                      "acceptance": [str(x) for x in (t.get("acceptance") or [])][:6],
                      "depends_on": deps})
        if len(tasks) >= MAX_TASKS:
            break
    return tasks


def plan_goal(goal: str, repo_path: str, mock: bool = False, on_line=None) -> list[dict]:
    """Return a task list (each: title/description/acceptance/depends_on indices).
    Never raises; falls back to a single task = the goal."""
    if mock:  # deterministic split so demo/tests show the swarm
        return [{"title": f"{goal} — part {n}", "description": "", "acceptance": [],
                 "depends_on": ([] if n == 1 else [])} for n in (1, 2, 3)]
    try:
        h = load_harnesses(load_config()).get(PLAN_LEAD)
        if not h or not h.available:
            return [{"title": goal, "depends_on": []}]
        res = run_harness(h, _prompt(goal, _repo_context(repo_path)), repo_path, on_line=on_line)
        tasks = _parse(res.output)
        return tasks or [{"title": goal, "depends_on": []}]
    except Exception:
        return [{"title": goal, "depends_on": []}]
