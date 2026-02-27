"""Queue an emotion clip from the emotions library."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class PlayEmotionTool(Tool):
    name = "play_emotion"
    description = "Play a recorded emotion clip (e.g. happy, sad, curious)."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Emotion name (e.g. happy, sad, curious)."},
        },
        "required": ["name"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        name = (kwargs.get("name") or "").strip() or "neutral"
        mm = deps.movement_manager
        if mm and hasattr(mm, "queue_emotion"):
            mm.queue_emotion(name)
            return {"ok": True, "message": f"Emotion '{name}' queued."}
        return {"ok": False, "error": "Movement manager not available for emotion."}
