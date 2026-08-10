"""Omni multi-agent workflow engine.

Deterministic coordinator over the agent CLIs: Project -> Run -> Task ->
Assignment, executed concurrently in isolated git worktrees. The coordinator
owns all state; agents only do work. SQLite persistence, no framework.
"""
