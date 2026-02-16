"""Slack bot (Socket Mode): reply in channel/thread using LLM + memory retrieval and skills."""

from __future__ import annotations

import os
import sys
import time


def _build_system_prompt() -> str:
    parts = [
        "You are a helpful personal AI assistant in Slack. Use the provided context (memory, skills) when relevant. Be concise.",
    ]
    try:
        from grumpyclaw.skills.registry import list_skills
        skills = list_skills()
        if skills:
            parts.append("\n\nAvailable skills (use when relevant):\n")
            for s in skills:
                parts.append(f"\n--- {s['name']} ---\n{s['content']}\n")
    except Exception:
        pass
    return "\n".join(parts).strip()


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    bot_token = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    app_token = os.environ.get("SLACK_APP_TOKEN", "").strip()
    if not bot_token or not app_token:
        print("Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN.", file=sys.stderr)
        return 1

    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk.web import WebClient

    from grumpyclaw.llm.client import chat
    from grumpyclaw.memory.retriever import Retriever

    web = WebClient(token=bot_token)
    client = SocketModeClient(app_token=app_token, web_client=web)
    retriever = Retriever()
    system_prompt = _build_system_prompt()

    def on_request(sock_client: SocketModeClient, req: SocketModeRequest) -> None:
        resp = SocketModeResponse(envelope_id=req.envelope_id)
        sock_client.send_socket_mode_response(resp)
        if req.type != "events_api":
            return
        payload = req.payload or {}
        event = (payload.get("event") or {}).copy()
        if event.get("type") != "message" or event.get("subtype"):
            return
        # Skip bot messages and message_changed
        if event.get("bot_id"):
            return
        text = (event.get("text") or "").strip()
        if not text:
            return
        channel = event.get("channel")
        ts = event.get("ts")
        thread_ts = event.get("thread_ts")
        if not channel or not ts:
            return
        reply_ts = thread_ts or ts

        # Optional: retrieve context
        try:
            hits = retriever.hybrid_search(text, top_k=5)
            if hits:
                context = "\n".join(
                    f"[{h['title']}] {h['content'][:300]}..."
                    if len(h.get("content", "")) > 300
                    else f"[{h['title']}] {h['content']}"
                    for h in hits
                )
                user_msg = f"Relevant context from memory:\n{context}\n\nUser: {text}"
            else:
                user_msg = text
        except Exception:
            user_msg = text

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]
        try:
            reply = chat(messages)
        except Exception as e:
            reply = f"Error: {e}"
        kwargs = {"channel": channel, "text": reply}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts
        try:
            web.chat_postMessage(**kwargs)
        except Exception as e:
            print("Slack post error:", e, file=sys.stderr)

    client.socket_mode_request_listeners.append(on_request)
    print("Slack bot (Socket Mode) running. Ctrl+C to stop.")
    client.connect()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
