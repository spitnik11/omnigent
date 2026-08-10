# Omnigent

A **multi-harness orchestrator** over your logged-in agent CLIs — **Claude**,
**Grok**, and **Codex**. One command routes a task to the right agent and runs
it headlessly inside a project directory. Built with **CrewAI** as the
orchestration engine.

No API keys, no gateways, no server. The CLIs already hold your subscriptions;
Omnigent just decides which one to call and runs it.

```
omnigent run "task"  ─►  CrewAI Flow  ─►  router  ─►  harness.run()  ─►  claude / grok / codex CLI
      the interface        engine        (free)         (subprocess in your project dir)
                                    ▲
                          harnesses.yaml  ← the one seam: add a provider = add an entry
```

## Install

```bash
cd "Z:\Claude app\omnigent"
pip install -e .
```

Requires Python 3.10–3.13. Pulls in CrewAI + PyYAML.

## Use

```bash
omnigent list                              # which harnesses are available
omnigent run "search the web for X"        # routed to grok by keyword
omnigent run "@claude explain this repo" --project "Z:\Claude app\trawl"
omnigent repl --project "Z:\Claude app\trawl"
omnigent web                               # local web UI at http://127.0.0.1:8770
```

### Web UI

`omnigent web [--port 8770]` serves a single-page UI (Starlette + uvicorn, no
new deps): task box, harness picker, project dir, Run. One task at a time;
runs block until the agent finishes. Ctrl/Cmd+Enter runs.

- **Routing** (when you don't force one): explicit `--harness X` > leading
  `@name ` > keyword rules in `harnesses.yaml` > default. It only ever routes
  to an *available* harness.
- **Force** a harness: `--harness grok` or prefix the task with `@grok `.
- **Project dir**: `--project DIR` runs the agent there (defaults to cwd).

## The one seam: `harnesses.yaml`

Every provider is one entry. `{prompt}` / `{project}` are substituted at run
time; availability is auto-detected. Add a fourth agent, change a flag, or
point `bin` at a full path — no code changes.

```yaml
harnesses:
  claude:
    bin: claude
    args: ["-p", "{prompt}", "--permission-mode", "acceptEdits"]
```

Autonomy is tuned here. **Default is full hands-off:** claude/grok use
`--permission-mode bypassPermissions`; codex uses
`--dangerously-bypass-approvals-and-sandbox`. Dial back to `acceptEdits`
(claude/grok) or `-s workspace-write` (codex) to reintroduce guardrails.

## Current status on this machine

- **claude** — available (`~/.local/bin/claude.exe`)
- **grok** — available (`~/.grok/bin/grok.exe`)
- **codex** — *unavailable*: the OpenAI Codex CLI isn't installed. Install it
  (`npm i -g @openai/codex`) and it activates automatically — no code change.

## Backwards compatibility

The core (`harness.py` + `router.py` + `core.py` + `cli.py`) runs with **zero
CrewAI dependency**. `flow.py` is the CrewAI layer the CLI prefers; if crewai
isn't importable the CLI transparently falls back to the direct path. Either
way `omnigent run` works.

## Docker

The harness CLIs are **not** in the image — they hold your host subscriptions.
See the `Dockerfile` header: use Docker for packaging/CI of the orchestrator,
or bake in the CLIs + API keys for a fully-contained run. This is the honest
tradeoff the "just `docker compose up`" plans gloss over.

## Tests

```bash
python test_router.py         # routing logic
python -m omnigent.harness    # config loads + harness detection
```

## Layout

```
harnesses.yaml        provider registry + routing rules  (the seam)
omnigent/
  harness.py          load + detect + run a CLI (framework-independent)
  router.py           deterministic task -> harness
  core.py             direct orchestrate() (no-CrewAI fallback)
  flow.py             CrewAI Flow (the engine)
  cli.py              the interface: list / run / repl
test_router.py        self-check
Dockerfile / docker-compose.yml
```
