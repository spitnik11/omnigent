"""KnowledgeService — the one façade the workflow layer talks to.

Every public method is failure-tolerant: retrieval/sync/write problems return
empty/no-op, never raise into a Run. Lexical (FTS5) retrieval; embeddings later.
"""
from __future__ import annotations

from pathlib import Path

from .chunker import chunk_markdown
from .config import KNOWLEDGE_DB, KnowledgeConfig, load_config
from .retrieval import format_context, query_for_review, query_for_task
from .sources import ObsidianSource, RepoDocsSource
from .store import KnowledgeStore
from .types import KnowledgeQuery, MemoryRecord
from .writer import ObsidianWriter


class KnowledgeService:
    def __init__(self, config: KnowledgeConfig, store: KnowledgeStore, sources: list, writer: ObsidianWriter):
        self.config = config
        self.store = store
        self.sources = sources
        self.writer = writer

    @classmethod
    def load(cls, config: KnowledgeConfig | None = None, repo_paths=None, db_path=None):
        """Returns a KnowledgeService, or None if knowledge is disabled."""
        config = config or load_config()
        if not config.enabled:
            return None
        store = KnowledgeStore(db_path or KNOWLEDGE_DB)
        sources, vault_path, write_root = [], "", "_Omni"
        for s in config.sources:
            if s.type == "obsidian":
                sources.append(ObsidianSource(s.name, s.path, s.include, s.exclude))
                vault_path, write_root = s.path or vault_path, s.write_root
        for proj, path in (repo_paths or []):
            sources.append(RepoDocsSource(proj, path))
        return cls(config, store, sources, ObsidianWriter(vault_path, write_root))

    def add_repo(self, project: str, repo_path: str) -> None:
        """Register a project's repo docs as a source (idempotent)."""
        if not repo_path:
            return
        prefix = f"repo://{project.lower()}/"
        if any(getattr(s, "uri_prefix", "") == prefix for s in self.sources):
            return
        self.sources.append(RepoDocsSource(project, repo_path))

    # -- indexing --
    def sync(self) -> dict:
        totals = {"indexed": 0, "skipped": 0, "deleted": 0, "errors": 0}
        for src in self.sources:
            try:
                existing = self.store.hashes_with_prefix(src.uri_prefix)
                seen = set()
                for doc in src.scan():
                    seen.add(doc.source_uri)
                    if existing.get(doc.source_uri) == doc.content_hash:
                        totals["skipped"] += 1
                        continue
                    self.store.upsert(doc, chunk_markdown(doc.content))
                    totals["indexed"] += 1
                for uri in existing:
                    if uri not in seen:
                        self.store.delete(uri)
                        totals["deleted"] += 1
            except Exception:
                totals["errors"] += 1
        return totals

    # -- retrieval (non-fatal) --
    def context_for_task(self, task: dict, project: str = "", goal: str = "") -> tuple[str, list[dict]]:
        try:
            hits = self.store.search(query_for_task(task, project, goal, self.config.max_results))
            return format_context(hits, self.config.max_context_chars)
        except Exception:
            return "", []

    def context_for_review(self, task: dict, changed_files=None, project: str = "") -> tuple[str, list[dict]]:
        try:
            hits = self.store.search(query_for_review(task, changed_files, project, self.config.max_results))
            return format_context(hits, self.config.max_context_chars)
        except Exception:
            return "", []

    def write_memory(self, record: MemoryRecord) -> str | None:
        return self.writer.write(record)

    # -- CLI helpers --
    def search(self, text: str, project: str | None = None):
        return self.store.search(KnowledgeQuery(text=text, project=project,
                                                limit=self.config.max_results))

    def status(self) -> dict:
        return {"enabled": True, "sources": [s.name for s in self.sources],
                "writer": "vault" if self.writer.in_vault else "state-dir", **self.store.stats()}

    def doctor(self) -> list[tuple[str, bool, str]]:
        checks = []
        for s in self.sources:
            root = getattr(s, "root", None)
            checks.append((f"source {s.name}", bool(root and Path(root).exists()),
                           str(root) if root else "no path (set the env var)"))
        checks.append(("knowledge.db writable", True, self.store.db_path))
        checks.append(("FTS5", self.store.fts, "full-text index" if self.store.fts else "LIKE fallback"))
        checks.append(("writer target", True, str(self.writer.base)))
        return checks
