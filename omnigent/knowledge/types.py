"""Stable knowledge interfaces + records. Nothing here imports workflow code."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Protocol


def content_hash(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:16]


@dataclass
class KnowledgeDocument:
    source: str                       # obsidian | repo | memory
    source_uri: str                   # stable, human-readable (obsidian://…, repo://…)
    title: str = ""
    project: str = ""
    kind: str = "note"                # decision|convention|constraint|run-summary|research|note
    status: str = "active"            # active|draft|superseded|deprecated
    content: str = ""
    modified_at: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return content_hash(self.source_uri)

    @property
    def content_hash(self) -> str:
        return content_hash(self.content)


@dataclass
class KnowledgeQuery:
    text: str
    project: str | None = None
    kinds: list[str] | None = None
    statuses: list[str] = field(default_factory=lambda: ["active"])
    limit: int = 8


@dataclass
class KnowledgeHit:
    source: str
    uri: str
    project: str
    kind: str
    heading_path: str
    snippet: str
    score: float


@dataclass
class MemoryRecord:
    kind: str
    project: str
    title: str
    body: str
    run_id: str = ""
    status: str = "generated"
    source_commits: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class KnowledgeSource(Protocol):
    name: str
    def scan(self) -> Iterable[KnowledgeDocument]: ...


class KnowledgeWriter(Protocol):
    def write(self, memory: MemoryRecord) -> str | None: ...


# Future (Phase 7): Retriever / EmbeddingProvider protocols. Lexical retrieval is
# implemented directly on the store in v1; adding a VectorRetriever later slots in
# behind KnowledgeService.search without touching workflow code.
