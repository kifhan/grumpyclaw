"""Enable or disable head-tracking (face/head position following)."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class HeadTrackingTool(Tool):
    name = "head_tracking"
    description = "Enable or disable head-tracking. When enabled, the robot head follows the user's head position."
    parameters_schema = {
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean", "description": "True to enable, false to disable."},
        },
        "required": ["enabled"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        enabled = bool(kwargs.get("enabled", False))
        mm = deps.movement_manager
        if mm and hasattr(mm, "set_head_tracking_enabled"):
            mm.set_head_tracking_enabled(enabled)
            return {"ok": True, "message": f"Head tracking {'enabled' if enabled else 'disabled'}."}
        return {"ok": False, "error": "Movement manager does not support head tracking."}
