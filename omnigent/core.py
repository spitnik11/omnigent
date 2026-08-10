"""Direct orchestration path (no CrewAI required).

This is the backwards-compatible fallback the CLI uses if crewai isn't
installed. flow.py wraps the same route()+run() in a CrewAI Flow.
"""
from __future__ import annotations

from .harness import Harness, Result, load_config, load_harnesses, run
from .router import route, strip_prefix


def _load() -> tuple[dict, dict[str, Harness]]:
    cfg = load_config()
    return cfg, load_harnesses(cfg)


def orchestrate(task: str, harness: str | None = None, project: str | None = None,
                timeout: int = 1800) -> tuple[str, Result]:
    cfg, hs = _load()
    name = route(task, hs, cfg, forced=harness)
    prompt = strip_prefix(task, hs)
    return name, run(hs[name], prompt, project, timeout)


def list_harnesses() -> dict[str, Harness]:
    return _load()[1]
