"""Clear the emotion queue."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class StopEmotionTool(Tool):
    name = "stop_emotion"
    description = "Clear all queued emotions."
    parameters_schema = {"type": "object", "properties": {}}

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        mm = deps.movement_manager
        if mm and hasattr(mm, "clear_emotion_queue"):
            mm.clear_emotion_queue()
            return {"ok": True, "message": "Emotion queue cleared."}
        return {"ok": True, "message": "No emotion queue to clear."}
