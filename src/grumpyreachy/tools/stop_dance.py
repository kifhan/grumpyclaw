"""Clear the dance queue."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class StopDanceTool(Tool):
    name = "stop_dance"
    description = "Clear all queued dances."
    parameters_schema = {"type": "object", "properties": {}}

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        mm = deps.movement_manager
        if mm and hasattr(mm, "clear_dance_queue"):
            mm.clear_dance_queue()
            return {"ok": True, "message": "Dance queue cleared."}
        return {"ok": True, "message": "No dance queue to clear."}
