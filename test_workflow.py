"""Workflow engine self-check — MOCK agents, fast/free/deterministic.

Covers the whole loop: concurrent execution in isolated worktrees -> cross-agent
review -> revision loop (stale reviews drop out) -> integration branch -> human
gate. Run: python test_workflow.py
"""
import subprocess
import tempfile
from pathlib import Path

from omnigent.workflow.adapter import (AgentResult, MockAgentAdapter, ReviewResult,
                                       _capacity_limited, _parse_verdict, _review_summary)
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


def test_limited_reviewer_is_skipped():
    assert _capacity_limited("You've hit your session limit · resets later")
    assert not _capacity_limited("VERDICT: APPROVED")
    tmp, repo, base = _mkrepo()

    class LimitedMock(MockAgentAdapter):
        def review(self, task, diff, commit_sha, on_line=None, cwd=None):
            if self.name == "claude":
                raise RuntimeError("You've hit your session limit")
            return ReviewResult("APPROVED", summary="ok")

    store = Store(tmp / "omni.db")
    svc = WorkflowService(store=store, adapter_factory=lambda a: LimitedMock(a))
    proj = svc.create_project("proj", str(repo), default_branch=base)
    run = svc.create_run(proj["id"], "Review despite one limited cloud agent")
    task = svc.create_task(run["id"], "Feature", agent="aider")

    svc.drive(run["id"])

    reviews = store.query("reviews", "task_id=?", (task["id"],))
    assert {r["reviewer_agent"]: r["verdict"] for r in reviews} == {
        "claude": "ABSTAIN", "codex": "APPROVED", "grok": "APPROVED"}
    assert store.get("tasks", task["id"])["status"] == TaskStatus.APPROVED
    skipped = store.query("run_events", "run_id=? AND event_type=?",
                          (run["id"], "REVIEW_SKIPPED"))
    assert len(skipped) == 1 and skipped[0]["agent"] == "claude"
    print("limited-reviewer ok: claude skipped, codex + grok approved")


def test_invalid_implementation_never_reaches_review():
    tmp, repo, base = _mkrepo()

    class NoopMock(MockAgentAdapter):
        reviews = 0
        def run(self, task, worktree_path, base_branch, on_line=None, on_start=None):
            return AgentResult("completed", commit_sha=_git(repo, "rev-parse", base_branch))
        def review(self, *args, **kwargs):
            self.reviews += 1
            return ReviewResult("APPROVED")

    adapters = {}
    def factory(agent):
        return adapters.setdefault(agent, NoopMock(agent))

    store = Store(tmp / "omni.db")
    svc = WorkflowService(store=store, adapter_factory=factory)
    proj = svc.create_project("proj", str(repo), default_branch=base)
    run = svc.create_run(proj["id"], "No-op must fail")
    task = svc.create_task(run["id"], "Feature", agent="aider", ownership=["src"])
    svc.drive(run["id"])
    assert store.get("tasks", task["id"])["status"] == TaskStatus.FAILED
    assert not store.query("reviews", "task_id=?", (task["id"],))
    events = store.query("run_events", "run_id=? AND event_type=?",
                         (run["id"], "IMPLEMENTATION_REJECTED"))
    assert events and "new commit" in " ".join(events[0]["payload"]["problems"])
    print("implementation-guard ok: no-op rejected before review")


def test_failed_dependency_finishes():
    tmp, repo, base = _mkrepo()
    store = Store(tmp / "omni.db")
    svc = WorkflowService(store=store, mock=True)
    proj = svc.create_project("proj", str(repo), default_branch=base)
    run = svc.create_run(proj["id"], "Failed dependency")
    first = svc.create_task(run["id"], "First")
    second = svc.create_task(run["id"], "Second", depends_on=[first["id"]])
    store.update("tasks", first["id"], status=TaskStatus.FAILED)
    svc.drive(run["id"])
    assert store.get("tasks", second["id"])["status"] == TaskStatus.FAILED
    print("dependency-failure ok: dependent failed deterministically")


def test_review_output_parsing():
    output = "\x1b[33m2026-08-13 WARN telemetry startup\x1b[0m\n" \
             "Reviewed the actual changes.\nFINDINGS:\n- real concern\nVERDICT: CHANGES_REQUESTED\n" \
             "- prompt bullet after verdict"
    verdict, findings = _parse_verdict(output)
    assert verdict == "CHANGES_REQUESTED" and findings == ["real concern"], findings
    assert _review_summary(output) == "Reviewed the actual changes."
    print("review-parser ok: warnings and prompt bullets excluded")


def test_cancel_run():
    tmp, repo, base = _mkrepo()
    store = Store(tmp / "omni.db")
    svc = WorkflowService(store=store, mock=True)
    proj = svc.create_project("proj", str(repo), default_branch=base)
    run = svc.create_run(proj["id"], "Cancel me")
    task = svc.create_task(run["id"], "Waiting")
    svc.cancel_run(run["id"])
    assert store.get("runs", run["id"])["status"] == RunStatus.CANCELLED
    assert store.get("tasks", task["id"])["status"] == TaskStatus.CANCELLED
    print("cancel ok: run and task cancelled")


if __name__ == "__main__":
    test_full_loop()
    test_revision_loop()
    test_limited_reviewer_is_skipped()
    test_invalid_implementation_never_reaches_review()
    test_failed_dependency_finishes()
    test_review_output_parsing()
    test_cancel_run()
    print("workflow self-check ok")
