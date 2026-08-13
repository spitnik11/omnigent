# Agent Rules

- The deterministic coordinator owns state, scheduling, ownership, and review timing.
- Work only in the assigned worktree and owned paths; never touch `do_not_modify` paths.
- Reviews are commit-pinned and read-only: inspect and judge, never edit or delegate.
- Never push to `main`; integration stays human-gated.
- Before editing, trace the affected flow and reuse existing code, stdlib, native features, or installed dependencies.
- Prefer the smallest root-cause fix; avoid speculative abstractions, boilerplate, dependencies, and files.
- Preserve validation, security, data-loss prevention, error handling, and accessibility.
- Review correctness, acceptance criteria, security, regressions, tests, performance, maintainability, and needless complexity.
- Add one focused runnable check for non-trivial logic and run the Task Contract validation before committing.
- Review findings start with `- ` and end with exactly `VERDICT: APPROVED` or `VERDICT: CHANGES_REQUESTED`.
