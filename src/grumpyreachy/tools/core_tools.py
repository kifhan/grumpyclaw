"""Base tool class and tool registry for Realtime API tool dispatch."""

from __future__ import annotations

import importlib.util
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# MovementManager is defined in moves.py; avoid circular import by using Any in deps


@dataclass
class ToolDependencies:
    """Injected dependencies available to tools at runtime."""

    robot_controller: Any
    movement_manager: Any  # MovementManager from moves.py
    camera_worker: Any | None
    memory_bridge: Any | None
    feedback_manager: Any | None


# Registry: name -> Tool class (populated by Tool.__init_subclass__ and by _load_tool_module)
ALL_TOOLS: dict[str, type[Tool]] = {}


class Tool(ABC):
    """Base class for tools callable by the Realtime API."""

    name: str = ""
    description: str = ""
    parameters_schema: dict[str, Any] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            ALL_TOOLS[cls.name] = cls

    @abstractmethod
    async def __call__(self, deps: ToolDependencies, **kwargs: Any) -> dict[str, Any]:
        """Execute the tool. Return a dict to send as tool result to the model."""
        ...


def _load_tool_module(module_path: Path) -> type[Tool] | None:
    """Load a single Python file as a tool module and return the Tool subclass."""
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        logging.getLogger("grumpyreachy.tools").exception("Failed to load tool %s", module_path)
        return None
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, Tool) and obj is not Tool and obj.name:
            return obj
    return None


def _discover_tools(tools_dir: Path) -> dict[str, type[Tool]]:
    """Discover Tool subclasses in a directory (e.g. profiles/<name>/ or tools/)."""
    result: dict[str, type[Tool]] = {}
    if not tools_dir.is_dir():
        return result
    for path in sorted(tools_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        cls = _load_tool_module(path)
        if cls and cls.name:
            result[cls.name] = cls
    return result


def get_all_tool_names() -> list[str]:
    """Return all known tool names (from ALL_TOOLS registry)."""
    return sorted(ALL_TOOLS.keys())


def get_tools_for_profile(
    profile_name: str,
    profile_tools_txt: str | None,
    profiles_dir: Path,
    external_tools_dir: Path | None,
) -> list[type[Tool]]:
    """
    Resolve enabled tools for a profile from tools.txt.
    tools.txt lists one tool name per line; # is comment.
    Lookup order: profile dir, then ALL_TOOLS (built-in), then external_tools_dir.
    """
    enabled: list[str] = []
    if profile_tools_txt:
        for line in profile_tools_txt.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                enabled.append(line.split()[0].strip())

    if not enabled:
        enabled = [
            "move_head",
            "dance",
            "stop_dance",
            "play_emotion",
            "stop_emotion",
            "do_nothing",
            "search_memory",
            "ask_grumpyclaw",
        ]

    profile_dir = profiles_dir / profile_name
    profile_tools = _discover_tools(profile_dir) if profile_dir.is_dir() else {}
    external = _discover_tools(external_tools_dir) if external_tools_dir and external_tools_dir.is_dir() else {}

    result: list[type[Tool]] = []
    for name in enabled:
        cls = profile_tools.get(name) or ALL_TOOLS.get(name) or external.get(name)
        if cls:
            result.append(cls)
        else:
            logging.getLogger("grumpyreachy.tools").warning("Tool not found: %s", name)
    return result
