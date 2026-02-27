"""Tool registry and tool implementations for grumpyreachy conversation."""

from __future__ import annotations

from grumpyreachy.tools.core_tools import (
    ALL_TOOLS,
    Tool,
    ToolDependencies,
    get_all_tool_names,
    get_tools_for_profile,
)
from grumpyreachy.tools import (
    ask_grumpyclaw,
    camera,
    dance,
    do_nothing,
    head_tracking,
    move_head,
    play_emotion,
    search_memory,
    stop_dance,
    stop_emotion,
)

__all__ = [
    "ALL_TOOLS",
    "Tool",
    "ToolDependencies",
    "get_all_tool_names",
    "get_tools_for_profile",
]
