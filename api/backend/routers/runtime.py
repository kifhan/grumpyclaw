from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..event_bus import sse_stream

router = APIRouter(prefix="/runtime", tags=["runtime"])


@router.get("/status")
def runtime_status(request: Request) -> dict[str, object]:
    return request.app.state.container.runtime.status()


@router.post("/processes/{name}/start")
def runtime_start(name: str, request: Request) -> dict[str, str]:
    try:
        status = request.app.state.container.runtime.start(name)
        return {"process_name": name, "status": status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/processes/{name}/stop")
def runtime_stop(name: str, request: Request) -> dict[str, str]:
    try:
        status = request.app.state.container.runtime.stop(name)
        return {"process_name": name, "status": status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/processes/{name}/restart")
def runtime_restart(name: str, request: Request) -> dict[str, str]:
    try:
        status = request.app.state.container.runtime.restart(name)
        return {"process_name": name, "status": status}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/events/stream")
def runtime_events_stream(request: Request, channel: str = Query(default="runtime")) -> StreamingResponse:
    return StreamingResponse(sse_stream(channel=channel, bus=request.app.state.container.events), media_type="text/event-stream")
