"""Queue a dance from the dances library."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class DanceTool(Tool):
    name = "dance"
    description = "Queue a dance from the Reachy Mini dances library. Name can be a known dance name."
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Dance name (e.g. from the library)."},
        },
        "required": ["name"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        name = (kwargs.get("name") or "").strip() or "default"
        mm = deps.movement_manager
        if mm and hasattr(mm, "queue_dance"):
            mm.queue_dance(name)
            return {"ok": True, "message": f"Dance '{name}' queued."}
        return {"ok": False, "error": "Movement manager not available for dance."}
