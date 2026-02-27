"""Queue a head pose change (left/right/up/down/front)."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class MoveHeadTool(Tool):
    name = "move_head"
    description = "Queue a head pose change. Use direction: left, right, up, down, or front."
    parameters_schema = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["left", "right", "up", "down", "front"],
                "description": "Head pose direction.",
            },
        },
        "required": ["direction"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        direction = (kwargs.get("direction") or "front").strip().lower()
        mm = deps.movement_manager
        if mm and hasattr(mm, "queue_head_direction"):
            mm.queue_head_direction(direction)
            return {"ok": True, "message": f"Head moving {direction}."}
        # Fallback: use robot_controller look_at for front
        rc = deps.robot_controller
        if rc and rc.connected:
            x, y, z = 0.35, 0.0, 0.1
            if direction == "left":
                y = 0.2
            elif direction == "right":
                y = -0.2
            elif direction == "up":
                z = 0.2
            elif direction == "down":
                z = -0.05
            rc.look_at(x, y, z, duration=0.5)
            return {"ok": True, "message": f"Head moving {direction}."}
        return {"ok": False, "error": "Robot or movement manager not available."}
