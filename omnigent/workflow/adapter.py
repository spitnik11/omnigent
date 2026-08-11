"""Agent adapters — normalize claude/codex/grok behind one interface.

One CliAgentAdapter parameterized by harness name (the three "containers" differ
only by which binary; harnesses.yaml already encodes that — no `if agent==grok`).
MockAgentAdapter writes a file + commits, so the coordinator/worktree/state
machine can be tested fast, free, and deterministically without real LLM calls.

The coordinator DERIVES the structured result from git (commit SHA, files
changed) rather than trusting the CLI to emit clean JSON — deterministic by
construction.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from ..harness import load_config, load_harnesses
from ..harness import run as run_harness


@dataclass
class AgentResult:
    status: str                 # "completed" | "failed"
    summary: str = ""
    commit_sha: str = ""
    files_changed: int = 0
    output: str = ""
    warnings: list = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class ReviewResult:
    verdict: str                # APPROVED | CHANGES_REQUESTED | BLOCKED
    summary: str = ""
    findings: list = field(default_factory=list)
    output: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


def review_prompt(task: dict, diff: str, commit_sha: str) -> str:
    """Narrow, read-only review contract (plan section 18)."""
    ac = "\n".join(f"- {c}" for c in (task.get("acceptance_criteria") or [])) or "- (none specified)"
    kb = task.get("_knowledge")
    prefix = (kb + "\n\n---\n\n") if kb else ""
    return prefix + (
        f"You are REVIEWING commit {commit_sha[:8]} for task: {task['title']}\n\n"
        "Do NOT modify code. Do NOT delegate. Review the diff below against the "
        "task's acceptance criteria for correctness, security, tests, regressions, "
        "and maintainability.\n\n"
        f"ACCEPTANCE CRITERIA\n{ac}\n\n"
        f"DIFF\n{diff[:12000]}\n\n"
        "Respond with a first line that is EXACTLY one of:\n"
        "VERDICT: APPROVED\n"
        "VERDICT: CHANGES_REQUESTED\n"
        "Then, if changes are requested, list each concern on its own line."
    )


def contract_prompt(task: dict) -> str:
    """Render a Task row into the plan's Task Contract (section 14).

    If the coordinator injected retrieved knowledge (task['_knowledge']), it is
    prepended as background context — never as instructions.
    """
    kb = task.get("_knowledge")
    prefix = (kb + "\n\n---\n\n") if kb else ""
    def block(label, items):
        return f"\n{label}\n" + "\n".join(f"- {i}" for i in items) if items else ""
    return prefix + (
        f"TASK: {task['title']}\n\n"
        f"GOAL\n{task.get('description','') or task['title']}\n"
        + block("OWNERSHIP (only modify these paths)", task.get("ownership") or [])
        + block("DO NOT MODIFY", task.get("do_not_modify") or [])
        + block("ACCEPTANCE CRITERIA", task.get("acceptance_criteria") or [])
        + (f"\nVALIDATION\nRun: {task['validation']}" if task.get("validation") else "")
        + "\n\nOUTPUT\nImplement the change, then commit ALL your work with git "
          "(git add -A && git commit -m \"...\"). Print a one-line summary of what you did."
    )


class AgentAdapter:
    name = "base"
    def run(self, task: dict, worktree_path: str, base_branch: str, on_line=None) -> AgentResult:
        raise NotImplementedError
    def review(self, task: dict, diff: str, commit_sha: str, on_line=None, cwd=None) -> ReviewResult:
        raise NotImplementedError


class CliAgentAdapter(AgentAdapter):
    """Runs a real agent CLI (via harness.run) in the assignment's worktree."""

    def __init__(self, agent: str):
        self.name = agent

    def _harness(self):
        h = load_harnesses(load_config()).get(self.name)
        return h if (h and h.available) else None

    def run(self, task, worktree_path, base_branch, on_line=None):
        h = self._harness()
        if not h:
            return AgentResult("failed", summary=f"agent '{self.name}' unavailable")
        res = run_harness(h, contract_prompt(task), worktree_path, on_line=on_line)
        ti, to, cost = _parse_usage(res.output)
        return AgentResult(
            status="completed" if res.ok else "failed",
            summary=(res.output.splitlines()[-1] if res.output else "")[:200],
            commit_sha=_head(worktree_path),
            files_changed=_changed(worktree_path, base_branch),
            output=res.output, tokens_in=ti, tokens_out=to, cost_usd=cost,
        )

    def review(self, task, diff, commit_sha, on_line=None, cwd=None):
        h = self._harness()
        if not h:
            return ReviewResult("BLOCKED", summary=f"agent '{self.name}' unavailable")
        # reviewers inspect the diff text (read-only intent); cwd = repo root.
        res = run_harness(h, review_prompt(task, diff, commit_sha), cwd, on_line=on_line)
        verdict, findings = _parse_verdict(res.output)
        ti, to, cost = _parse_usage(res.output)
        return ReviewResult(verdict, summary=(res.output.splitlines()[0] if res.output else "")[:200],
                            findings=findings, output=res.output,
                            tokens_in=ti, tokens_out=to, cost_usd=cost)


class MockAgentAdapter(AgentAdapter):
    """Test double: writes a file + commits; reviews APPROVED. No LLM. Deterministic."""

    def __init__(self, agent: str):
        self.name = agent

    def run(self, task, worktree_path, base_branch, on_line=None):
        emit = on_line or (lambda _l: None)
        rev = task.get("revisions", 0)
        emit(f"starting {task['title']}" + (f" (revision {rev})" if rev else ""))
        fname = f"{self.name}_{task['id']}.txt"
        (_p(worktree_path) / fname).write_text(
            f"{self.name} implemented: {task['title']} (rev {rev})\n", encoding="utf-8")
        emit(f"wrote {fname}")
        _run(worktree_path, "git", "add", "-A")
        _run(worktree_path, "git", "commit", "-m", f"{task['title']} ({self.name}) rev{rev}")
        sha = _head(worktree_path)
        emit(f"committed {sha[:8]}")
        return AgentResult("completed", summary=f"mock implemented {task['title']}",
                           commit_sha=sha, files_changed=1, output=f"committed {sha}",
                           tokens_in=200, tokens_out=80, cost_usd=0.002)

    def review(self, task, diff, commit_sha, on_line=None, cwd=None):
        emit = on_line or (lambda _l: None)
        emit(f"reviewed {commit_sha[:8]}: APPROVED")
        return ReviewResult("APPROVED", summary="mock review approved",
                            tokens_in=150, tokens_out=20, cost_usd=0.0009)


# --- git helpers ---
from pathlib import Path as _p  # noqa: E402

def _run(cwd, *args):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)

def _head(cwd):
    p = _run(cwd, "git", "rev-parse", "HEAD")
    return p.stdout.strip() if p.returncode == 0 else ""

def _changed(cwd, base):
    p = _run(cwd, "git", "diff", "--name-only", f"{base}...HEAD")
    return len([l for l in p.stdout.splitlines() if l.strip()]) if p.returncode == 0 else 0


import re as _re  # noqa: E402

def _parse_usage(output: str) -> tuple[int, int, float]:
    """Best-effort token/cost extraction from CLI output.

    Populated when a CLI emits usage (e.g. claude/grok/codex JSON output modes).
    Plain `-p` text usually won't include it -> returns zeros. Wiring is here so
    the moment a harness is switched to a usage-emitting mode, cost shows up.
    # ponytail: regex scrape. Swap for real stream-json parsing per harness when
    # true live token streaming (Claude-CLI style) is wired.
    """
    if not output:
        return 0, 0, 0.0
    def _find(*keys):
        for k in keys:
            m = _re.search(rf'"{k}"\s*:\s*(\d+)', output)
            if m: return int(m.group(1))
        return 0
    ti = _find("input_tokens", "prompt_tokens", "tokens_in")
    to = _find("output_tokens", "completion_tokens", "tokens_out")
    cm = _re.search(r'"(?:total_cost_usd|cost_usd|cost)"\s*:\s*([0-9.]+)', output) \
        or _re.search(r'\$([0-9]+\.[0-9]+)', output)
    cost = float(cm.group(1)) if cm else 0.0
    return ti, to, cost


def _parse_verdict(output: str) -> tuple[str, list]:
    """Extract APPROVED / CHANGES_REQUESTED and any listed findings."""
    text = output or ""
    up = text.upper()
    if "CHANGES_REQUESTED" in up or "CHANGES REQUESTED" in up:
        findings = [l.strip("-* \t") for l in text.splitlines()
                    if l.strip().startswith(("-", "*")) and l.strip("-* \t")][:8]
        return "CHANGES_REQUESTED", findings
    if "APPROVED" in up:
        return "APPROVED", []
    return "CHANGES_REQUESTED", ["reviewer gave no clear verdict"]  # fail safe


def get_adapter(agent: str, mock: bool = False) -> AgentAdapter:
    return MockAgentAdapter(agent) if mock else CliAgentAdapter(agent)
