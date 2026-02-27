from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from grumpyclaw.memory.retriever import Retriever
from grumpyclaw.skills.registry import list_skills
from grumpyreachy.heartbeat_bridge import HeartbeatBridge

from ..db import dump_json, get_conn, load_json
from ..event_bus import EventBus, StreamEvent
from .heartbeat_scheduler import HeartbeatScheduler
from .realtime_service import OpenAIRealtimeService
from .text_gateway import OpenAITextGateway
from .tools import ToolDispatcher

LOG = logging.getLogger("grumpyadmin.assistant")


def _system_prompt() -> str:
    parts = [
        "You are a helpful personal AI assistant.",
        "Use memory and local skills when relevant.",
    ]
    try:
        skills = list_skills()
        if skills:
            parts.append("Available skills:")
            for skill in skills:
                parts.append(f"- {skill['name']}: {skill['id']}")
    except Exception:
        pass
    return "\n".join(parts)


class AssistantManager:
    """Centralized orchestration for text chat, realtime and heartbeat."""

    def __init__(self, *, event_bus: EventBus, config: Any, robot_service: Any):
        self._event_bus = event_bus
        self._config = config
        self._robot_service = robot_service

        self._retriever = Retriever()
        self._heartbeat_bridge = HeartbeatBridge()
        self._tools = ToolDispatcher(robot_service=robot_service)

        self._text_gateway = OpenAITextGateway(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            model=config.openai_text_model,
            tools=self._tools,
        )
        self._realtime_service = OpenAIRealtimeService(
            api_key=config.openai_api_key,
            base_url=config.openai_base_url,
            model=config.openai_realtime_model,
            input_gain=config.realtime_input_gain,
            output_gain=config.realtime_output_gain,
            tools=self._tools,
            on_event=self._on_realtime_event,
            get_robot_mini=self._get_robot_mini,
        )
        self._heartbeat_scheduler = HeartbeatScheduler(
            interval_seconds=config.heartbeat_interval_seconds,
            run_once=self._run_heartbeat_once,
        )

    def start(self) -> None:
        self._heartbeat_scheduler.start()

    def shutdown(self) -> None:
        self._heartbeat_scheduler.stop()
        self._realtime_service.stop()

    def runtime_status(self) -> dict[str, Any]:
        return {
            "heartbeat": self.heartbeat_status(),
            "realtime": self.realtime_status(),
            "robot": self._robot_service.status(),
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    def create_session(self, mode: str, title: str | None = None) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO app_chat_sessions(id, mode, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, mode, title or f"{mode} session", ts, ts),
            )
            conn.commit()
        finally:
            conn.close()
        return {"session_id": session_id, "mode": mode, "created_at": ts}

    def list_sessions(self, mode: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        conn = get_conn()
        try:
            if mode:
                rows = conn.execute(
                    """
                    SELECT id, mode, title, created_at, updated_at
                    FROM app_chat_sessions
                    WHERE mode = ?
                    ORDER BY datetime(updated_at) DESC
                    LIMIT ? OFFSET ?
                    """,
                    (mode, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, mode, title, created_at, updated_at
                    FROM app_chat_sessions
                    ORDER BY datetime(updated_at) DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        conn = get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, session_id, role, content, status, created_at, meta_json
                FROM app_chat_messages
                WHERE session_id = ?
                ORDER BY datetime(created_at) ASC, id ASC
                """,
                (session_id,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "role": row["role"],
                    "content": row["content"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "meta": load_json(row["meta_json"]),
                }
                for row in rows
            ]
        finally:
            conn.close()

    def enqueue_user_message(self, session_id: str, content: str) -> dict[str, Any]:
        user_id = str(uuid.uuid4())
        assistant_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc).isoformat()

        conn = get_conn()
        try:
            session = conn.execute("SELECT mode FROM app_chat_sessions WHERE id = ?", (session_id,)).fetchone()
            if not session:
                raise ValueError("session not found")
            conn.execute(
                """
                INSERT INTO app_chat_messages(id, session_id, role, content, status, created_at, meta_json)
                VALUES (?, ?, 'user', ?, 'final', ?, ?)
                """,
                (user_id, session_id, content, ts, dump_json({})),
            )
            conn.execute(
                """
                INSERT INTO app_chat_messages(id, session_id, role, content, status, created_at, meta_json)
                VALUES (?, ?, 'assistant', '', 'processing', ?, ?)
                """,
                (assistant_id, session_id, ts, dump_json({"streaming": True})),
            )
            conn.execute("UPDATE app_chat_sessions SET updated_at = ? WHERE id = ?", (ts, session_id))
            conn.commit()
        finally:
            conn.close()

        threading.Thread(
            target=self._process_assistant_reply,
            args=(session_id, assistant_id, content),
            daemon=True,
        ).start()

        return {"message_id": assistant_id, "queued": True}

    def _process_assistant_reply(self, session_id: str, assistant_id: str, user_text: str) -> None:
        channel = f"assistant:{session_id}"
        token_buffer: list[str] = []
        try:
            history = self.list_messages(session_id)
            messages: list[dict[str, Any]] = []
            for item in history:
                role = str(item.get("role", ""))
                content = str(item.get("content", ""))
                if role in {"user", "assistant"} and content:
                    messages.append({"role": role, "content": content})

            # Retrieval augmentation.
            try:
                hits = self._retriever.hybrid_search(user_text, top_k=5)
                if hits:
                    context = "\n".join(f"[{h['title']}] {h['content'][:240]}" for h in hits)
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Relevant context from memory:\n{context}\n\nUser: {user_text}",
                        }
                    )
            except Exception:
                pass

            for evt in self._text_gateway.stream_reply(instructions=_system_prompt(), messages=messages):
                if evt["type"] == "token":
                    token = str(evt.get("delta", ""))
                    if token:
                        token_buffer.append(token)
                        self._event_bus.publish(
                            channel,
                            StreamEvent(
                                event="assistant.token",
                                data={"session_id": session_id, "message_id": assistant_id, "token": token},
                            ),
                        )
                    continue

                if evt["type"] == "tool":
                    self._event_bus.publish(
                        channel,
                        StreamEvent(
                            event="assistant.tool",
                            data={
                                "session_id": session_id,
                                "message_id": assistant_id,
                                "tool": evt.get("name"),
                                "arguments": evt.get("arguments"),
                                "result": evt.get("result"),
                            },
                        ),
                    )
                    continue

                if evt["type"] == "final":
                    final = str(evt.get("text", "") or "").strip()
                    if not final:
                        final = "".join(token_buffer).strip()
                    self._set_assistant_final(assistant_id, final)
                    self._event_bus.publish(
                        channel,
                        StreamEvent(
                            event="assistant.final",
                            data={"session_id": session_id, "message_id": assistant_id, "content": final},
                        ),
                    )
                    return

            final = "".join(token_buffer)
            self._set_assistant_final(assistant_id, final)
            self._event_bus.publish(
                channel,
                StreamEvent(
                    event="assistant.final",
                    data={"session_id": session_id, "message_id": assistant_id, "content": final},
                ),
            )
        except Exception as exc:
            LOG.exception("assistant reply failed")
            self._set_assistant_final(assistant_id, f"Error: {exc}", status="error")
            self._event_bus.publish(
                channel,
                StreamEvent(
                    event="assistant.error",
                    data={"session_id": session_id, "message_id": assistant_id, "error": str(exc)},
                ),
            )

    def _set_assistant_final(self, message_id: str, content: str, status: str = "final") -> None:
        conn = get_conn()
        try:
            conn.execute(
                "UPDATE app_chat_messages SET content = ?, status = ?, meta_json = ? WHERE id = ?",
                (content, status, dump_json({"streaming": False}), message_id),
            )
            conn.commit()
        finally:
            conn.close()

    def realtime_start(self) -> dict[str, Any]:
        return self._realtime_service.start()

    def realtime_stop(self) -> dict[str, Any]:
        return self._realtime_service.stop()

    def realtime_status(self) -> dict[str, Any]:
        return self._realtime_service.status()

    def realtime_history(self, limit: int = 200) -> list[dict[str, Any]]:
        conn = get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, event_type, payload_json, created_at
                FROM app_realtime_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            items = [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "payload": load_json(row["payload_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
            items.reverse()
            return items
        finally:
            conn.close()

    def heartbeat_start(self) -> dict[str, Any]:
        self._heartbeat_scheduler.start()
        return self.heartbeat_status()

    def heartbeat_stop(self) -> dict[str, Any]:
        self._heartbeat_scheduler.stop()
        return self.heartbeat_status()

    def heartbeat_run_now(self) -> dict[str, Any]:
        return self._heartbeat_scheduler.run_now()

    def heartbeat_status(self) -> dict[str, Any]:
        return self._heartbeat_scheduler.status()

    def _run_heartbeat_once(self, trigger: str) -> dict[str, Any]:
        result = self._heartbeat_bridge.evaluate()
        payload = {
            "status": result.status,
            "message": result.message,
            "context": result.context,
            "trigger": trigger,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO app_heartbeat_runs(status, message, context_json, trigger, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload["status"],
                    payload["message"],
                    dump_json(payload["context"]),
                    payload["trigger"],
                    payload["ts"],
                ),
            )
            conn.execute(
                """
                INSERT INTO app_process_events(process_name, source, level, event_type, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "heartbeat",
                    "runtime",
                    "INFO" if payload["status"] == "HEARTBEAT_OK" else "WARNING",
                    "runtime.heartbeat",
                    dump_json(payload),
                ),
            )
            # Keep compatibility with existing heartbeat history endpoint.
            conn.execute(
                "INSERT INTO app_heartbeat_history(status, message, context_json) VALUES (?, ?, ?)",
                (payload["status"], payload["message"], dump_json(payload["context"])),
            )
            conn.commit()
        finally:
            conn.close()

        self._event_bus.publish("runtime", StreamEvent(event="runtime.heartbeat", data=payload))
        return payload

    def _on_realtime_event(self, event_type: str, payload: dict[str, Any]) -> None:
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO app_realtime_events(event_type, payload_json) VALUES (?, ?)",
                (event_type, dump_json(payload)),
            )
            conn.commit()
        finally:
            conn.close()

        self._event_bus.publish("assistant-realtime", StreamEvent(event=event_type, data=payload))

    def _get_robot_mini(self) -> Any | None:
        app = self._robot_service.get_app()
        if not app:
            return None
        controller = getattr(app, "_controller", None)
        if not controller:
            return None
        return getattr(controller, "_mini", None)
