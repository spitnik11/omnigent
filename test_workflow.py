"""Workflow engine self-check — MOCK agents, fast/free/deterministic.

Covers the whole loop: concurrent execution in isolated worktrees -> cross-agent
review -> revision loop (stale reviews drop out) -> integration branch -> human
gate. Run: python test_workflow.py
"""
import subprocess
import tempfile
from pathlib import Path

from omnigent.workflow.adapter import MockAgentAdapter, ReviewResult
from omnigent.workflow.models import RunStatus, Store, TaskStatus
from omnigent.workflow.service import WorkflowService


def _git(cwd, *a):
    p = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    assert p.returncode == 0, f"git {' '.join(a)}: {p.stderr}"
    return p.stdout.strip()


def _mkrepo():
    tmp = Path(tempfile.mkdtemp(prefix="omni_wf_"))
    repo = tmp / "proj"; repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.dev")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello", encoding="utf-8")
    _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "init")
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return tmp, repo, base


def test_full_loop():
    tmp, repo, base = _mkrepo()
    svc = WorkflowService(store=Store(tmp / "omni.db"), mock=True)
    proj = svc.create_project("proj", str(repo), default_branch=base)
    run = svc.create_run(proj["id"], "Add settings page")
    tasks = [svc.create_task(run["id"], "Settings backend", agent="claude"),
             svc.create_task(run["id"], "Settings UI", agent="codex"),
             svc.create_task(run["id"], "Tests", agent="grok")]

    summary = svc.drive(run["id"])

    # all tasks approved via 2-of-3 review consensus
    for t in tasks:
        assert svc.store.get("tasks", t["id"])["status"] == TaskStatus.APPROVED
    # 3 tasks x 2 reviewers = 6 reviews
    assert summary["reviews"] == 6, summary
    # cost + tokens aggregated from assignments (mock usage)
    assert summary["cost_usd"] > 0 and summary["tokens_in"] > 0, summary
    # integration branch now contains all three task commits
    assert svc.store.get("runs", run["id"])["status"] == RunStatus.WAITING_FOR_USER
    log = _git(repo, "log", "--oneline", run["integration_branch"])
    for name in ("Settings backend", "Settings UI", "Tests"):
        assert name in log, (name, log)
    # human gate: approve -> COMPLETED
    svc.approve_run(run["id"])
    assert svc.store.get("runs", run["id"])["status"] == RunStatus.COMPLETED
    print(f"full-loop ok: 3 tasks approved, {summary['reviews']} reviews, "
          f"${summary['cost_usd']} cost, integrated -> gate -> completed")


def test_revision_loop():
    tmp, repo, base = _mkrepo()

    class RevMock(MockAgentAdapter):
        # grok requests changes on the FIRST commit, approves once revised
        def review(self, task, diff, commit_sha, on_line=None, cwd=None):
            if self.name == "grok" and "rev 0" in diff:
                return ReviewResult("CHANGES_REQUESTED", summary="needs work",
                                    findings=["handle the empty case"])
            return ReviewResult("APPROVED", summary="ok",
                                tokens_in=150, tokens_out=20, cost_usd=0.0009)

    svc = WorkflowService(store=Store(tmp / "omni.db"),
                          adapter_factory=lambda a: RevMock(a))
    proj = svc.create_project("proj", str(repo), default_branch=base)
    run = svc.create_run(proj["id"], "One task with a revision")
    task = svc.create_task(run["id"], "Feature", agent="codex")  # reviewers: claude + grok

    svc.drive(run["id"], max_revisions=1)

    row = svc.store.get("tasks", task["id"])
    assert row["status"] == TaskStatus.APPROVED, row["status"]
    assert row["revisions"] == 1, row["revisions"]
    # both a stale CHANGES_REQUESTED (old commit) and a fresh APPROVED exist
    verdicts = {r["verdict"] for r in svc.store.query("reviews", "task_id=?", (task["id"],))}
    assert {"CHANGES_REQUESTED", "APPROVED"} <= verdicts, verdicts
    # the final approval is pinned to the current (revised) commit
    cur = svc._latest_impl(row)["commit_sha"]
    approvals_now = [r for r in svc.store.query("reviews", "task_id=?", (task["id"],))
                     if r["reviewed_commit_sha"] == cur and r["verdict"] == "APPROVED"]
    assert len(approvals_now) >= 2, approvals_now
    print(f"revision-loop ok: 1 revision, stale review dropped, "
          f"{len(approvals_now)} approvals on final commit")


if __name__ == "__main__":
    test_full_loop()
    test_revision_loop()
    print("workflow self-check ok")
