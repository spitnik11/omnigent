# Agent Rules

- Act as an autonomous maintainer with permission to read and modify every path in this repository.
- Create branches and worktrees, run tools and tests, commit changes, and merge into local `master` when the user authorizes the work.
- Never push remote branches or `master` unless the user explicitly requests a push.
- During an Omni run, the deterministic coordinator still owns state, scheduling, assignments, and review timing.
- When assigned as an Omni reviewer, stay read-only and judge only the pinned commit.
- Before editing, trace the affected flow and reuse existing code, stdlib, native features, or installed dependencies.
- Prefer the smallest root-cause fix; avoid speculative abstractions, boilerplate, dependencies, and files.
- Preserve validation, security, data-loss prevention, error handling, and accessibility.
- Review correctness, acceptance criteria, security, regressions, tests, performance, maintainability, and needless complexity.
- Add one focused runnable check for non-trivial logic and run relevant validation before committing.
