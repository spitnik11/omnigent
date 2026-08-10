"""Harness registry + runner.

Framework-independent core: run a logged-in agent CLI (claude/grok/codex)
headlessly in a project directory and capture its output. CrewAI (flow.py)
and the CLI both build on this. The single extension seam is harnesses.yaml.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
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


def run(harness: Harness, prompt: str, project: str | None = None, timeout: int = 1800,
        on_line=None, on_start=None) -> Result:
    """Run one harness headlessly, streaming stdout line-by-line.

    Backward compatible: still returns a Result with the full captured output, so
    existing callers (CLI, Flow) work unchanged. Optional hooks:
      on_line(str)      called per output line as it arrives (live streaming)
      on_start(Popen)   receives the process handle (for stop/kill)
    A watchdog enforces the hard timeout even if the process goes silent.
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
    lines: list[str] = []
    try:
        p = subprocess.Popen(argv, cwd=proj, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1,
                             encoding="utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return Result(harness.name, False, f"error launching '{harness.name}': {e}",
                      time.monotonic() - start, 1)
    if on_start:
        try: on_start(p)
        except Exception: pass
    timed_out = {"v": False}
    def _kill():
        timed_out["v"] = True
        try: p.kill()
        except Exception: pass
    watchdog = threading.Timer(timeout, _kill)
    watchdog.start()
    try:
        for line in p.stdout:
            line = line.rstrip("\r\n")
            lines.append(line)
            if on_line:
                try: on_line(line)
                except Exception: pass
        p.wait()
    except Exception as e:  # noqa: BLE001
        lines.append(f"[error: {e}]")
    finally:
        watchdog.cancel()
    if timed_out["v"]:
        lines.append(f"[killed: exceeded {timeout}s timeout]")
    rc = p.returncode if p.returncode is not None else 1
    out = "\n".join(lines).strip()
    ok = (rc == 0) and not timed_out["v"]
    return Result(harness.name, ok, out, time.monotonic() - start, 124 if timed_out["v"] else rc)


if __name__ == "__main__":
    # Self-check: config loads and detection runs without touching the network.
    hs = load_harnesses()
    assert hs, "no harnesses defined in harnesses.yaml"
    for n, h in hs.items():
        assert h.name == n
        print(f"{n:8} available={h.available!s:5} path={h.path}")
    print("harness self-check ok")
