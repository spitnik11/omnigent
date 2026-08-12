"""Omnigent CLI — the running interface.

    omnigent list                          show harnesses + availability
    omnigent run "task" [--harness X]      route + run one task in a project
    omnigent repl [--project DIR]          interactive loop

Uses the CrewAI Flow when crewai is installed; falls back to the direct core
path otherwise (so it always runs).
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .core import list_harnesses, orchestrate

try:
    from .flow import run_flow
    _HAVE_FLOW = True
except ImportError:
    _HAVE_FLOW = False


def _dispatch(task: str, harness: str | None, project: str | None, timeout: int,
             profile: str | None = None):
    """Return (chosen, ok, output, seconds). Prefer the CrewAI Flow."""
    if _HAVE_FLOW:
        st = run_flow(task, harness, project, timeout, profile)
        return st.chosen, st.ok, st.output, st.seconds
    name, r = orchestrate(task, harness, project, timeout, profile)
    return name, r.ok, r.output, r.seconds


def cmd_list(args) -> int:
    engine = "CrewAI Flow" if _HAVE_FLOW else "direct core (crewai not installed)"
    print(f"omnigent {__version__}  |  engine: {engine}\n")
    for name, h in list_harnesses(args.profile).items():
        mark = "OK " if h.available else "-- "
        where = h.path or f"'{h.bin}' not on PATH"
        print(f"  [{mark}] {name:8} {where}")
    return 0


def cmd_run(args) -> int:
    chosen, ok, output, seconds = _dispatch(args.task, args.harness, args.project, args.timeout,
                                            args.profile)
    print(f"▶ {chosen}  ({seconds:.1f}s)  {'ok' if ok else 'FAILED'}\n")
    print(output or "(no output)")
    return 0 if ok else 1


def cmd_repl(args) -> int:
    print("omnigent repl — type a task, '@grok ...' to force a harness, 'exit' to quit.")
    print(f"project: {args.project or '(current dir)'}\n")
    while True:
        try:
            task = input("omni> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not task:
            continue
        if task in ("exit", "quit"):
            return 0
        chosen, ok, output, seconds = _dispatch(task, args.harness, args.project, args.timeout,
                                                args.profile)
        print(f"▶ {chosen}  ({seconds:.1f}s)  {'ok' if ok else 'FAILED'}")
        print(output or "(no output)", "\n")


def cmd_web(args) -> int:
    from .web import serve
    serve(args.host, args.port, args.profile)
    return 0


def cmd_knowledge(args) -> int:
    from .knowledge.service import KnowledgeService
    ks = KnowledgeService.load()
    if not ks:
        print("knowledge: disabled — set `enabled: true` in knowledge.yaml and "
              "OMNI_OBSIDIAN_VAULT, then `omnigent knowledge sync`.")
        return 0
    if args.action == "sync":
        print("indexed:", ks.sync())
    elif args.action == "status":
        s = ks.status()
        print(f"sources: {', '.join(s['sources']) or '(none)'}")
        print(f"documents: {s['documents']}  chunks: {s['chunks']}  fts: {s['fts']}  writer: {s['writer']}")
    elif args.action == "search":
        hits = ks.search(args.query)
        if not hits:
            print("no matches")
        for h in hits:
            print(f"  {h.uri}" + (f"#{h.heading_path}" if h.heading_path else ""))
            print(f"    {h.snippet[:160]}")
    elif args.action == "doctor":
        for name, ok, detail in ks.doctor():
            print(f"  [{'OK ' if ok else '-- '}] {name}: {detail}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omnigent", description="Multi-harness agent orchestrator.")
    p.add_argument("--version", action="version", version=f"omnigent {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("list", help="show harnesses and availability")
    lp.add_argument("--profile", help="harnesses.yaml profile to filter by (default: all)")
    lp.set_defaults(func=cmd_list)

    r = sub.add_parser("run", help="route and run one task")
    r.add_argument("task", help="the task (prefix '@name ' to force a harness)")
    r.add_argument("--harness", help="force a specific harness")
    r.add_argument("--project", help="project directory to run in (default: cwd)")
    r.add_argument("--timeout", type=int, default=1800, help="seconds (default 1800)")
    r.add_argument("--profile", help="harnesses.yaml profile to filter by (default: all)")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("repl", help="interactive loop")
    rp.add_argument("--harness", help="force a specific harness for every line")
    rp.add_argument("--project", help="project directory to run in (default: cwd)")
    rp.add_argument("--timeout", type=int, default=1800, help="seconds (default 1800)")
    rp.add_argument("--profile", help="harnesses.yaml profile to filter by (default: all)")
    rp.set_defaults(func=cmd_repl)

    w = sub.add_parser("web", help="launch the local web UI")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8770)
    w.add_argument("--profile", help="harnesses.yaml profile to filter by (default: all)")
    w.set_defaults(func=cmd_web)

    k = sub.add_parser("knowledge", help="RAG index: status | sync | search <query> | doctor")
    k.add_argument("action", choices=["status", "sync", "search", "doctor"])
    k.add_argument("query", nargs="?", default="")
    k.set_defaults(func=cmd_knowledge)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
