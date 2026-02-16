from __future__ import annotations

from fastapi import APIRouter, Request

from ..models import RobotActionRequest

router = APIRouter(prefix="/robot", tags=["robot"])


@router.post("/actions")
def post_robot_action(body: RobotActionRequest, request: Request) -> dict[str, object]:
    result = request.app.state.container.robot.enqueue_action(payload=body.model_dump())
    return {
        "accepted": result.accepted,
        "action_id": result.action_id,
        "reason": result.reason,
    }
