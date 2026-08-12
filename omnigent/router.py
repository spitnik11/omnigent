"""Pick which harness handles a task.

Deterministic and free: explicit override > leading '@name' > keyword rules >
default. No LLM call. Only ever routes to an *available* harness.

# ponytail: keyword router. Swap route() for an LLM classifier only if these
# rules misfire in real use — not before.
"""
from __future__ import annotations

from .harness import Harness


def _explicit_name(task: str, harnesses: dict[str, Harness]) -> str | None:
    if task.startswith("@"):
        head = task.split(None, 1)[0][1:]
        if head in harnesses:
            return head
    return None


def strip_prefix(task: str, harnesses: dict[str, Harness]) -> str:
    """Remove a leading '@name ' override from the task text."""
    if _explicit_name(task, harnesses):
        _, _, rest = task.partition(" ")
        return rest.strip()
    return task


def route(task: str, harnesses: dict[str, Harness], cfg: dict,
          forced: str | None = None, role: str | None = None) -> str:
    avail = [n for n, h in harnesses.items() if h.available]
    if not avail:
        raise RuntimeError("no harnesses available — check installs or harnesses.yaml")

    pick = forced or _explicit_name(task, harnesses)
    if pick:
        if pick not in harnesses:
            raise RuntimeError(f"unknown harness '{pick}' (known: {', '.join(harnesses)})")
        return pick if pick in avail else _fallback(cfg, avail)

    # Cost-aware preference: IMPLEMENT work goes to a free local harness when one
    # is available and capable. REVIEW/other roles skip this and fall through to
    # the keyword rules as before (role=None means "no preference", unchanged).
    if role == "IMPLEMENT":
        local = _local_pick(harnesses, avail)
        if local:
            return local

    rules = (cfg.get("router") or {}).get("rules") or {}
    low = task.lower()
    for name, kws in rules.items():
        if name in avail and any(k.lower() in low for k in kws):
            return name
    return _fallback(cfg, avail)


def _local_pick(harnesses: dict[str, Harness], avail: list[str]) -> str | None:
    for name in avail:
        h = harnesses[name]
        if h.kind == "local" and h.cost == 0 and (not h.capabilities or "implement" in h.capabilities):
            return name
    return None


def _fallback(cfg: dict, avail: list[str]) -> str:
    default = (cfg.get("router") or {}).get("default")
    return default if default in avail else avail[0]
