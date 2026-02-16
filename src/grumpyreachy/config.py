"""Configuration helpers for grumpyreachy."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class GrumpyReachyConfig:
    observe_interval_seconds: int = 600
    feedback_enabled: bool = True
    reachy_mode: str = "lite"

    @classmethod
    def from_env(cls) -> "GrumpyReachyConfig":
        return cls(
            observe_interval_seconds=_get_int("GRUMPYREACHY_OBSERVE_INTERVAL", 600),
            feedback_enabled=_get_bool("GRUMPYREACHY_FEEDBACK_ENABLED", True),
            reachy_mode=os.environ.get("GRUMPYREACHY_REACHY_MODE", "lite").strip() or "lite",
        )
