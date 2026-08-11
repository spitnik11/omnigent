"""knowledge.yaml loader. Separate from harnesses.yaml (agents) by design.

Disabled unless knowledge.yaml exists AND enabled: true — so default behaviour is
byte-identical to today. The RAG index lives in Omni's state dir, never in the vault.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_YAML = REPO_ROOT / "knowledge.yaml"
STATE_DIR = Path(os.environ.get("OMNI_STATE_DIR", str(Path.home() / ".omni")))
KNOWLEDGE_DB = STATE_DIR / "knowledge" / "knowledge.db"


@dataclass
class SourceCfg:
    name: str
    type: str = "obsidian"            # obsidian | repository
    path: str = ""                    # resolved absolute path ("" = unavailable)
    include: list = field(default_factory=lambda: ["**/*.md"])
    exclude: list = field(default_factory=list)
    write_root: str = "_Omni"


@dataclass
class KnowledgeConfig:
    enabled: bool = False
    version: int = 1
    sources: list = field(default_factory=list)
    lexical: bool = True
    vector_enabled: bool = False
    max_results: int = 8
    max_context_chars: int = 12000


def _bool(v, default=True):
    if isinstance(v, dict):
        return bool(v.get("enabled", default))
    return bool(v) if v is not None else default


def load_config(path: Path | str = DEFAULT_YAML) -> KnowledgeConfig:
    p = Path(path)
    if not p.exists():
        return KnowledgeConfig(enabled=False)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not raw.get("enabled"):
        return KnowledgeConfig(enabled=False)
    sources = []
    for name, s in (raw.get("sources") or {}).items():
        s = s or {}
        path_val = os.environ.get(s["path_env"], "") if s.get("path_env") else s.get("path", "")
        sources.append(SourceCfg(
            name=name, type=s.get("type", "obsidian"), path=str(path_val or ""),
            include=s.get("include") or ["**/*.md"], exclude=s.get("exclude") or [],
            write_root=s.get("write_root", "_Omni")))
    r = raw.get("retrieval") or {}
    d = raw.get("defaults") or {}
    return KnowledgeConfig(
        enabled=True, version=raw.get("version", 1), sources=sources,
        lexical=_bool(r.get("lexical"), True),
        vector_enabled=_bool(r.get("vector"), False),
        max_results=int(d.get("max_results", 8)),
        max_context_chars=int(d.get("max_context_chars", 12000)))
