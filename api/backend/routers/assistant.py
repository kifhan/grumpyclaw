from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..event_bus import sse_stream

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/sessions")
def create_session(request: Request, body: dict[str, object] | None = None) -> dict[str, object]:
    payload = body or {}
    mode = str(payload.get("mode", "assistant") or "assistant")
    title = str(payload.get("title", "") or "").strip() or None
    return request.app.state.container.assistant.create_session(mode=mode, title=title)


@router.get("/sessions")
def list_sessions(
    request: Request,
    mode: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, object]]:
    return request.app.state.container.assistant.list_sessions(mode=mode, limit=limit, offset=offset)


@router.get("/sessions/{session_id}/messages")
def list_messages(session_id: str, request: Request) -> list[dict[str, object]]:
    return request.app.state.container.assistant.list_messages(session_id=session_id)


@router.post("/sessions/{session_id}/messages")
def post_message(session_id: str, request: Request, body: dict[str, object]) -> dict[str, object]:
    content = str(body.get("content", "") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content required")
    try:
        return request.app.state.container.assistant.enqueue_user_message(session_id=session_id, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/stream")
def stream_session(session_id: str, request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(channel=f"assistant:{session_id}", bus=request.app.state.container.events),
        media_type="text/event-stream",
    )


@router.post("/realtime/start")
def realtime_start(request: Request) -> dict[str, object]:
    try:
        status = request.app.state.container.assistant.realtime_start()
        return {"ok": True, "status": status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/realtime/stop")
def realtime_stop(request: Request) -> dict[str, object]:
    status = request.app.state.container.assistant.realtime_stop()
    return {"ok": True, "status": status}


@router.get("/realtime/status")
def realtime_status(request: Request) -> dict[str, object]:
    return request.app.state.container.assistant.realtime_status()


@router.get("/realtime/history")
def realtime_history(
    request: Request,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, object]]:
    return request.app.state.container.assistant.realtime_history(limit=limit)


@router.get("/realtime/stream")
def realtime_stream(request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(channel="assistant-realtime", bus=request.app.state.container.events),
        media_type="text/event-stream",
    )
