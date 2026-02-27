"""Ask grumpyclaw (LLM) a question."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class AskGrumpyclawTool(Tool):
    name = "ask_grumpyclaw"
    description = "Ask the agent's LLM a question or run a task. Use for reasoning or when you need a detailed answer."
    parameters_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "The question or task for the LLM."},
        },
        "required": ["prompt"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        prompt = (kwargs.get("prompt") or "").strip()
        if not prompt:
            return {"ok": False, "error": "Prompt is required."}
        if deps.feedback_manager:
            deps.feedback_manager.emit("tool_started", tool_name=self.name)
        try:
            from grumpyclaw.llm.client import chat

            if deps.feedback_manager:
                deps.feedback_manager.emit("tool_progress", tool_name=self.name, message="querying_llm")
            reply = chat([{"role": "user", "content": prompt}])
            if deps.feedback_manager:
                deps.feedback_manager.emit("tool_succeeded", tool_name=self.name, message="Task completed.")
            return {"ok": True, "result": reply}
        except Exception as exc:
            if deps.feedback_manager:
                deps.feedback_manager.emit("tool_failed", tool_name=self.name, message=str(exc))
            return {"ok": False, "error": str(exc)}
