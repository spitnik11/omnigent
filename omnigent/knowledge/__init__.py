"""Omni knowledge layer — optional RAG over Obsidian + repo docs + Omni memory.

Strictly separate from workflow state: this package never mutates omni.db and its
failure never fails a Run. Lexical (SQLite FTS5) retrieval in v1, no embeddings.
Flattened from the spec's deep sources/indexing/retrieval/writers tree into a few
modules — same boundaries, less ceremony.
"""
