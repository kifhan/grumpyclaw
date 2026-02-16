from __future__ import annotations

from typing import Any

from grumpyclaw.memory.retriever import Retriever
from grumpyclaw.skills.registry import get_skill_content, list_skills
from grumpyreachy.heartbeat_bridge import HeartbeatBridge

from .db import dump_json, get_conn, load_json


class AdminDataService:
    def __init__(self) -> None:
        self._retriever = Retriever()
        self._heartbeat = HeartbeatBridge()

    def search_memory(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        return self._retriever.hybrid_search(query=query, top_k=top_k)

    def skills(self) -> list[dict[str, Any]]:
        rows = list_skills()
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "path": str(item["path"]),
                "preview": item["content"][:220],
            }
            for item in rows
        ]

    def run_skill(self, skill_id: str) -> dict[str, Any]:
        content = get_skill_content(skill_id)
        if not content:
            raise ValueError(f"skill not found: {skill_id}")
        return {"skill_id": skill_id, "content": content}

    def evaluate_heartbeat(self) -> dict[str, Any]:
        result = self._heartbeat.evaluate()
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO app_heartbeat_history(status, message, context_json) VALUES (?, ?, ?)",
                (result.status, result.message, dump_json(result.context)),
            )
            conn.commit()
        finally:
            conn.close()
        return {
            "status": result.status,
            "message": result.message,
            "context": result.context,
        }

    def heartbeat_history(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = get_conn()
        try:
            rows = conn.execute(
                "SELECT id, status, message, context_json, created_at FROM app_heartbeat_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "status": row["status"],
                    "message": row["message"],
                    "context": load_json(row["context_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def logs(
        self,
        source: str | None = None,
        level: str | None = None,
        process_name: str | None = None,
        event_type: str | None = None,
        q: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        normalized_level = level.strip().upper() if level else None
        query_text = q.strip() if q else None
        conn = get_conn()
        try:
            entries: list[dict[str, Any]] = []
            if source in {None, "runtime"}:
                clauses = []
                params: list[Any] = []
                if normalized_level:
                    clauses.append("level = ?")
                    params.append(normalized_level)
                if process_name:
                    clauses.append("process_name = ?")
                    params.append(process_name)
                if event_type:
                    clauses.append("event_type = ?")
                    params.append(event_type)
                if query_text:
                    clauses.append("payload_json LIKE ?")
                    params.append(f"%{query_text}%")
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                rows = conn.execute(
                    f"""
                    SELECT process_name, source, level, event_type, payload_json, created_at
                    FROM app_process_events
                    {where}
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (*params, limit),
                ).fetchall()
                entries.extend(
                    {
                        "source": row["source"],
                        "name": row["process_name"],
                        "level": row["level"],
                        "event_type": row["event_type"],
                        "payload": load_json(row["payload_json"]),
                        "created_at": row["created_at"],
                    }
                    for row in rows
                )

            if source in {None, "robot"}:
                clauses = []
                params = []
                if normalized_level:
                    clauses.append("level = ?")
                    params.append(normalized_level)
                if event_type and event_type != "robot.action":
                    clauses.append("1 = 0")
                if query_text:
                    clauses.append("(reason LIKE ? OR payload_json LIKE ?)")
                    params.extend([f"%{query_text}%", f"%{query_text}%"])
                where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
                rows = conn.execute(
                    f"""
                    SELECT id, source, level, action, payload_json, accepted, reason, created_at
                    FROM app_robot_actions
                    {where}
                    ORDER BY datetime(created_at) DESC
                    LIMIT ?
                    """,
                    (*params, limit),
                ).fetchall()
                entries.extend(
                    {
                        "source": row["source"],
                        "name": row["action"],
                        "level": row["level"],
                        "event_type": "robot.action",
                        "payload": load_json(row["payload_json"]),
                        "accepted": bool(row["accepted"]),
                        "reason": row["reason"],
                        "created_at": row["created_at"],
                    }
                    for row in rows
                )

            entries.sort(key=lambda x: x["created_at"], reverse=True)
            return entries[:limit]
        finally:
            conn.close()
