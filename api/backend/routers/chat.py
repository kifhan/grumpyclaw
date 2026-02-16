from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..event_bus import sse_stream
from ..models import CreateSessionRequest, PostMessageRequest

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions")
def create_chat_session(body: CreateSessionRequest, request: Request) -> dict[str, object]:
    return request.app.state.container.chat.create_session(mode=body.mode, title=body.title)


@router.get("/sessions")
def list_chat_sessions(
    request: Request,
    mode: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, object]]:
    return request.app.state.container.chat.list_sessions(mode=mode, limit=limit, offset=offset)


@router.get("/sessions/{session_id}/messages")
def list_chat_messages(session_id: str, request: Request) -> list[dict[str, object]]:
    return request.app.state.container.chat.list_messages(session_id=session_id)


@router.post("/sessions/{session_id}/messages")
def post_chat_message(session_id: str, body: PostMessageRequest, request: Request) -> dict[str, object]:
    try:
        return request.app.state.container.chat.enqueue_user_message(session_id=session_id, content=body.content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/stream")
def chat_stream(session_id: str, request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(channel=f"chat:{session_id}", bus=request.app.state.container.events),
        media_type="text/event-stream",
    )
