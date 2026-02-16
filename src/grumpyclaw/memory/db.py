"""SQLite schema and path for the knowledge base."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def get_db_path() -> Path:
    path = os.environ.get("GRUMPYCLAW_DB_PATH", "")
    if path:
        return Path(path)
    # Default: project root / data / grumpyclaw.db
    root = Path(__file__).resolve().parents[3]
    return root / "data" / "grumpyclaw.db"


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding BLOB NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_source
        ON chunks (source_type, source_id)
    """)
    # FTS5 for BM25 keyword search; chunk_id links to chunks.id
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            chunk_id UNINDEXED,
            content
        )
    """)
    conn.commit()
    return conn
