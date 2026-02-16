from __future__ import annotations

from pathlib import Path

from api.backend.db import get_conn, init_app_db


def test_init_app_db_creates_tables(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "schema.db"
    monkeypatch.setenv("GRUMPYCLAW_DB_PATH", str(db_path))
    init_app_db()

    conn = get_conn()
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {row["name"] for row in rows}
        assert "app_chat_sessions" in names
        assert "app_chat_messages" in names
        assert "app_process_events" in names
        assert "app_heartbeat_history" in names
        assert "app_robot_actions" in names

        proc_cols = {row["name"] for row in conn.execute("PRAGMA table_info(app_process_events)").fetchall()}
        assert "source" in proc_cols
        assert "level" in proc_cols

        robot_cols = {row["name"] for row in conn.execute("PRAGMA table_info(app_robot_actions)").fetchall()}
        assert "source" in robot_cols
        assert "level" in robot_cols
    finally:
        conn.close()
