# Omni backlog

## P1 correctness and safety

- Enforce OS-level read-only review sandboxes. Reviews remain prompt-enforced today.
- Add coordinator-managed integration conflict resolution tasks for conflicting paths.
- Add a visible waiting-for-review-capacity state when two independent approvals are unavailable.

## P2 observability

- Switch each cloud harness to structured streaming output. Structured usage events are normalized now; legacy plain output still uses final regex reconciliation.
- Add transcript retention cleanup. JSONL audit logs are persisted under `~/.omni/transcripts` and paged on demand, but are not automatically expired yet.

## P3 robustness and polish

- Add a compact native dependency graph after task ownership and dependency data have enough real-run coverage.
- Add full transcript export and richer agent/task/verdict filters if native search becomes insufficient.
- Document or implement a host bridge for Docker; authenticated agent CLIs remain host-side.

## Opportunistic

- Add an LLM router only after deterministic routing shows measured misroutes.
- Persist legacy `runstore.py` history only if that separate one-shot interface still needs restart durability.
