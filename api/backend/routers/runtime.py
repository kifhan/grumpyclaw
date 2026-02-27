from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..event_bus import sse_stream

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/status")
def runtime_status(request: Request) -> dict[str, object]:
    return request.app.state.container.assistant.runtime_status()


@router.post("/heartbeat/start")
def runtime_heartbeat_start(request: Request) -> dict[str, object]:
    return request.app.state.container.assistant.heartbeat_start()


@router.post("/heartbeat/stop")
def runtime_heartbeat_stop(request: Request) -> dict[str, object]:
    return request.app.state.container.assistant.heartbeat_stop()


@router.post("/heartbeat/run-now")
def runtime_heartbeat_run_now(request: Request) -> dict[str, object]:
    return request.app.state.container.assistant.heartbeat_run_now()


@router.get("/events/stream")
def runtime_events_stream(request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(channel="runtime", bus=request.app.state.container.events),
        media_type="text/event-stream",
    )
