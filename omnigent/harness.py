"""Harness registry + runner.

Framework-independent core: run a logged-in agent CLI (claude/grok/codex)
headlessly in a project directory and capture its output. CrewAI (flow.py)
and the CLI both build on this. The single extension seam is harnesses.yaml.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / "harnesses.yaml"


@dataclass
class Harness:
    name: str
    bin: str
    args: list[str] = field(default_factory=list)
    detect: str = ""
    enabled: bool = True

    @property
    def path(self) -> str | None:
        return shutil.which(self.detect or self.bin) or shutil.which(self.bin)

    @property
    def available(self) -> bool:
        return self.enabled and self.path is not None


@dataclass
class Result:
    harness: str
    ok: bool
    output: str
    seconds: float
    returncode: int


def load_config(path: Path | str = CONFIG) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_harnesses(cfg: dict | None = None) -> dict[str, Harness]:
    cfg = cfg if cfg is not None else load_config()
    out: dict[str, Harness] = {}
    for name, h in (cfg.get("harnesses") or {}).items():
        h = h or {}
        out[name] = Harness(
            name=name,
            bin=h.get("bin", name),
            args=list(h.get("args", [])),
            detect=h.get("detect", h.get("bin", name)),
            enabled=h.get("enabled", True),
        )
    return out


def run(harness: Harness, prompt: str, project: str | None = None, timeout: int = 1800) -> Result:
    """Run one harness headlessly. Blocks until the agent finishes or times out.

    # ponytail: captures output (no live streaming); add --stream if long runs
    # with no feedback become annoying in practice.
    """
    if not harness.available:
        return Result(harness.name, False,
                      f"harness '{harness.name}' unavailable (bin '{harness.bin}' not found)",
                      0.0, 127)
    proj = str(Path(project).resolve()) if project else str(Path.cwd())
    argv = [harness.path] + [
        a.replace("{prompt}", prompt).replace("{project}", proj) for a in harness.args
    ]
    start = time.monotonic()
    try:
        p = subprocess.run(argv, cwd=proj, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "").strip()
        if p.stderr and p.stderr.strip():
            out = (out + "\n[stderr] " + p.stderr.strip()).strip()
        return Result(harness.name, p.returncode == 0, out, time.monotonic() - start, p.returncode)
    except subprocess.TimeoutExpired:
        return Result(harness.name, False, f"timed out after {timeout}s",
                      time.monotonic() - start, 124)
    except Exception as e:  # noqa: BLE001
        return Result(harness.name, False, f"error running '{harness.name}': {e}",
                      time.monotonic() - start, 1)


if __name__ == "__main__":
    # Self-check: config loads and detection runs without touching the network.
    hs = load_harnesses()
    assert hs, "no harnesses defined in harnesses.yaml"
    for n, h in hs.items():
        assert h.name == n
        print(f"{n:8} available={h.available!s:5} path={h.path}")
    print("harness self-check ok")
