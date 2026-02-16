"""Chunk, embed, and store documents in SQLite. Uses FastEmbed (384-dim)."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from grumpyclaw.memory.db import get_db_path, init_db


def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks for embedding."""
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        if end < len(text):
            last_space = chunk.rfind(" ")
            if last_space > max_chars // 2:
                end = start + last_space + 1
                chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap if overlap < (end - start) else end
    return [c for c in chunks if c]


class Indexer:
    """Index documents into SQLite with FastEmbed embeddings."""

    def __init__(
        self,
        db_path: Path | None = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        batch_size: int = 32,
    ):
        self.db_path = db_path or get_db_path()
        self.embedding_model = embedding_model
        self.batch_size = batch_size
        self._model = None

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            providers_raw = os.environ.get("GRUMPYCLAW_EMBEDDING_PROVIDERS", "CPUExecutionProvider").strip()
            providers = None if not providers_raw or providers_raw.lower() == "auto" else [
                p.strip() for p in providers_raw.split(",") if p.strip()
            ]
            self._model = TextEmbedding(
                model_name=self.embedding_model,
                max_length=512,
                providers=providers,
                cuda=False,
            )
        return self._model

    def delete_by_source(self, source_type: str, source_id: str) -> None:
        """Remove all chunks for a given source (e.g. before re-indexing)."""
        conn = init_db(self.db_path)
        try:
            conn.execute(
                "DELETE FROM chunks_fts WHERE chunk_id IN "
                "(SELECT id FROM chunks WHERE source_type = ? AND source_id = ?)",
                (source_type, source_id),
            )
            conn.execute(
                "DELETE FROM chunks WHERE source_type = ? AND source_id = ?",
                (source_type, source_id),
            )
            conn.commit()
        finally:
            conn.close()

    def index_documents(
        self,
        documents: list[dict],
        source_type: str = "google_docs",
    ) -> int:
        """
        Chunk each document, embed, and store. Each doc must have 'id', 'title', 'text'.
        Returns total chunks indexed.
        """
        init_db(self.db_path)
        model = self._get_model()
        total = 0
        conn = sqlite3.connect(str(self.db_path))
        try:
            for doc in documents:
                doc_id = str(doc["id"])
                title = doc.get("title", "")
                text = doc.get("text", "")
                if not text.strip():
                    continue
                conn.execute(
                    "DELETE FROM chunks_fts WHERE chunk_id IN "
                    "(SELECT id FROM chunks WHERE source_type = ? AND source_id = ?)",
                    (source_type, doc_id),
                )
                conn.execute(
                    "DELETE FROM chunks WHERE source_type = ? AND source_id = ?",
                    (source_type, doc_id),
                )
                chunks = _chunk_text(text)
                if not chunks:
                    continue
                embeddings = list(model.embed(chunks, batch_size=self.batch_size))
                cur = conn.cursor()
                for content, embedding in zip(chunks, embeddings):
                    emb_blob = json.dumps([float(x) for x in embedding])
                    cur.execute(
                        """INSERT INTO chunks (source_type, source_id, title, content, embedding)
                           VALUES (?, ?, ?, ?, ?)""",
                        (source_type, doc_id, title, content, emb_blob),
                    )
                    chunk_id = cur.lastrowid
                    cur.execute(
                        "INSERT INTO chunks_fts(chunk_id, content) VALUES (?, ?)",
                        (chunk_id, content),
                    )
                    total += 1
            conn.commit()
        finally:
            conn.close()
        return total
