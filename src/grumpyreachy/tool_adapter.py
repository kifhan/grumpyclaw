"""Expose grumpyclaw capabilities as tool handlers with lifecycle feedback."""

from __future__ import annotations

from typing import Any

from grumpyclaw.llm.client import chat
from grumpyclaw.memory.retriever import Retriever
from grumpyclaw.skills.registry import get_skill_content
from grumpyreachy.feedback import FeedbackManager


class GrumpyClawToolAdapter:
    """Tool handlers for ask, run_skill, and memory search."""

    def __init__(self, feedback: FeedbackManager):
        self.feedback = feedback
        self.retriever = Retriever()

    def ask(self, prompt: str) -> dict[str, Any]:
        tool = "grumpyclaw.ask"
        self.feedback.emit("tool_started", tool_name=tool)
        try:
            self.feedback.emit("tool_progress", tool_name=tool, message="querying_llm")
            reply = chat([{"role": "user", "content": prompt}])
            msg = "Task completed."
            self.feedback.emit("tool_succeeded", tool_name=tool, message=msg)
            return {"ok": True, "tool": tool, "result": reply}
        except Exception as exc:
            reason = f"Ask failed: {exc}"
            self.feedback.emit("tool_failed", tool_name=tool, message=reason)
            return {"ok": False, "tool": tool, "error": reason}

    def search_memory(self, query: str, top_k: int = 5) -> dict[str, Any]:
        tool = "grumpyclaw.search_memory"
        self.feedback.emit("tool_started", tool_name=tool)
        try:
            hits = self.retriever.hybrid_search(query=query, top_k=top_k)
            self.feedback.emit("tool_succeeded", tool_name=tool, message="Found memory results.")
            return {"ok": True, "tool": tool, "result": hits}
        except Exception as exc:
            reason = f"Memory search failed: {exc}"
            self.feedback.emit("tool_failed", tool_name=tool, message=reason)
            return {"ok": False, "tool": tool, "error": reason}

    def run_skill(self, skill_id: str) -> dict[str, Any]:
        tool = "grumpyclaw.run_skill"
        self.feedback.emit("tool_started", tool_name=tool)
        try:
            content = get_skill_content(skill_id)
            if not content:
                raise ValueError(f"Skill not found: {skill_id}")
            self.feedback.emit("tool_succeeded", tool_name=tool, message="Skill loaded.")
            return {"ok": True, "tool": tool, "result": {"skill_id": skill_id, "content": content}}
        except Exception as exc:
            reason = f"Run skill failed: {exc}"
            self.feedback.emit("tool_failed", tool_name=tool, message=reason)
            return {"ok": False, "tool": tool, "error": reason}
