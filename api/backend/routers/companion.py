from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..event_bus import sse_stream
from ..models import CompanionConfig, CompanionSimulateRequest

router = APIRouter(prefix="/companion", tags=["companion"])


@router.get("/config")
def get_companion_config(request: Request) -> dict[str, object]:
    return request.app.state.container.companion.get_config()


@router.put("/config")
def put_companion_config(body: CompanionConfig, request: Request) -> dict[str, object]:
    return request.app.state.container.companion.update_config(body.model_dump())


@router.get("/status")
def get_companion_status(request: Request) -> dict[str, object]:
    return request.app.state.container.companion.status()


@router.get("/events")
def get_companion_events(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    return request.app.state.container.companion.events(limit=limit)


@router.get("/events/stream")
def stream_companion_events(request: Request) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(channel="companion", bus=request.app.state.container.events),
        media_type="text/event-stream",
    )


@router.post("/events/simulate")
def post_companion_simulate(body: CompanionSimulateRequest, request: Request) -> dict[str, object]:
    return request.app.state.container.companion.simulate_trigger(
        trigger=body.trigger,
        confidence=body.confidence,
    )
