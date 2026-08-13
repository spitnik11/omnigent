"""WorkflowService — the ONLY code allowed to change workflow state.

Coordinator = deterministic app code. It decides what's READY, who owns it,
which worktree it gets, and when it advances. Agents only do the work inside
their worktree. This turn covers: create Project/Run/Task, schedule ready tasks
onto available agents, execute them concurrently in isolated worktrees, capture
commits, emit RunEvents. Reviews/integration/planning are the next slice.
"""
from __future__ import annotations

import re
import subprocess
import threading

from .adapter import get_adapter
from ..harness import load_config, load_harnesses
from .models import (AssignmentStatus, Role, RunStatus, Store, TaskStatus,
                     Verdict, new_id, now)
from .worktrees import WorktreeManager

AGENTS = ["claude", "codex", "grok"]   # cloud API agents — the reviewers (plan section 34)
MIN_APPROVALS = 2                      # plan section 20 (2 of 3)
# Local implementers to auto-offload IMPLEMENT work to (aider first — fastest; opencode/
# goose reliable on qwen3:14b). Enables a parallel local swarm; cloud agents still review.
LOCAL_IMPL = ["aider", "opencode", "goose"]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:32] or "run"


class WorkflowService:
    def __init__(self, store: Store | None = None, mock: bool = False, adapter_factory=None,
                 knowledge=None):
        self.store = store or Store()
        self.mock = mock
        self.logs: dict[str, list[str]] = {}   # assignment_id -> live output lines
        # injectable so tests can script agent behaviour (revision loop, etc.)
        self._adapter = adapter_factory or (lambda agent: get_adapter(agent, mock=self.mock))
        # Optional RAG. None = today's exact behaviour. Never allowed to fail a run.
        self.knowledge = knowledge

    def _project_name(self, run: dict) -> str:
        proj = self.store.get("projects", run["project_id"])
        return (proj["name"] or "").lower() if proj else ""

    def _inject_task_context(self, task: dict, run: dict, agent: str) -> dict:
        """Attach retrieved knowledge to a task copy + emit CONTEXT_RETRIEVED. No-op if disabled."""
        if not self.knowledge:
            return task
        ctx, prov = self.knowledge.context_for_task(task, project=self._project_name(run), goal=run["goal"])
        if not ctx:
            return task
        self.store.event(run["id"], "CONTEXT_RETRIEVED", task["id"], agent,
                         {"sources": prov, "count": len(prov)})
        return {**task, "_knowledge": ctx}

    # -- creation ----------------------------------------------------------
    def create_project(self, name, repo_path, repository_url="", default_branch="main") -> dict:
        row = {"id": new_id("proj"), "name": name, "repo_path": str(repo_path),
               "repository_url": repository_url, "default_branch": default_branch,
               "created_at": now()}
        self.store.insert("projects", row)
        return row

    def create_run(self, project_id, goal, mode="local") -> dict:
        proj = self.store.get("projects", project_id)
        if not proj:
            raise ValueError(f"no project {project_id}")
        rid = new_id("run")
        base = proj["default_branch"]
        integ = f"omni/{_slug(goal)}-{rid.split('_')[1]}"
        row = {"id": rid, "project_id": project_id, "goal": goal,
               "status": RunStatus.PLANNING, "base_branch": base,
               "integration_branch": integ, "mode": mode,
               "created_at": now(), "completed_at": None}
        self.store.insert("runs", row)
        # create the integration branch off base so task worktrees can branch from it
        wm = WorktreeManager(proj["repo_path"])
        wm.ensure_branch(integ, base)
        self.store.event(rid, "RUN_CREATED", payload={"goal": goal, "integration_branch": integ})
        return row

    def create_task(self, run_id, title, description="", agent=None, depends_on=None,
                    acceptance_criteria=None, ownership=None, do_not_modify=None,
                    validation="", priority=0) -> dict:
        row = {"id": new_id("task"), "run_id": run_id, "title": title,
               "description": description, "status": TaskStatus.PLANNED, "priority": priority,
               "depends_on": depends_on or [], "acceptance_criteria": acceptance_criteria or [],
               "ownership": ownership or [], "do_not_modify": do_not_modify or [],
               "validation": validation, "assigned_agent": agent, "created_at": now()}
        self.store.insert("tasks", row)
        return row

    # -- scheduling --------------------------------------------------------
    def _deps_approved(self, task: dict) -> bool:
        for dep in task.get("depends_on") or []:
            d = self.store.get("tasks", dep)
            if not d or d["status"] != TaskStatus.APPROVED:
                return False
        return True

    def ready_tasks(self, run_id: str) -> list[dict]:
        # CHANGES_REQUESTED is handled by revise_task (reuses the worktree), not here.
        tasks = self.store.query("tasks", "run_id=?", (run_id,), order="priority DESC, created_at")
        return [t for t in tasks
                if t["status"] in (TaskStatus.PLANNED, TaskStatus.READY)
                and self._deps_approved(t)]

    def _impl_order(self, mode: str = "local") -> list[str]:
        """Implementer preference by mode. Reviews are ALWAYS cloud (see request_reviews).
        cloud mode -> cloud agents implement. local mode -> free local agents implement
        (offload), cloud fallback. Nothing is ever finished without cloud review either way.
        """
        try:
            hs = load_harnesses(load_config())
        except Exception:  # noqa: BLE001
            return list(AGENTS)
        cloud = [a for a in AGENTS if a in hs and hs[a].available]
        if mode == "cloud":
            return cloud or list(AGENTS)
        local = [n for n in LOCAL_IMPL if n in hs and hs[n].available]     # offload targets
        return (local + [a for a in cloud if a not in local]) or list(AGENTS)

    def _pick_agent(self, task: dict, busy: set[str]) -> str | None:
        if task.get("assigned_agent"):
            return task["assigned_agent"] if task["assigned_agent"] not in busy else None
        run = self.store.get("runs", task["run_id"])
        mode = (run or {}).get("mode") or "local"
        for a in self._impl_order(mode):
            if a not in busy:
                return a
        return None

    # -- execution ---------------------------------------------------------
    def assign(self, task: dict, agent: str) -> dict:
        """SERIAL: create the worktree + assignment for a task. Coordinator-owned."""
        run = self.store.get("runs", task["run_id"])
        proj = self.store.get("projects", run["project_id"])
        wm = WorktreeManager(proj["repo_path"])
        aid = new_id("asg")
        name = f"{_slug(task['title'])}-{agent}"
        branch, wt = wm.create(run["id"], name, run["integration_branch"])
        self.store.insert("assignments", {
            "id": aid, "task_id": task["id"], "agent": agent, "role": Role.IMPLEMENT,
            "status": AssignmentStatus.RUNNING, "session_id": None, "worktree_path": wt,
            "branch": branch, "started_at": now(), "finished_at": None,
            "commit_sha": None, "files_changed": 0})
        self.store.update("tasks", task["id"], status=TaskStatus.RUNNING, assigned_agent=agent)
        self.store.event(run["id"], "AGENT_ASSIGNED", task["id"], agent,
                         {"assignment": aid, "branch": branch})
        self.store.event(run["id"], "TASK_STARTED", task["id"], agent, {"worktree": wt})
        self.logs[aid] = []
        return self.store.get("assignments", aid)

    def execute_assignment(self, assignment: dict, on_line=None) -> dict:
        """CONCURRENT-SAFE: run the agent in its own worktree, capture the commit."""
        aid = assignment["id"]
        task = self.store.get("tasks", assignment["task_id"])
        run = self.store.get("runs", task["run_id"])
        agent = assignment["agent"]

        def sink(line):
            self.logs.setdefault(aid, []).append(line)
            if on_line:
                on_line(agent, task["id"], line)

        task = self._inject_task_context(task, run, agent)
        adapter = self._adapter(agent)
        result = adapter.run(task, assignment["worktree_path"], run["integration_branch"], on_line=sink)

        done = result.status == "completed"
        self.store.update("assignments", aid,
                          status=AssignmentStatus.DONE if done else AssignmentStatus.FAILED,
                          finished_at=now(), commit_sha=result.commit_sha,
                          files_changed=result.files_changed,
                          tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                          cost_usd=result.cost_usd)
        if done:
            self.store.update("tasks", task["id"], status=TaskStatus.REVIEW_READY)
            self.store.event(run["id"], "COMMIT_CREATED", task["id"], agent,
                             {"commit": result.commit_sha, "files_changed": result.files_changed})
        else:
            self.store.update("tasks", task["id"], status=TaskStatus.FAILED)
            self.store.event(run["id"], "TASK_FAILED", task["id"], agent, {"summary": result.summary})
        return {"assignment_id": aid, "task_id": task["id"], "agent": agent,
                "ok": done, "commit": result.commit_sha, "summary": result.summary}

    def execute_run(self, run_id: str, on_line=None) -> list[dict]:
        """One scheduling pass: assign ready tasks (serial), run them concurrently.

        One implementation assignment per agent at a time (plan section 26).
        Worktree creation is serialized; agent execution is parallel.
        """
        self.store.update("runs", run_id, status=RunStatus.RUNNING)
        busy: set[str] = set()
        assignments: list[dict] = []
        for t in self.ready_tasks(run_id):               # serial assignment
            a = self._pick_agent(t, busy)
            if a:
                busy.add(a)
                assignments.append(self.assign(t, a))
        results: list[dict] = []
        lock = threading.Lock()
        def work(asg):
            r = self.execute_assignment(asg, on_line=on_line)
            with lock:
                results.append(r)
        threads = [threading.Thread(target=work, args=(a,), daemon=True) for a in assignments]
        for th in threads: th.start()
        for th in threads: th.join()
        return results

    # -- reviews -----------------------------------------------------------
    def _latest_impl(self, task: dict) -> dict | None:
        asgs = [a for a in self.store.query("assignments", "task_id=?", (task["id"],))
                if a["role"] == Role.IMPLEMENT]
        return sorted(asgs, key=lambda a: a["started_at"] or "")[-1] if asgs else None

    def _diff(self, task: dict, commit: str) -> str:
        run = self.store.get("runs", task["run_id"])
        proj = self.store.get("projects", run["project_id"])
        p = subprocess.run(["git", "-C", proj["repo_path"], "diff",
                            f'{run["integration_branch"]}...{commit}'],
                           capture_output=True, text=True)
        return p.stdout

    def request_reviews(self, task: dict, on_line=None) -> str:
        """Dispatch the OTHER two agents to review the implementer's commit (plan section 19)."""
        task = self.store.get("tasks", task["id"])
        run = self.store.get("runs", task["run_id"])
        proj = self.store.get("projects", run["project_id"])
        asg = self._latest_impl(task)
        if not asg or not asg["commit_sha"]:
            return task["status"]
        commit, implementer = asg["commit_sha"], asg["agent"]
        self.store.update("tasks", task["id"], status=TaskStatus.REVIEWING)
        diff = self._diff(task, commit)
        rtask = task
        if self.knowledge:
            rctx, rprov = self.knowledge.context_for_review(
                task, changed_files=task.get("ownership"), project=self._project_name(run))
            if rctx:
                self.store.event(run["id"], "CONTEXT_RETRIEVED", task["id"], None,
                                 {"sources": rprov, "count": len(rprov), "phase": "review"})
                rtask = {**task, "_knowledge": rctx}
        for r in [a for a in AGENTS if a != implementer]:
            self.store.event(run["id"], "REVIEW_STARTED", task["id"], r, {"commit": commit})
            cb = (lambda line, a=r: on_line(a, task["id"], line)) if on_line else None
            # review INSIDE the implementer's worktree (checked out at the commit) so the
            # reviewer can read the actual files, not just the diff text.
            rr = self._adapter(r).review(rtask, diff, commit, on_line=cb, cwd=asg["worktree_path"])
            self.store.insert("reviews", {
                "id": new_id("rev"), "task_id": task["id"], "assignment_id": asg["id"],
                "reviewer_agent": r, "reviewed_commit_sha": commit, "verdict": rr.verdict,
                "summary": rr.summary, "findings": rr.findings, "created_at": now()})
            self.store.event(run["id"], "REVIEW_COMPLETED", task["id"], r,
                             {"verdict": rr.verdict, "commit": commit})
        return self.evaluate_task(task)

    def evaluate_task(self, task: dict) -> str:
        """Consensus (plan section 20). Only reviews pinned to the CURRENT commit count.
        A real rejection (CHANGES_REQUESTED/BLOCKED) wins. ABSTAIN (unparseable review) is
        ignored — it never becomes a false rejection. Else >=2 real APPROVALS -> APPROVED."""
        task = self.store.get("tasks", task["id"])
        asg = self._latest_impl(task)
        commit = asg["commit_sha"] if asg else None
        reviews = [r for r in self.store.query("reviews", "task_id=?", (task["id"],))
                   if r["reviewed_commit_sha"] == commit]
        rejections = [r for r in reviews if r["verdict"] in (Verdict.CHANGES_REQUESTED, Verdict.BLOCKED)]
        approvals = [r for r in reviews if r["verdict"] == Verdict.APPROVED]
        if rejections:
            findings = [f for r in rejections for f in (r["findings"] or [r["summary"]])]
            self.store.update("tasks", task["id"], status=TaskStatus.CHANGES_REQUESTED)
            self.store.event(task["run_id"], "CHANGES_REQUESTED", task["id"], None, {"findings": findings})
            return TaskStatus.CHANGES_REQUESTED
        if len(approvals) >= MIN_APPROVALS:
            self.store.update("tasks", task["id"], status=TaskStatus.APPROVED)
            self.store.event(task["run_id"], "TASK_APPROVED", task["id"], None, {"commit": commit})
            return TaskStatus.APPROVED
        return task["status"]   # only abstains / not enough approvals -> waits (never a false fail)

    def revise_task(self, task: dict, on_line=None) -> str:
        """Re-run the implementer in the SAME worktree with the review findings.
        Old reviews (pinned to the old commit) automatically go stale."""
        task = self.store.get("tasks", task["id"])
        run = self.store.get("runs", task["run_id"])
        asg = self._latest_impl(task)
        agent, wt, old = asg["agent"], asg["worktree_path"], asg["commit_sha"]
        findings = [f for r in self.store.query("reviews", "task_id=?", (task["id"],))
                    if r["reviewed_commit_sha"] == old and r["verdict"] != Verdict.APPROVED
                    for f in (r["findings"] or [r["summary"]])]
        rev = (task["revisions"] or 0) + 1
        self.store.update("tasks", task["id"], status=TaskStatus.RUNNING, revisions=rev)
        self.store.event(run["id"], "REVISION_STARTED", task["id"], agent, {"findings": findings, "revision": rev})
        t2 = dict(task); t2["revisions"] = rev
        t2["description"] = ((task["description"] or task["title"])
                             + "\n\nADDRESS THESE REVIEW FINDINGS:\n"
                             + "\n".join(f"- {f}" for f in findings))
        def sink(line):
            self.logs.setdefault(asg["id"], []).append(line)
            if on_line: on_line(agent, task["id"], line)
        t2 = self._inject_task_context(t2, run, agent)
        result = self._adapter(agent).run(t2, wt, run["integration_branch"], on_line=sink)
        self.store.update("assignments", asg["id"], commit_sha=result.commit_sha,
                          files_changed=result.files_changed, finished_at=now(),
                          tokens_in=(asg["tokens_in"] or 0) + result.tokens_in,
                          tokens_out=(asg["tokens_out"] or 0) + result.tokens_out,
                          cost_usd=(asg["cost_usd"] or 0) + result.cost_usd)
        self.store.update("tasks", task["id"], status=TaskStatus.REVIEW_READY)
        self.store.event(run["id"], "COMMIT_CREATED", task["id"], agent,
                         {"commit": result.commit_sha, "revision": rev})
        return result.commit_sha

    # -- integration + human gate -----------------------------------------
    def integrate_run(self, run_id: str) -> dict:
        """Merge approved task branches into the integration branch (plan section 23).
        Stops before main; conflicts are surfaced, never auto-resolved (section 24)."""
        from pathlib import Path
        run = self.store.get("runs", run_id)
        proj = self.store.get("projects", run["project_id"])
        tasks = self.store.query("tasks", "run_id=?", (run_id,))
        if not tasks or not all(t["status"] == TaskStatus.APPROVED for t in tasks):
            return {"ok": False, "reason": "not all tasks approved"}
        self.store.update("runs", run_id, status=RunStatus.INTEGRATING)
        repo, integ = proj["repo_path"], run["integration_branch"]
        iwt = str(Path(repo) / ".worktrees" / run_id / "_integration")
        if not Path(iwt).exists():
            subprocess.run(["git", "-C", repo, "worktree", "add", iwt, integ],
                           capture_output=True, text=True)
        conflicts = []
        for t in tasks:
            branch = self._latest_impl(t)["branch"]
            m = subprocess.run(["git", "-C", iwt, "merge", "--no-ff", "--no-edit", branch],
                               capture_output=True, text=True)
            if m.returncode != 0:
                subprocess.run(["git", "-C", iwt, "merge", "--abort"], capture_output=True, text=True)
                conflicts.append(t["title"])
                self.store.event(run_id, "INTEGRATION_CONFLICT", t["id"], None, {"branch": branch})
            else:
                self.store.event(run_id, "TASK_INTEGRATED", t["id"], None, {"branch": branch})
        validation = None
        if proj.get("test_command") and not conflicts:
            v = subprocess.run(proj["test_command"], cwd=iwt, shell=True, capture_output=True, text=True)
            validation = {"command": proj["test_command"], "exit_code": v.returncode,
                          "passed": v.returncode == 0}
            self.store.event(run_id, "VALIDATION_COMPLETED", None, None, validation)
        self.store.update("runs", run_id, status=RunStatus.WAITING_FOR_USER)
        self.store.event(run_id, "RUN_READY", None, None, {"conflicts": conflicts})
        return {"ok": not conflicts and (validation is None or validation["passed"]),
                "conflicts": conflicts, "validation": validation, "integration_branch": integ}

    def run_summary(self, run_id: str) -> dict:
        run = self.store.get("runs", run_id)
        tasks = self.store.query("tasks", "run_id=?", (run_id,))
        asgs = [a for t in tasks for a in self.store.query("assignments", "task_id=?", (t["id"],))]
        reviews = [r for t in tasks for r in self.store.query("reviews", "task_id=?", (t["id"],))]
        return {
            "status": run["status"], "goal": run["goal"],
            "integration_branch": run["integration_branch"],
            "tasks": {"total": len(tasks),
                      "approved": sum(1 for t in tasks if t["status"] == TaskStatus.APPROVED),
                      "failed": sum(1 for t in tasks if t["status"] == TaskStatus.FAILED)},
            "reviews": len(reviews),
            "cost_usd": round(sum(a["cost_usd"] or 0 for a in asgs), 4),
            "tokens_in": sum(a["tokens_in"] or 0 for a in asgs),
            "tokens_out": sum(a["tokens_out"] or 0 for a in asgs),
        }

    def approve_run(self, run_id: str) -> dict:
        self.store.update("runs", run_id, status=RunStatus.COMPLETED, completed_at=now())
        self.store.event(run_id, "RUN_APPROVED", None, None, {})
        self._write_run_memory(run_id)
        return self.run_summary(run_id)

    def _write_run_memory(self, run_id: str) -> None:
        """Deterministic factual run summary → Omni memory (Obsidian _Omni). Non-fatal."""
        if not self.knowledge:
            return
        try:
            run = self.store.get("runs", run_id)
            proj = self.store.get("projects", run["project_id"])
            tasks = self.store.query("tasks", "run_id=?", (run_id,))
            lines = [f"# {run['goal']}", "", f"Project: {proj['name'] if proj else ''}",
                     f"Run: {run_id}", ""]
            commits = []
            for t in tasks:
                asg = self._latest_impl(t) or {}
                sha = asg.get("commit_sha") or ""
                if sha:
                    commits.append(sha)
                verds = ", ".join(f"{r['reviewer_agent']}:{r['verdict']}"
                                  for r in self.store.query("reviews", "task_id=?", (t["id"],))) or "—"
                lines += [f"## {t['title']} — {t['status']}",
                          f"- agent: {asg.get('agent', '—')}",
                          f"- commit: {sha[:8] or '—'} ({asg.get('files_changed', 0)} files)",
                          f"- reviews: {verds}", ""]
            from ..knowledge.types import MemoryRecord
            uri = self.knowledge.write_memory(MemoryRecord(
                kind="run-summary", project=(proj["name"].lower() if proj else "global"),
                title=f"{run['goal']} {run_id}", body="\n".join(lines),
                run_id=run_id, status="generated", source_commits=commits))
            if uri:
                self.store.event(run_id, "MEMORY_WRITTEN", None, None, {"uri": uri})
        except Exception:
            pass

    # -- driver ------------------------------------------------------------
    def drive(self, run_id: str, on_line=None, max_revisions: int = 1, max_cycles: int = 8) -> dict:
        """Run the whole loop: execute -> review -> revise -> integrate -> gate."""
        for _ in range(max_cycles):
            self.execute_run(run_id, on_line=on_line)
            progressed = False
            for t in self.store.query("tasks", "run_id=? AND status=?", (run_id, TaskStatus.REVIEW_READY)):
                self.request_reviews(t, on_line=on_line); progressed = True
            for t in self.store.query("tasks", "run_id=? AND status=?", (run_id, TaskStatus.CHANGES_REQUESTED)):
                if (t["revisions"] or 0) < max_revisions:
                    self.revise_task(t, on_line=on_line); progressed = True
                else:
                    self.store.update("tasks", t["id"], status=TaskStatus.FAILED)
                    self.store.event(run_id, "TASK_FAILED", t["id"], None, {"reason": "max revisions"})
            tasks = self.store.query("tasks", "run_id=?", (run_id,))
            if all(t["status"] in (TaskStatus.APPROVED, TaskStatus.FAILED) for t in tasks):
                break
            if not progressed and not self.ready_tasks(run_id):
                break
        tasks = self.store.query("tasks", "run_id=?", (run_id,))
        if tasks and all(t["status"] == TaskStatus.APPROVED for t in tasks):
            self.integrate_run(run_id)
        else:
            self.store.update("runs", run_id, status=RunStatus.WAITING_FOR_USER)
        return self.run_summary(run_id)
