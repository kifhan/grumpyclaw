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


def _get_optional_bool(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


@dataclass(frozen=True)
class GrumpyReachyConfig:
    observe_interval_seconds: int = 600
    feedback_enabled: bool = True
    reachy_mode: str = "lite"
    camera_analyzer_enabled: bool | None = None
    audio_analyzer_enabled: bool | None = None

    @classmethod
    def from_env(cls) -> "GrumpyReachyConfig":
        return cls(
            observe_interval_seconds=_get_int("GRUMPYREACHY_OBSERVE_INTERVAL", 600),
            feedback_enabled=_get_bool("GRUMPYREACHY_FEEDBACK_ENABLED", True),
            reachy_mode=os.environ.get("GRUMPYREACHY_REACHY_MODE", "lite").strip() or "lite",
            camera_analyzer_enabled=_get_optional_bool("GRUMPYREACHY_CAMERA_ANALYZER_ENABLED"),
            audio_analyzer_enabled=_get_optional_bool("GRUMPYREACHY_AUDIO_ANALYZER_ENABLED"),
        )
