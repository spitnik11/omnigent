"""knowledge.db — documents + chunks + FTS5 lexical index. Disposable/rebuildable.

Deleting knowledge.db is safe: Omni re-indexes from its sources. Falls back to a
LIKE scan if this Python's sqlite3 lacks FTS5 (doctor reports which).
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path

from .types import KnowledgeDocument, KnowledgeHit, KnowledgeQuery

SCHEMA_DOCS = """
CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, source TEXT, source_uri TEXT UNIQUE, title TEXT, project TEXT,
  kind TEXT, status TEXT, content_hash TEXT, modified_at REAL, metadata_json TEXT);
CREATE TABLE IF NOT EXISTS chunks(
  id TEXT PRIMARY KEY, document_id TEXT, chunk_index INTEGER, heading_path TEXT, content TEXT);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(document_id);
"""


def _fts_available(conn) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(content)")
        return True
    except sqlite3.OperationalError:
        return False


class KnowledgeStore:
    def __init__(self, db_path: Path | str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._c = sqlite3.connect(self.db_path, check_same_thread=False)
        self._c.row_factory = sqlite3.Row
        self._c.executescript(SCHEMA_DOCS)
        self.fts = _fts_available(self._c)
        self._c.commit()

    # -- write --
    def hashes_with_prefix(self, prefix: str) -> dict[str, str]:
        rows = self._c.execute(
            "SELECT source_uri, content_hash FROM documents WHERE source_uri LIKE ?", (prefix + "%",))
        return {r["source_uri"]: r["content_hash"] for r in rows}

    def upsert(self, doc: KnowledgeDocument, chunks: list[tuple[str, str]]) -> None:
        with self._lock:
            self._delete_chunks(doc.id)
            self._c.execute("DELETE FROM documents WHERE id=?", (doc.id,))
            self._c.execute(
                "INSERT INTO documents(id,source,source_uri,title,project,kind,status,content_hash,modified_at,metadata_json)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (doc.id, doc.source, doc.source_uri, doc.title, doc.project, doc.kind,
                 doc.status, doc.content_hash, doc.modified_at, json.dumps(doc.metadata)))
            for i, (heading, content) in enumerate(chunks):
                cid = f"{doc.id}:{i}"
                cur = self._c.execute(
                    "INSERT INTO chunks(id,document_id,chunk_index,heading_path,content) VALUES(?,?,?,?,?)",
                    (cid, doc.id, i, heading, content))
                if self.fts:
                    self._c.execute("INSERT INTO chunks_fts(rowid,content) VALUES(?,?)", (cur.lastrowid, content))
            self._c.commit()

    def delete(self, source_uri: str) -> None:
        with self._lock:
            row = self._c.execute("SELECT id FROM documents WHERE source_uri=?", (source_uri,)).fetchone()
            if row:
                self._delete_chunks(row["id"])
                self._c.execute("DELETE FROM documents WHERE id=?", (row["id"],))
                self._c.commit()

    def _delete_chunks(self, doc_id: str) -> None:
        if self.fts:
            rows = self._c.execute("SELECT rowid FROM chunks WHERE document_id=?", (doc_id,)).fetchall()
            for r in rows:
                self._c.execute("DELETE FROM chunks_fts WHERE rowid=?", (r["rowid"],))
        self._c.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))

    # -- read --
    def search(self, q: KnowledgeQuery) -> list[KnowledgeHit]:
        terms = re.findall(r"[A-Za-z0-9_]{2,}", (q.text or "").lower())
        if not terms:
            return []
        with self._lock:                       # single connection shared across run threads
            return self._search(q, terms)

    def _search(self, q: KnowledgeQuery, terms: list[str]) -> list[KnowledgeHit]:
        statuses = q.statuses or ["active"]
        st_ph = ",".join("?" * len(statuses))
        if self.fts:
            match = " OR ".join(dict.fromkeys(terms))  # dedupe, keep order
            sql = (f"SELECT d.source,d.source_uri,d.project,d.kind,c.heading_path,c.content,"
                   f"bm25(chunks_fts) AS score FROM chunks_fts "
                   f"JOIN chunks c ON c.rowid=chunks_fts.rowid "
                   f"JOIN documents d ON d.id=c.document_id "
                   f"WHERE chunks_fts MATCH ? AND d.status IN ({st_ph}) "
                   f"{'AND d.project=? ' if q.project else ''}"
                   f"{'AND d.kind IN (' + ','.join('?'*len(q.kinds)) + ') ' if q.kinds else ''}"
                   f"ORDER BY score LIMIT ?")
            args = [match, *statuses]
            if q.project: args.append(q.project)
            if q.kinds: args += list(q.kinds)
            args.append(q.limit * 3)
            rows = self._c.execute(sql, args).fetchall()
        else:  # LIKE fallback
            like = "%" + terms[0] + "%"
            sql = (f"SELECT d.source,d.source_uri,d.project,d.kind,c.heading_path,c.content,0 AS score "
                   f"FROM chunks c JOIN documents d ON d.id=c.document_id "
                   f"WHERE c.content LIKE ? AND d.status IN ({st_ph}) "
                   f"{'AND d.project=? ' if q.project else ''} LIMIT ?")
            args = [like, *statuses]
            if q.project: args.append(q.project)
            args.append(q.limit * 3)
            rows = self._c.execute(sql, args).fetchall()
        seen, hits = set(), []
        for r in rows:
            if r["source_uri"] in seen:
                continue
            seen.add(r["source_uri"])
            snippet = (r["content"] or "").strip().replace("\n", " ")
            hits.append(KnowledgeHit(source=r["source"], uri=r["source_uri"], project=r["project"] or "",
                                     kind=r["kind"] or "note", heading_path=r["heading_path"] or "",
                                     snippet=snippet[:400], score=float(r["score"])))
            if len(hits) >= q.limit:
                break
        return hits

    def stats(self) -> dict:
        d = self._c.execute("SELECT COUNT(*) n FROM documents").fetchone()["n"]
        c = self._c.execute("SELECT COUNT(*) n FROM chunks").fetchone()["n"]
        by_src = {r["source"]: r["n"] for r in
                  self._c.execute("SELECT source, COUNT(*) n FROM documents GROUP BY source")}
        return {"documents": d, "chunks": c, "by_source": by_src, "fts": self.fts}
