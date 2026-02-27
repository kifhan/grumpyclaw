from __future__ import annotations

import logging
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiConfig:
    app_name: str = "grumpyadmin-api"
    cors_origin: str = "http://localhost:5173"
    robot_rate_limit_seconds: float = 1.0
    robot_speak_confirm_threshold: int = 80
    autostart_robot: bool = True
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_text_model: str = "gpt-5-mini"
    openai_realtime_model: str = "gpt-realtime"
    heartbeat_interval_seconds: int = 1800
    realtime_input_gain: float = 1.0
    realtime_output_gain: float = 1.8

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
            openai_text_model=openai_text_model,
            openai_realtime_model=openai_realtime_model,
            heartbeat_interval_seconds=int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "1800")),
            realtime_input_gain=float(os.environ.get("GRUMPYREACHY_REALTIME_INPUT_GAIN", "1.0")),
            realtime_output_gain=float(os.environ.get("GRUMPYREACHY_REALTIME_OUTPUT_GAIN", "1.8")),
        )
