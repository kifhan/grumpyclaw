"""Heartbeat bridge that injects robot observation context."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any

from grumpyclaw.llm.client import chat
from grumpyclaw.memory.db import get_db_path, init_db
from grumpyreachy.memory_bridge import MemoryBridge


@dataclass(frozen=True)
class HeartbeatResult:
    status: str
    message: str
    context: dict[str, Any]


class HeartbeatBridge:
    """Builds heartbeat context and returns deterministic status payload."""

    def __init__(self, observation_limit: int = 5):
        self.observation_limit = max(1, int(observation_limit))

    def build_context(
        self,
        pending_tasks: list[str] | None = None,
        recent_intents: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "latest_observations": self._load_latest_observations(),
            "pending_tasks": pending_tasks or [],
            "recent_user_intents": recent_intents or [],
        }

    def evaluate(
        self,
        pending_tasks: list[str] | None = None,
        recent_intents: list[str] | None = None,
    ) -> HeartbeatResult:
        context = self.build_context(pending_tasks=pending_tasks, recent_intents=recent_intents)
        system = (
            "Decide heartbeat status from context. Reply ONLY valid JSON with keys: "
            "status and message. status must be HEARTBEAT_OK or NOTIFY. "
            "Use HEARTBEAT_OK when no proactive user-facing notification is needed."
        )
        user = json.dumps(context, ensure_ascii=True)
        try:
            raw = chat([{"role": "system", "content": system}, {"role": "user", "content": user}]).strip()
        except Exception:
            return HeartbeatResult(status="HEARTBEAT_OK", message="", context=context)
        return self._parse_model_result(raw=raw, context=context)

    def _load_latest_observations(self) -> list[dict[str, str]]:
        db_path = get_db_path()
        init_db(db_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT source_id, title, content, updated_at
                FROM chunks
                WHERE source_type = ?
                ORDER BY datetime(updated_at) DESC, id DESC
                LIMIT ?
                """,
                (MemoryBridge.SOURCE_TYPE, self.observation_limit),
            ).fetchall()
            return [
                {
                    "source_id": str(r["source_id"]),
                    "title": str(r["title"]),
                    "summary": str(r["content"]),
                    "updated_at": str(r["updated_at"]),
                }
                for r in rows
            ]
        finally:
            conn.close()

    def _parse_model_result(self, raw: str, context: dict[str, Any]) -> HeartbeatResult:
        # Accept both strict JSON and legacy plain response.
        try:
            parsed = json.loads(raw)
            status = str(parsed.get("status", "HEARTBEAT_OK")).strip().upper()
            message = str(parsed.get("message", "")).strip()
        except json.JSONDecodeError:
            status = "HEARTBEAT_OK" if raw.upper() == "HEARTBEAT_OK" else "NOTIFY"
            message = "" if status == "HEARTBEAT_OK" else raw
        if status not in {"HEARTBEAT_OK", "NOTIFY"}:
            status = "HEARTBEAT_OK"
            message = ""
        if status == "HEARTBEAT_OK":
            message = ""
        return HeartbeatResult(status=status, message=message, context=context)


def heartbeat_result_to_json(result: HeartbeatResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=True)
