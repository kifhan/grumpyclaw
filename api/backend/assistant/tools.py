from __future__ import annotations

from typing import Any

from grumpyclaw.memory.retriever import Retriever
from grumpyclaw.skills.registry import get_skill_content


class ToolDispatcher:
    """Unified tool execution for Responses and Realtime."""

    def __init__(self, robot_service: Any):
        self._robot_service = robot_service
        self._retriever = Retriever()

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "search_memory",
                "description": "Search memory chunks by semantic + keyword hybrid search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "run_skill",
                "description": "Load local SKILL.md content by skill id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string"},
                    },
                    "required": ["skill_id"],
                },
            },
            {
                "type": "function",
                "name": "robot_action",
                "description": "Queue a robot action in the in-process robot runtime.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["nod", "look_at", "antenna_feedback", "speak"],
                        },
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "z": {"type": "number"},
                        "duration": {"type": "number"},
                        "state": {
                            "type": "string",
                            "enum": ["attention", "success", "error", "neutral"],
                        },
                        "text": {"type": "string"},
                        "confirm": {"type": "boolean"},
                    },
                    "required": ["action"],
                },
            },
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "search_memory":
            return self._search_memory(arguments)
        if name == "run_skill":
            return self._run_skill(arguments)
        if name == "robot_action":
            return self._robot_action(arguments)
        return {"ok": False, "error": f"Unknown tool: {name}"}

    def _search_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        top_k = int(arguments.get("top_k", 5) or 5)
        top_k = max(1, min(20, top_k))
        try:
            hits = self._retriever.hybrid_search(query=query, top_k=top_k)
            return {"ok": True, "result": hits}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _run_skill(arguments: dict[str, Any]) -> dict[str, Any]:
        skill_id = str(arguments.get("skill_id", "")).strip()
        if not skill_id:
            return {"ok": False, "error": "skill_id is required"}
        content = get_skill_content(skill_id)
        if not content:
            return {"ok": False, "error": f"skill not found: {skill_id}"}
        return {"ok": True, "result": {"skill_id": skill_id, "content": content}}

    def _robot_action(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = {
                "action": str(arguments.get("action", "")).strip(),
                "x": arguments.get("x"),
                "y": arguments.get("y"),
                "z": arguments.get("z"),
                "duration": arguments.get("duration"),
                "state": arguments.get("state"),
                "text": arguments.get("text"),
                "confirm": bool(arguments.get("confirm", False)),
            }
            result = self._robot_service.enqueue_action(payload=payload)
            return {
                "ok": True,
                "result": {
                    "accepted": result.accepted,
                    "action_id": result.action_id,
                    "reason": result.reason,
                },
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
