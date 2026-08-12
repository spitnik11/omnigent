"""Direct orchestration path (no CrewAI required).

This is the backwards-compatible fallback the CLI uses if crewai isn't
installed. flow.py wraps the same route()+run() in a CrewAI Flow.
"""
from __future__ import annotations

from .harness import Harness, Result, load_config, load_harnesses, run
from .router import route, strip_prefix


def _load(profile: str | None = None) -> tuple[dict, dict[str, Harness]]:
    cfg = load_config()
    return cfg, load_harnesses(cfg, profile=profile)


def orchestrate(task: str, harness: str | None = None, project: str | None = None,
                timeout: int = 1800, profile: str | None = None) -> tuple[str, Result]:
    cfg, hs = _load(profile)
    name = route(task, hs, cfg, forced=harness)
    prompt = strip_prefix(task, hs)
    return name, run(hs[name], prompt, project, timeout)


def list_harnesses(profile: str | None = None) -> dict[str, Harness]:
    return _load(profile)[1]
