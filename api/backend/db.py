from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from grumpyclaw.memory.db import get_db_path, init_db


def get_app_db_path() -> Path:
    return get_db_path()


def init_app_db() -> None:
    conn = init_db(get_app_db_path())
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_chat_sessions (
                id TEXT PRIMARY KEY,
                mode TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                meta_json TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES app_chat_sessions(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_process_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                process_name TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'runtime',
                level TEXT NOT NULL DEFAULT 'INFO',
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_heartbeat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                context_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_robot_actions (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'robot',
                level TEXT NOT NULL DEFAULT 'INFO',
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                accepted INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_realtime_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_heartbeat_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                context_json TEXT NOT NULL,
                trigger TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_column(conn, "app_process_events", "source", "TEXT NOT NULL DEFAULT 'runtime'")
        _ensure_column(conn, "app_process_events", "level", "TEXT NOT NULL DEFAULT 'INFO'")
        _ensure_column(conn, "app_robot_actions", "source", "TEXT NOT NULL DEFAULT 'robot'")
        _ensure_column(conn, "app_robot_actions", "level", "TEXT NOT NULL DEFAULT 'INFO'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_chat_messages_session ON app_chat_messages(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_chat_messages_created ON app_chat_messages(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_process_events_name ON app_process_events(process_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_process_events_source ON app_process_events(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_process_events_level ON app_process_events(level)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_process_events_type ON app_process_events(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_process_events_created ON app_process_events(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_robot_actions_source ON app_robot_actions(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_robot_actions_level ON app_robot_actions(level)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_realtime_events_type ON app_realtime_events(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_realtime_events_created ON app_realtime_events(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_app_heartbeat_runs_created ON app_heartbeat_runs(created_at)")
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_def: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols = {row[1] for row in rows}
    if column in cols:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_app_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=True)


def load_json(raw: str) -> Any:
    return json.loads(raw)
