"""Discover and load local SKILL.md files from a directory."""

from __future__ import annotations

import os
from pathlib import Path


def _default_skills_dirs() -> list[Path]:
    """Default directories to scan for SKILL.md (project skills/ and .cursor/skills/)."""
    root = Path(__file__).resolve().parents[3]
    return [root / "skills", root / ".cursor" / "skills"]


def _get_skills_dir() -> list[Path]:
    """Return list of directories to scan (from env or default)."""
    env_path = os.environ.get("GRUMPYCLAW_SKILLS_DIR", "").strip()
    if env_path:
        return [Path(p.strip()) for p in env_path.split(os.pathsep) if p.strip()]
    return _default_skills_dirs()


def list_skills() -> list[dict]:
    """
    Scan configured directories for SKILL.md files.
    Returns list of {"id": str, "path": Path, "name": str, "content": str}.
    """
    dirs = _get_skills_dir()
    seen: set[Path] = set()
    out: list[dict] = []
    for d in dirs:
        if not d.is_dir():
            continue
        d = d.resolve()
        for path in d.rglob("SKILL.md"):
            path = path.resolve()
            if path in seen:
                continue
            seen.add(path)
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            # name: parent dir or "SKILL"
            name = path.parent.name if path.parent != d else "SKILL"
            try:
                rel = path.relative_to(d)
            except ValueError:
                rel = path.name
            skill_id = str(rel).replace("\\", "/").replace("/", "_")
            out.append({
                "id": skill_id,
                "path": path,
                "name": name,
                "content": content,
            })
    return out


def get_skill_content(skill_id: str) -> str:
    """Return full markdown content for a skill by id (from list_skills)."""
    for s in list_skills():
        if s["id"] == skill_id:
            return s["content"]
    return ""
