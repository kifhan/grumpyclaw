from __future__ import annotations

import logging
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


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _get_str(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


@dataclass(frozen=True)
class ApiConfig:
    app_name: str = "grumpyadmin-api"
    cors_origin: str = "http://localhost:5173"
    robot_rate_limit_seconds: float = 1.0
    robot_speak_confirm_threshold: int = 80
    autostart_robot: bool = True
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_ca_bundle: str = ""
    openai_text_model: str = "gpt-5-mini"
    openai_realtime_model: str = "gpt-realtime"
    heartbeat_interval_seconds: int = 1800
    realtime_input_gain: float = 1.0
    realtime_output_gain: float = 1.8
    realtime_mic_suppression_seconds: float = 0.35
    realtime_talk_overlap_mode: str = "strict_anti_loop"
    realtime_post_playback_hold_seconds: float = 0.9
    realtime_voice_effect_mode: str = "chipmunk"
    realtime_aec_enabled: bool = True
    realtime_aec_delay_ms: int = 120
    realtime_aec_strength: float = 0.75
    realtime_aec_corr_threshold: float = 0.12
    realtime_image_cache_dir: str = "data/realtime_image_cache"
    realtime_image_cache_ttl_seconds: int = 604800

    @classmethod
    def from_env(cls) -> "ApiConfig":
        log = logging.getLogger("grumpyadmin.config")

        openai_text_model = os.environ.get("OPENAI_TEXT_MODEL", "").strip()
        if not openai_text_model:
            legacy = os.environ.get("LLM_MODEL", "").strip()
            if legacy:
                openai_text_model = legacy
                log.warning("Deprecated env LLM_MODEL in use. Set OPENAI_TEXT_MODEL instead.")
            else:
                openai_text_model = "gpt-5-mini"

        openai_realtime_model = os.environ.get("OPENAI_REALTIME_MODEL", "").strip()
        if not openai_realtime_model:
            legacy = os.environ.get("MODEL_NAME", "").strip()
            if legacy:
                openai_realtime_model = legacy
                log.warning("Deprecated env MODEL_NAME in use. Set OPENAI_REALTIME_MODEL instead.")
            else:
                openai_realtime_model = "gpt-realtime"

        return cls(
            cors_origin=os.environ.get("GRUMPYADMIN_CORS_ORIGIN", "http://localhost:5173").strip(),
            robot_rate_limit_seconds=float(os.environ.get("GRUMPYADMIN_ROBOT_RATE_LIMIT", "1.0")),
            robot_speak_confirm_threshold=int(os.environ.get("GRUMPYADMIN_SPEAK_CONFIRM_THRESHOLD", "80")),
            autostart_robot=os.environ.get("GRUMPYADMIN_AUTOSTART_ROBOT", "true").strip().lower() in {"1", "true", "yes", "on"},
            openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "").strip(),
            openai_ca_bundle=os.environ.get("OPENAI_CA_BUNDLE", "").strip(),
            openai_text_model=openai_text_model,
            openai_realtime_model=openai_realtime_model,
            heartbeat_interval_seconds=int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "1800")),
            realtime_input_gain=_get_float("GRUMPYREACHY_REALTIME_INPUT_GAIN", 1.0),
            realtime_output_gain=_get_float("GRUMPYREACHY_REALTIME_OUTPUT_GAIN", 1.8),
            realtime_mic_suppression_seconds=_get_float("GRUMPYREACHY_REALTIME_MIC_SUPPRESSION_SECONDS", 0.35),
            realtime_talk_overlap_mode=_get_str("GRUMPYREACHY_REALTIME_TALK_OVERLAP_MODE", "strict_anti_loop"),
            realtime_post_playback_hold_seconds=_get_float("GRUMPYREACHY_REALTIME_POST_PLAYBACK_HOLD_SECONDS", 0.9),
            realtime_voice_effect_mode=_get_str("GRUMPYREACHY_REALTIME_VOICE_EFFECT_MODE", "chipmunk"),
            realtime_aec_enabled=_get_bool("GRUMPYREACHY_REALTIME_AEC_ENABLED", True),
            realtime_aec_delay_ms=_get_int("GRUMPYREACHY_REALTIME_AEC_DELAY_MS", 120),
            realtime_aec_strength=_get_float("GRUMPYREACHY_REALTIME_AEC_STRENGTH", 0.75),
            realtime_aec_corr_threshold=_get_float("GRUMPYREACHY_REALTIME_AEC_CORR_THRESHOLD", 0.12),
            realtime_image_cache_dir=_get_str(
                "GRUMPYADMIN_REALTIME_IMAGE_CACHE_DIR",
                "data/realtime_image_cache",
            ),
            realtime_image_cache_ttl_seconds=_get_int(
                "GRUMPYADMIN_REALTIME_IMAGE_CACHE_TTL_SECONDS",
                604800,
            ),
        )
