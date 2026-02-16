"""Hybrid search: 0.7 vector (cosine) + 0.3 keyword (FTS5 BM25)."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path

from grumpyclaw.memory.db import get_db_path, init_db


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _normalize_scores(scores: list[float], invert: bool = False) -> list[float]:
    """Min-max normalize to [0, 1]. If invert=True, higher raw = lower norm (for BM25)."""
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [0.5] * len(scores)
    out = [(s - lo) / (hi - lo) for s in scores]
    if invert:
        out = [1.0 - x for x in out]
    return out


def _fts5_escape(term: str) -> str:
    """Escape a term for FTS5 MATCH (quote and escape internal quotes)."""
    term = term.strip()
    if not term:
        return '""'
    # FTS5: double-quote the term, escape " as ""
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


def _query_to_fts5_phrase(query: str) -> str:
    """Turn a short query into FTS5 MATCH expression (phrase or AND of tokens)."""
    # Simple: tokenize on non-alnum, quote each token, join with space (AND in FTS5)
    tokens = re.findall(r"[^\s]+", query)
    if not tokens:
        return '""'
    return " ".join(_fts5_escape(t) for t in tokens[:20])  # limit tokens


class Retriever:
    """Hybrid retrieval: vector (FastEmbed) + keyword (FTS5 BM25)."""

    VECTOR_WEIGHT = 0.7
    BM25_WEIGHT = 0.3

    def __init__(
        self,
        db_path: Path | None = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        self.db_path = db_path or get_db_path()
        self.embedding_model = embedding_model
        self._model = None

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.embedding_model, max_length=512)
        return self._model

    def hybrid_search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[dict]:
        """
        Return top_k chunks by combined score: 0.7 * norm_cosine + 0.3 * norm_bm25.
        Each result: {content, title, source_id, source_type, score}.
        """
        init_db(self.db_path)
        query = query.strip()
        if not query:
            return []

        model = self._get_model()
        (query_emb,) = list(model.embed([query]))

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            # 1) FTS5: get chunk_id and bm25 (lower = better in FTS5)
            fts_expr = _query_to_fts5_phrase(query)
            try:
                fts_rows = conn.execute(
                    """
                    SELECT chunk_id, bm25(chunks_fts) AS bm25_score
                    FROM chunks_fts
                    WHERE chunks_fts MATCH ?
                    ORDER BY bm25_score
                    LIMIT 200
                    """,
                    (fts_expr,),
                ).fetchall()
            except sqlite3.OperationalError:
                # MATCH syntax error or no FTS match
                fts_rows = []

            if fts_rows:
                chunk_ids = [r["chunk_id"] for r in fts_rows]
                bm25_by_id = {r["chunk_id"]: r["bm25_score"] for r in fts_rows}
                placeholders = ",".join("?" * len(chunk_ids))
                rows = conn.execute(
                    f"""
                    SELECT id, source_type, source_id, title, content, embedding
                    FROM chunks
                    WHERE id IN ({placeholders})
                    """,
                    chunk_ids,
                ).fetchall()
            else:
                # Fallback: vector-only over all chunks (limit for perf)
                rows = conn.execute(
                    """
                    SELECT id, source_type, source_id, title, content, embedding
                    FROM chunks
                    ORDER BY id
                    LIMIT 500
                    """
                ).fetchall()
                bm25_by_id = {}

            if not rows:
                return []

            # 2) Cosine similarity for candidate chunks
            id_to_row = {r["id"]: r for r in rows}
            cos_scores = []
            for r in rows:
                emb = json.loads(r["embedding"])
                cos_scores.append(_cosine_sim(emb, query_emb))

            norm_cos = _normalize_scores(cos_scores)
            bm25_scores = [bm25_by_id.get(r["id"], 0.0) for r in rows]
            # BM25: more negative = better; normalize so higher norm = better
            norm_bm25 = _normalize_scores(bm25_scores, invert=True) if bm25_by_id else [0.5] * len(rows)

            # 3) Combine and sort
            combined = [
                (
                    self.VECTOR_WEIGHT * nc + self.BM25_WEIGHT * nb,
                    id_to_row[r["id"]],
                )
                for r, nc, nb in zip(rows, norm_cos, norm_bm25)
            ]
            combined.sort(key=lambda x: -x[0])

            return [
                {
                    "content": r["content"],
                    "title": r["title"],
                    "source_id": r["source_id"],
                    "source_type": r["source_type"],
                    "score": score,
                }
                for score, r in combined[:top_k]
            ]
        finally:
            conn.close()
