from __future__ import annotations

from fastapi import APIRouter, Request

from ..models import RobotActionRequest

router = APIRouter(prefix="/robot", tags=["robot"])


@router.get("/status")
def get_robot_status(request: Request) -> dict[str, object]:
    """Return in-process robot service state: run_state, robot_connected, thread_alive."""
    status = request.app.state.container.robot.status()
    return status or {}


@router.post("/start")
def post_robot_start(request: Request) -> dict[str, object]:
    """Start the in-process robot service (GrumpyReachyApp)."""
    request.app.state.container.robot.start()
    return {"ok": True, "message": "Robot service start requested"}


@router.post("/stop")
def post_robot_stop(request: Request) -> dict[str, object]:
    """Stop the in-process robot service."""
    request.app.state.container.robot.stop()
    return {"ok": True, "message": "Robot service stopped"}


@router.post("/restart")
def post_robot_restart(request: Request) -> dict[str, object]:
    """Restart the in-process robot service."""
    request.app.state.container.robot.stop()
    request.app.state.container.robot.start()
    return {"ok": True, "message": "Robot service restart requested"}


@router.post("/actions")
def post_robot_action(body: RobotActionRequest, request: Request) -> dict[str, object]:
    result = request.app.state.container.robot.enqueue_action(payload=body.model_dump())
    return {
        "accepted": result.accepted,
        "action_id": result.action_id,
        "reason": result.reason,
    }
