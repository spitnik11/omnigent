"""Git worktree manager — the coordinator owns workspace creation.

Each implementation assignment gets its own branch + worktree directory under
<repo>/.worktrees/<run>/<name>. The agent CLI runs with that dir as cwd, so
three agents modify the same project concurrently without colliding. This is
our substitute for the plan's per-container mounts.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(repo: str, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


class WorktreeManager:
    def __init__(self, repo_path: str):
        self.repo = str(Path(repo_path).resolve())

    def ensure_branch(self, branch: str, base: str) -> None:
        """Create `branch` off `base` if it doesn't exist (e.g. the integration branch)."""
        exists = _git(self.repo, "branch", "--list", branch)
        if not exists:
            _git(self.repo, "branch", branch, base)

    def create(self, run_id: str, name: str, base_branch: str) -> tuple[str, str]:
        """Add a worktree on a fresh branch. Returns (branch, worktree_path)."""
        branch = f"task/{name}"
        wt = Path(self.repo) / ".worktrees" / run_id / name
        wt.parent.mkdir(parents=True, exist_ok=True)
        # remove a stale worktree/branch of the same name so re-runs are clean
        if wt.exists():
            self.remove(str(wt), force=True)
        if _git(self.repo, "branch", "--list", branch):
            _git(self.repo, "branch", "-D", branch, check=False)
        _git(self.repo, "worktree", "add", "-b", branch, str(wt), base_branch)
        return branch, str(wt)

    def head_sha(self, worktree_path: str) -> str:
        return _git(worktree_path, "rev-parse", "HEAD")

    def changed_files(self, worktree_path: str, base_branch: str) -> int:
        out = _git(worktree_path, "diff", "--name-only", f"{base_branch}...HEAD", check=False)
        return len([l for l in out.splitlines() if l.strip()])

    def is_dirty(self, worktree_path: str) -> bool:
        return bool(_git(worktree_path, "status", "--porcelain", check=False))

    def remove(self, worktree_path: str, force: bool = False) -> None:
        """Remove a worktree. Refuses to drop uncommitted work unless force=True."""
        if not force and Path(worktree_path).exists() and self.is_dirty(worktree_path):
            raise GitError(f"worktree has uncommitted changes: {worktree_path}")
        args = ["worktree", "remove", worktree_path]
        if force:
            args.append("--force")
        _git(self.repo, *args, check=False)

    def list(self) -> list[str]:
        out = _git(self.repo, "worktree", "list", "--porcelain", check=False)
        return [l.split(" ", 1)[1] for l in out.splitlines() if l.startswith("worktree ")]
