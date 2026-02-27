"""Conversation (Realtime API) and profile management endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from grumpyreachy.config import GrumpyReachyConfig

router = APIRouter(prefix="/conversation", tags=["conversation"])
profiles_router = APIRouter(prefix="/profiles", tags=["profiles"])
LOG = logging.getLogger("grumpyadmin.conversation")


def _webrtc_offer_unavailable(request: Request) -> JSONResponse:
    """Returned when fastrtc stream is not mounted (fallback route)."""
    detail = "Conversation stream not available. Install fastrtc and ensure the robot app can start."
    reason = getattr(request.app.state, "conversation_stream_error", None)
    if reason:
        detail += f" Reason: {reason}"
    return JSONResponse(status_code=503, content={"detail": detail})

# Module-level stream and transcript queue for SSE; set by mount_conversation_stream
_conversation_stream: Any = None
_transcript_queue: asyncio.Queue[dict[str, Any]] | None = None


def _profiles_dir(request: Request) -> Path:
    """Resolve profiles directory from app state or default."""
    app = request.app
    robot = getattr(app.state.container, "robot", None)
    app_instance = robot.get_app() if robot else None
    if app_instance and hasattr(app_instance, "_profiles_dir"):
        return app_instance._profiles_dir
    return Path(__file__).resolve().parents[3] / "src" / "grumpyreachy" / "profiles"


def _external_profiles_dir(request: Request) -> Path | None:
    config = GrumpyReachyConfig.from_env()
    if config.external_profiles_dir:
        return Path(config.external_profiles_dir)
    return None


@router.post("/start", response_model=None)
async def conversation_start(request: Request) -> dict[str, Any] | JSONResponse:
    """Ensure robot app is running; conversation stream is already mounted."""
    robot = request.app.state.container.robot
    robot.start()
    app = robot.get_app()
    if not app:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "Robot app failed to start"},
        )
    profile = getattr(app.config, "custom_profile", None) or "default"
    return {"ok": True, "profile": profile, "message": "Conversation ready; connect via WebRTC."}


@router.post("/stop")
async def conversation_stop(request: Request) -> dict[str, Any]:
    """No-op; each WebRTC connection closes independently."""
    return {"ok": True, "message": "Use WebRTC disconnect to stop."}


@router.get("/status")
async def conversation_status(request: Request) -> dict[str, Any]:
    """Return current conversation-related status."""
    robot = request.app.state.container.robot
    app = robot.get_app()
    profile = "default"
    if app:
        profile = getattr(app.config, "custom_profile", None) or "default"
    stream_error = getattr(request.app.state, "conversation_stream_error", None)
    return {
        "robot_running": app is not None,
        "profile": profile,
        "stream_mounted": _conversation_stream is not None,
        "stream_mount_error": stream_error,
    }


@router.get("/transcript")
async def conversation_transcript_stream(request: Request) -> StreamingResponse:
    """SSE stream of transcript and tool events."""

    async def event_stream():
        q = _transcript_queue
        if not q:
            yield f"data: {json.dumps({'error': 'Transcript not available'})}\n\n"
            return
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@profiles_router.get("")
async def list_profiles(request: Request) -> list[dict[str, Any]]:
    """List available profile names and paths."""
    base = _profiles_dir(request)
    external = _external_profiles_dir(request)
    result: list[dict[str, Any]] = []
    for d in (base, external) if external else (base,):
        if not d or not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.is_dir() and (p / "instructions.txt").is_file():
                result.append({"name": p.name, "path": str(p)})
    return result


@profiles_router.post("")
async def create_profile(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Create a new profile with instructions and optional tools."""
    name = (body.get("name") or "").strip()
    instructions = (body.get("instructions") or "").strip()
    if not name:
        return {"ok": False, "error": "name required"}
    base = _profiles_dir(request)
    profile_dir = base / name
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "instructions.txt").write_text(instructions, encoding="utf-8")
    tools_txt = body.get("tools")
    if tools_txt is not None:
        (profile_dir / "tools.txt").write_text(tools_txt if isinstance(tools_txt, str) else "\n".join(tools_txt), encoding="utf-8")
    else:
        default_tools = (base / "default" / "tools.txt").read_text(encoding="utf-8") if (base / "default" / "tools.txt").is_file() else ""
        if default_tools:
            (profile_dir / "tools.txt").write_text(default_tools, encoding="utf-8")
    return {"ok": True, "name": name, "path": str(profile_dir)}


@profiles_router.put("/{name}")
async def update_profile(request: Request, name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Update profile instructions and/or tools."""
    base = _profiles_dir(request)
    profile_dir = base / name
    if not profile_dir.is_dir():
        return {"ok": False, "error": "Profile not found"}
    if "instructions" in body:
        (profile_dir / "instructions.txt").write_text(str(body["instructions"]), encoding="utf-8")
    if "tools" in body:
        (profile_dir / "tools.txt").write_text(body["tools"] if isinstance(body["tools"], str) else "\n".join(body["tools"]), encoding="utf-8")
    return {"ok": True, "name": name}


def build_factory_handler(
    get_app_fn: Any,
    default_profile: str,
    transcript_queue: asyncio.Queue[dict[str, Any]],
) -> Any:
    """Build an AsyncStreamHandler whose copy() returns a real handler from the app."""

    from fastrtc import AsyncStreamHandler

    class FactoryHandler(AsyncStreamHandler):
        def __init__(self, get_app: Any, profile: str, tq: asyncio.Queue):
            super().__init__(expected_layout="mono", output_sample_rate=24000, input_sample_rate=24000)
            self._get_app = get_app
            self._profile = profile
            self._transcript_queue = tq

        async def emit(self) -> Any:
            """Not used; copy() returns the real handler which implements emit."""
            return None

        async def receive(self, frame: tuple[int, Any]) -> None:
            """Not used; copy() returns the real handler which implements receive."""
            pass

        def copy(self) -> AsyncStreamHandler:
            app = self._get_app()
            if not app:
                raise RuntimeError("Robot app not running; start the robot first.")

            def on_transcript(m: dict) -> None:
                try:
                    self._transcript_queue.put_nowait(m)
                except Exception:
                    pass

            return app.create_realtime_handler(profile_name=self._profile, on_transcript=on_transcript)

    return FactoryHandler(get_app_fn, default_profile, transcript_queue)


def mount_conversation_stream(app: Any, get_app_fn: Any, default_profile: str = "default") -> None:
    """Create and mount the fastrtc Stream for conversation on the FastAPI app."""
    global _conversation_stream, _transcript_queue
    _transcript_queue = asyncio.Queue()
    try:
        from fastrtc import Stream

        handler = build_factory_handler(get_app_fn, default_profile, _transcript_queue)
        _conversation_stream = Stream(handler, mode="send-receive", modality="audio")
        _conversation_stream.mount(app, path="/api/v1")
        LOG.info("Conversation stream mounted at /api/v1/webrtc/offer")
    except ImportError as e:
        LOG.warning("fastrtc not available; conversation stream disabled: %s", e)
