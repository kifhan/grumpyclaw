from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from grumpyclaw.llm.client import chat as llm_chat
from grumpyclaw.memory.retriever import Retriever
from grumpyclaw.skills.registry import list_skills
from grumpyreachy.tool_adapter import GrumpyClawToolAdapter

from .db import dump_json, get_conn, load_json
from .event_bus import EventBus, StreamEvent
from .robot_service import ApiFeedbackBridge


def _system_prompt() -> str:
    parts = [
        "You are a helpful personal AI assistant. Use memory and skill context when relevant.",
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


class ChatService:
    def __init__(self, event_bus: EventBus, feedback_bridge: ApiFeedbackBridge):
        self._event_bus = event_bus
        self._retriever = Retriever()
        self._adapter = GrumpyClawToolAdapter(feedback=feedback_bridge)
        self._system = _system_prompt()

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
            mode = str(session["mode"])
        finally:
            conn.close()

        threading.Thread(
            target=self._process_assistant_reply,
            args=(session_id, assistant_id, content, mode),
            daemon=True,
        ).start()
        return {"message_id": assistant_id, "queued": True}

    def _process_assistant_reply(self, session_id: str, assistant_id: str, user_text: str, mode: str) -> None:
        try:
            if mode == "grumpyreachy":
                self._reply_grumpyreachy(session_id, assistant_id, user_text)
            else:
                self._reply_grumpyclaw(session_id, assistant_id, user_text)
        except Exception as exc:
            self._event_bus.publish(
                f"chat:{session_id}",
                StreamEvent(event="chat.error", data={"session_id": session_id, "error": str(exc)}),
            )
            self._set_assistant_final(assistant_id, f"Error: {exc}", status="error")

    def _reply_grumpyreachy(self, session_id: str, assistant_id: str, user_text: str) -> None:
        out = self._adapter.ask(prompt=user_text)
        if not out.get("ok"):
            raise RuntimeError(str(out.get("error", "unknown error")))
        final = str(out.get("result", ""))
        self._set_assistant_final(assistant_id, final)
        self._event_bus.publish(
            f"chat:{session_id}",
            StreamEvent(event="chat.final", data={"session_id": session_id, "message_id": assistant_id, "content": final}),
        )

    def _reply_grumpyclaw(self, session_id: str, assistant_id: str, user_text: str) -> None:
        history = self.list_messages(session_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": self._system}]
        for item in history:
            if item["role"] in {"user", "assistant"} and item["content"]:
                messages.append({"role": item["role"], "content": item["content"]})

        try:
            hits = self._retriever.hybrid_search(user_text, top_k=5)
            if hits:
                context = "\n".join(f"[{h['title']}] {h['content'][:240]}" for h in hits)
                messages.append({
                    "role": "user",
                    "content": f"Relevant context from memory:\n{context}\n\nUser: {user_text}",
                })
            else:
                messages.append({"role": "user", "content": user_text})
        except Exception:
            messages.append({"role": "user", "content": user_text})

        chunks = llm_chat(messages, stream=True)
        if not hasattr(chunks, "__iter__"):
            final = str(chunks)
            self._set_assistant_final(assistant_id, final)
            self._event_bus.publish(
                f"chat:{session_id}",
                StreamEvent(event="chat.final", data={"session_id": session_id, "message_id": assistant_id, "content": final}),
            )
            return

        buffer: list[str] = []
        for token in chunks:  # type: ignore[union-attr]
            tok = str(token)
            if not tok:
                continue
            buffer.append(tok)
            self._event_bus.publish(
                f"chat:{session_id}",
                StreamEvent(
                    event="chat.token",
                    data={"session_id": session_id, "message_id": assistant_id, "token": tok},
                ),
            )
        final = "".join(buffer)
        self._set_assistant_final(assistant_id, final)
        self._event_bus.publish(
            f"chat:{session_id}",
            StreamEvent(event="chat.final", data={"session_id": session_id, "message_id": assistant_id, "content": final}),
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
