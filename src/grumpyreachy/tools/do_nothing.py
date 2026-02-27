"""Explicitly remain idle."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class DoNothingTool(Tool):
    name = "do_nothing"
    description = "Explicitly do nothing; remain idle. Use when the user asks for no action."
    parameters_schema = {"type": "object", "properties": {}}

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "message": "No action taken."}
