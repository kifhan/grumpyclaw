from __future__ import annotations

import hashlib
import re
from typing import Any

from grumpyclaw.memory.db import get_db_path, init_db
from grumpyclaw.memory.indexer import Indexer
from grumpyclaw.memory.retriever import Retriever
from grumpyclaw.skills.registry import get_skill_content

from .image_cache import RealtimeImageCache


_ROBOT_ACTIONS = [
    "nod",
    "look_at",
    "antenna_feedback",
    "speak",
    "play_emotion",
    "stop_emotion",
    "dance",
    "stop_dance",
]


_SENSITIVE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(
        r"\b(?:api[_\s-]?key|secret|password|passwd|access[_\s-]?token|refresh[_\s-]?token)\b\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
]


class ToolDispatcher:
    """Unified tool execution for Responses and Realtime."""

    def __init__(
        self,
        *,
        robot_service: Any,
        retriever: Retriever | None = None,
        indexer: Indexer | None = None,
        image_cache: RealtimeImageCache | None = None,
    ):
        self._robot_service = robot_service
        self._retriever = retriever or Retriever()
        self._indexer = indexer or Indexer()
        self._image_cache = image_cache or RealtimeImageCache(
            cache_dir="data/realtime_image_cache",
            ttl_seconds=604800,
        )

    def purge_runtime_cache(self) -> int:
        return self._image_cache.purge_expired()

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
                "name": "save_memory",
                "description": "Save stable user facts/preferences to personal long-term memory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory": {"type": "string"},
                    },
                    "required": ["memory"],
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
                "name": "capture_camera_context",
                "description": "Capture the latest camera frame and provide image context for the next response.",
                "parameters": {"type": "object", "properties": {}},
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
                            "enum": _ROBOT_ACTIONS,
                        },
                        "name": {
                            "type": "string",
                            "description": "Optional emotion/dance name for expressive actions.",
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
        if name == "save_memory":
            return self._save_memory(arguments)
        if name == "run_skill":
            return self._run_skill(arguments)
        if name == "capture_camera_context":
            return self._capture_camera_context(arguments)
        if name == "robot_action":
            return self._robot_action(arguments)
        return {"ok": False, "error": f"Unknown tool: {name}"}

    def _search_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", "")).strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        try:
            top_k = int(arguments.get("top_k", 5) or 5)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(20, top_k))
        try:
            hits = self._retriever.hybrid_search(query=query, top_k=top_k)
            return {"ok": True, "result": hits}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _save_memory(self, arguments: dict[str, Any]) -> dict[str, Any]:
        memory = str(arguments.get("memory", "")).strip()
        if not memory:
            return {"ok": False, "error": "memory is required", "code": "memory_required"}
        normalized = self._normalize_memory(memory)
        if self._looks_sensitive(normalized):
            return {
                "ok": False,
                "error": "memory appears to contain sensitive data",
                "code": "sensitive_content_blocked",
            }

        memory_id = hashlib.sha256(normalized.lower().encode("utf-8")).hexdigest()
        source_type = "personal_memory"
        already_exists = self._memory_exists(source_type=source_type, source_id=memory_id)
        if already_exists:
            return {
                "ok": True,
                "result": {
                    "memory_id": memory_id,
                    "source_type": source_type,
                    "stored": False,
                    "deduped": True,
                    "chunks_indexed": 0,
                },
            }
        try:
            chunks = int(
                self._indexer.index_documents(
                    [
                        {
                            "id": memory_id,
                            "title": "Personal memory",
                            "text": normalized,
                        }
                    ],
                    source_type=source_type,
                )
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "result": {
                "memory_id": memory_id,
                "source_type": source_type,
                "stored": True,
                "deduped": False,
                "chunks_indexed": chunks,
            },
        }

    @staticmethod
    def _run_skill(arguments: dict[str, Any]) -> dict[str, Any]:
        skill_id = str(arguments.get("skill_id", "")).strip()
        if not skill_id:
            return {"ok": False, "error": "skill_id is required"}
        content = get_skill_content(skill_id)
        if not content:
            return {"ok": False, "error": f"skill not found: {skill_id}"}
        return {"ok": True, "result": {"skill_id": skill_id, "content": content}}

    def _capture_camera_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        worker = None
        get_camera_worker = getattr(self._robot_service, "get_camera_worker", None)
        if callable(get_camera_worker):
            worker = get_camera_worker()
        if worker is None:
            app_getter = getattr(self._robot_service, "get_app", None)
            app = app_getter() if callable(app_getter) else None
            worker = getattr(app, "_camera_worker", None) if app is not None else None
        if worker is None:
            return {"ok": False, "error": "camera not available", "code": "camera_unavailable"}
        get_latest_frame = getattr(worker, "get_latest_frame", None)
        if not callable(get_latest_frame):
            return {"ok": False, "error": "camera worker unavailable", "code": "camera_worker_unavailable"}
        frame = get_latest_frame()
        if frame is None:
            return {"ok": False, "error": "no camera frame captured yet", "code": "camera_frame_unavailable"}
        if not isinstance(frame, (bytes, bytearray)):
            return {"ok": False, "error": "unsupported camera frame type", "code": "unsupported_frame_type"}
        image_bytes = bytes(frame)
        if not image_bytes:
            return {"ok": False, "error": "camera frame is empty", "code": "camera_frame_empty"}
        try:
            cached = self._image_cache.store_jpeg(image_bytes)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "code": "camera_cache_failed"}
        return {
            "ok": True,
            "result": {
                "cache_file": str(cached.path),
                "byte_size": cached.byte_size,
                "mime_type": cached.mime_type,
                "created_at": cached.created_at,
                "expires_at": cached.expires_at,
                # Internal field consumed by realtime service and stripped from logs/DB.
                "image_data_url": self._image_cache.to_data_url(image_bytes, mime_type=cached.mime_type),
            },
        }

    def _robot_action(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            action = str(arguments.get("action", "")).strip()
            if not action:
                return {
                    "ok": False,
                    "error": "action is required",
                    "code": "action_required",
                }
            if action not in _ROBOT_ACTIONS:
                return {
                    "ok": False,
                    "error": f"unsupported action: {action}",
                    "code": "unsupported_action",
                    "allowed_actions": list(_ROBOT_ACTIONS),
                }
            payload = {
                "action": action,
                "name": arguments.get("name"),
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

    @staticmethod
    def _normalize_memory(memory: str) -> str:
        return " ".join(memory.split()).strip()

    @staticmethod
    def _looks_sensitive(memory: str) -> bool:
        for pattern in _SENSITIVE_PATTERNS:
            if pattern.search(memory):
                return True
        return False

    def _memory_exists(self, *, source_type: str, source_id: str) -> bool:
        db_path = getattr(self._indexer, "db_path", None) or get_db_path()
        conn = init_db(db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM chunks WHERE source_type = ? AND source_id = ? LIMIT 1",
                (source_type, source_id),
            ).fetchone()
            return bool(row)
        finally:
            conn.close()
