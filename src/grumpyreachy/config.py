"""Configuration helpers for grumpyreachy."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

DEFAULT_PREFERRED_INPUT_DEVICE = "respeaker,seeed-4mic,4mic,voicecard,ac108"


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


def _get_str(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip() or default


def _resolve_realtime_model() -> str:
    model = _get_str("OPENAI_REALTIME_MODEL")
    if model:
        return model
    legacy = _get_str("MODEL_NAME")
    if legacy:
        logging.getLogger("grumpyreachy.config").warning(
            "Deprecated env MODEL_NAME in use. Set OPENAI_REALTIME_MODEL instead."
        )
        return legacy
    return "gpt-realtime"


@dataclass(frozen=True)
class GrumpyReachyConfig:
    observe_interval_seconds: int = 600
    feedback_enabled: bool = True
    reachy_mode: str = "lite"
    camera_analyzer_enabled: bool | None = None
    audio_analyzer_enabled: bool | None = None
    openai_api_key: str = ""
    model_name: str = "gpt-realtime"
    custom_profile: str = "default"
    external_profiles_dir: str = ""
    external_tools_dir: str = ""
    locked_profile: str | None = None
    camera_index: int = 0
    camera_enabled: bool = True
    preferred_input_device: str = DEFAULT_PREFERRED_INPUT_DEVICE
    preferred_output_device: str = ""

    @classmethod
    def from_env(cls) -> "GrumpyReachyConfig":
        return cls(
            observe_interval_seconds=_get_int("GRUMPYREACHY_OBSERVE_INTERVAL", 600),
            feedback_enabled=_get_bool("GRUMPYREACHY_FEEDBACK_ENABLED", True),
            reachy_mode=os.environ.get("GRUMPYREACHY_REACHY_MODE", "lite").strip() or "lite",
            camera_analyzer_enabled=_get_optional_bool("GRUMPYREACHY_CAMERA_ANALYZER_ENABLED"),
            audio_analyzer_enabled=_get_optional_bool("GRUMPYREACHY_AUDIO_ANALYZER_ENABLED"),
            openai_api_key=_get_str("OPENAI_API_KEY"),
            model_name=_resolve_realtime_model(),
            custom_profile=_get_str("GRUMPYREACHY_CUSTOM_PROFILE", "default"),
            external_profiles_dir=_get_str("GRUMPYREACHY_EXTERNAL_PROFILES_DIRECTORY"),
            external_tools_dir=_get_str("GRUMPYREACHY_EXTERNAL_TOOLS_DIRECTORY"),
            locked_profile=os.environ.get("GRUMPYREACHY_LOCKED_PROFILE") or None,
            camera_index=_get_int("GRUMPYREACHY_CAMERA_INDEX", 0),
            camera_enabled=_get_bool("GRUMPYREACHY_CAMERA_ENABLED", True),
            preferred_input_device=_get_str(
                "GRUMPYREACHY_PREFERRED_INPUT_DEVICE",
                DEFAULT_PREFERRED_INPUT_DEVICE,
            ),
            preferred_output_device=_get_str("GRUMPYREACHY_PREFERRED_OUTPUT_DEVICE", ""),
        )
