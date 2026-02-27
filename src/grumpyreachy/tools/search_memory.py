"""Search grumpyclaw memory (hybrid search)."""

from __future__ import annotations

from typing import Any

from grumpyreachy.tools.core_tools import Tool, ToolDependencies


class SearchMemoryTool(Tool):
    name = "search_memory"
    description = "Search the agent's memory for relevant past content. Use when you need to recall stored information."
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "top_k": {"type": "integer", "description": "Max number of results (default 5).", "default": 5},
        },
        "required": ["query"],
    }

    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "Query is required."}
        top_k = int(kwargs.get("top_k") or 5)
        if deps.feedback_manager:
            deps.feedback_manager.emit("tool_started", tool_name=self.name)
        try:
            from grumpyclaw.memory.retriever import Retriever

            retriever = Retriever()
            hits = retriever.hybrid_search(query=query, top_k=top_k)
            if deps.feedback_manager:
                deps.feedback_manager.emit("tool_succeeded", tool_name=self.name, message="Found memory results.")
            return {"ok": True, "result": hits}
        except Exception as exc:
            if deps.feedback_manager:
                deps.feedback_manager.emit("tool_failed", tool_name=self.name, message=str(exc))
            return {"ok": False, "error": str(exc)}
