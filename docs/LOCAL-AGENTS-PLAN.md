# Local Coding Agents — Integration Plan

Add local, Ollama-backed coding agents (**Aider, OpenCode, Goose**) to Omni so they
**offload implementation from the paid API CLIs** (claude/codex/grok), plus a
**local-only sandbox profile** that runs them in parallel. Everything is **additive
and backwards-compatible** — no existing behavior changes until you opt in.

> Core insight: a local coding agent is **just another harness**. The whole
> integration is new `harnesses.yaml` entries + a profile filter + a routing
> preference. Adding agent #4…N later = one entry each.

## Decisions
- **Agents (first 3):** Aider (git auto-commit → ideal for commit-derived results),
  OpenCode (flexible local routing, client-server), Goose (headless + sub-agents).
- **Model runner:** the already-running **Ollama** (`http://localhost:11434`, from the
  Hermes/SillyTavern stack). No LM Studio.
- **Coding model:** `qwen2.5-coder:7b` (fits 12 GB). Stretch: `deepseek-coder-v2:16b-lite`.
- **Sandbox:** reuse Omni with `--profile local` (not a second app).
- **GPU reality:** 12 GB holds one model at a time → agents run in parallel but share
  one Ollama model (inference queues). Parallel orchestration, serialized GPU.

## Additive schema (backwards-compatible)

`harnesses.yaml` — existing entries unchanged; new optional fields + a profiles map:
```yaml
harnesses:
  # ...claude / grok / codex unchanged (implicitly kind: api, cost: 1)...
  aider:
    bin: aider
    detect: aider
    kind: local            # NEW (default "api" if omitted)
    cost: 0                # NEW (default 1) — 0 = free/local
    capabilities: [implement, refactor, tests]   # NEW (optional)
    # Aider runs one message headlessly and auto-commits:
    args: ["--model", "ollama/qwen2.5-coder:7b", "--yes", "--no-stream", "--message", "{prompt}"]
  opencode:
    bin: opencode
    detect: opencode
    kind: local
    cost: 0
    args: ["run", "{prompt}"]        # model set via opencode config -> ollama
  goose:
    bin: goose
    detect: goose
    kind: local
    cost: 0
    args: ["run", "-t", "{prompt}"]  # provider ollama set via goose config

profiles:                # NEW. No profile selected -> all harnesses (today's behavior).
  default: [claude, codex, grok, aider, opencode, goose]
  api:     [claude, codex, grok]
  local:   [aider, opencode, goose]
```

Env for local agents (set by the runner, not committed): `OLLAMA_API_BASE=http://localhost:11434`.

## Code touch-points (all additive, guarded)
- `harness.py`: `Harness` gains `kind`/`cost`/`capabilities` (defaults preserve today);
  `load_harnesses(cfg, profile=None)` filters by profile (None = all). No caller breaks.
- `router.py`: `route()` gains a preference layer — for `role == IMPLEMENT`, prefer an
  available `cost == 0` harness whose `capabilities` match; keep API harnesses for
  REVIEW and planning. Existing keyword rules still apply as fallback. Guarded so the
  default (no local agents installed) behaves exactly as now.
- `cli.py` / `web.py`: optional `--profile <name>` → passed to `load_harnesses`.
  Sandbox = `omnigent web --profile local`.
- Offload rule (the point): **local implements, cloud reviews.** So a run's IMPLEMENT
  assignments go to aider/opencode/goose (free, private, offline); the 2-of-3 cross
  review stays on claude/codex/grok (quality gate). Cuts API tokens, keeps code local.

## Phases (each shippable + tested; regression-guarded)
0. **Protect** — run `test_router.py`, `test_workflow.py`, `test_knowledge.py` as the baseline.
1. **One local harness** — Aider entry + install aider + `ollama pull qwen2.5-coder:7b`;
   prove `omnigent run --harness aider "..."` works fully offline.
2. **Profiles** — `kind/cost/profiles` + `--profile`; sandbox = `--profile local`. Tests.
3. **Cost-aware routing** — local implements, API reviews. Tests assert the split.
4. **Add OpenCode + Goose** harness entries (+ their local model config).
5. **Parallel local swarm** — the sandbox profile uses Omni's existing worktree
   parallelism (GPU-serialized). Verify N local assignments run concurrently.
6. **Later** — Cline / Continue / Plandex / Tabby as entries; per-task model selection;
   Goose sub-agents; optional second Ollama instance for true concurrency on more VRAM.

## Host prerequisites (not agent tasks)
- `ollama pull qwen2.5-coder:7b` (into the running ollama-backend container).
- Install the agent CLIs: `pip install aider-chat` · OpenCode (`npm i -g opencode-ai` or binary)
  · Goose (official installer). Each is detect-gated, so Omni stays green until they exist.

## Non-negotiables (maintainability rules)
- Never break existing api harnesses or tests. `kind`/`cost`/`profile` all default to today.
- A local agent that isn't installed = unavailable, never an error.
- Reviews stay cross-model + commit-SHA-pinned regardless of who implemented.
- One config seam (`harnesses.yaml`) — no per-agent branching in the engine.
