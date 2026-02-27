"""Load profile instructions with optional [template] placeholder includes."""

from __future__ import annotations

import re
from pathlib import Path

_PROMPTS_DIR: Path | None = None


def set_prompts_dir(path: Path) -> None:
    global _PROMPTS_DIR
    _PROMPTS_DIR = path


def get_prompts_dir() -> Path:
    if _PROMPTS_DIR is not None:
        return _PROMPTS_DIR
    return Path(__file__).resolve().parent / "prompts"


def load_instructions(raw: str, prompts_dir: Path | None = None) -> str:
    """
    Resolve [template_name] or [subdir/template_name] placeholders by loading
    the corresponding file from the prompts directory and inlining its content.
    """
    directory = prompts_dir or get_prompts_dir()
    if not directory.is_dir():
        return raw

    pattern = re.compile(r"\[([a-zA-Z0-9_/]+)\]")

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        # Support nested paths: identities/witty_identity -> identities/witty_identity.txt
        parts = key.split("/")
        path = directory
        for p in parts:
            path = path / p
        # Try with .txt if no extension
        if not path.suffix:
            path = path.with_suffix(".txt")
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        return match.group(0)

    return pattern.sub(repl, raw)
