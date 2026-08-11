"""Knowledge sources — read-only scanners that yield KnowledgeDocuments.

ObsidianSource: the shared vault (Markdown + frontmatter). RepoDocsSource: a repo's
README/docs. Neither ever writes. Project is taken from frontmatter or the path
(…/Projects/<Name>/… or _Omni/Projects/<name>/…).
"""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

import yaml

from .types import KnowledgeDocument


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                meta = yaml.safe_load(text[3:end].strip()) or {}
            except Exception:
                meta = {}
            if isinstance(meta, dict):
                return meta, text[end + 4:].lstrip("\n")
    return {}, text


def _excluded(relposix: str, patterns: list[str]) -> bool:
    for p in patterns:
        if p.endswith("/**"):
            prefix = p[:-3]
            if relposix == prefix or relposix.startswith(prefix + "/"):
                return True
        elif fnmatch(relposix, p):
            return True
    return False


def _project_from_path(relposix: str) -> str:
    parts = relposix.split("/")
    if "Projects" in parts:
        i = parts.index("Projects")
        if i + 1 < len(parts):
            return parts[i + 1].lower()
    return ""


class ObsidianSource:
    uri_prefix = "obsidian://"

    def __init__(self, name: str, path: str, include=None, exclude=None):
        self.name = name
        self.root = Path(path) if path else None
        self.include = include or ["**/*.md"]
        self.exclude = exclude or []

    def scan(self):
        if not self.root or not self.root.exists():
            return
        for f in self.root.rglob("*.md"):
            rel = f.relative_to(self.root).as_posix()
            if _excluded(rel, self.exclude):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            meta, body = parse_frontmatter(text)
            yield KnowledgeDocument(
                source="obsidian", source_uri=f"obsidian://{rel}",
                title=str(meta.get("title") or f.stem),
                project=str(meta.get("project") or _project_from_path(rel)).lower(),
                kind=str(meta.get("kind") or "note"),
                status=str(meta.get("status") or "active"),
                content=body, modified_at=f.stat().st_mtime,
                metadata={"omni_managed": bool(meta.get("omni_managed", False)),
                          "importance": meta.get("importance", "")})


class RepoDocsSource:
    """Scans a single repo's docs. Constructed per-project by the caller."""
    def __init__(self, project: str, repo_path: str,
                 include=("README.md", "docs/**/*.md", "architecture/**/*.md", "*.md")):
        self.name = f"repo:{project}"
        self.project = project.lower()
        self.root = Path(repo_path) if repo_path else None
        self.include = list(include)
        self.uri_prefix = f"repo://{self.project}/"

    def scan(self):
        if not self.root or not self.root.exists():
            return
        seen = set()
        for pat in self.include:
            for f in self.root.glob(pat):
                if not f.is_file() or f.suffix != ".md" or f in seen:
                    continue
                seen.add(f)
                rel = f.relative_to(self.root).as_posix()
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                meta, body = parse_frontmatter(text)
                yield KnowledgeDocument(
                    source="repo", source_uri=f"repo://{self.project}/{rel}",
                    title=str(meta.get("title") or f.stem), project=self.project,
                    kind="doc", status="active", content=body, modified_at=f.stat().st_mtime)
