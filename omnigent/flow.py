"""CrewAI Flow — the orchestration engine, per design.

Built with CrewAI (@start/@listen + typed state). No API key needed: routing
is deterministic and the "agents" are your logged-in CLIs, so the Flow never
makes an LLM call itself. Import-guarded by the CLI, so the core still runs if
crewai isn't installed.

Note: we deliberately do NOT use CrewAI's @router per-harness fan-out. That
would hardcode one @listen("name") per provider and break the "add a provider
= one YAML entry" seam. The routing decision lives in state.chosen; a single
listener executes it, so any number of harnesses works with zero code change.
"""
from __future__ import annotations

import os

# Keep the orchestrator non-interactive: stop CrewAI's first-run "view traces?"
# prompt from blocking headless runs. Override by exporting the var yourself.
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from .harness import load_config, load_harnesses, run
from .router import route, strip_prefix


class OmniState(BaseModel):
    task: str = ""
    harness: str = ""   # forced harness (optional)
    project: str = ""
    timeout: int = 1800
    profile: str = ""   # optional harnesses.yaml profile filter
    chosen: str = ""
    output: str = ""
    ok: bool = False
    seconds: float = 0.0


class OmnigentFlow(Flow[OmniState]):

    @start()
    def classify(self):
        self._cfg = load_config()
        self._hs = load_harnesses(self._cfg, profile=self.state.profile or None)
        self.state.chosen = route(
            self.state.task, self._hs, self._cfg,
            forced=self.state.harness or None,
        )

    @listen(classify)
    def execute(self):
        prompt = strip_prefix(self.state.task, self._hs)
        r = run(self._hs[self.state.chosen], prompt,
                self.state.project or None, self.state.timeout)
        self.state.chosen = r.harness
        self.state.output = r.output
        self.state.ok = r.ok
        self.state.seconds = r.seconds


def run_flow(task: str, harness: str | None = None, project: str | None = None,
             timeout: int = 1800, profile: str | None = None) -> OmniState:
    flow = OmnigentFlow()
    flow.kickoff(inputs={
        "task": task,
        "harness": harness or "",
        "project": project or "",
        "timeout": timeout,
        "profile": profile or "",
    })
    return flow.state
