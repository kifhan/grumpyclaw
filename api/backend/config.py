from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiConfig:
    app_name: str = "grumpyadmin-api"
    cors_origin: str = "http://localhost:5173"
    robot_rate_limit_seconds: float = 1.0
    robot_speak_confirm_threshold: int = 80
    autostart_robot: bool = True

    @classmethod
    def from_env(cls) -> "ApiConfig":
        return cls(
            cors_origin=os.environ.get("GRUMPYADMIN_CORS_ORIGIN", "http://localhost:5173").strip(),
            robot_rate_limit_seconds=float(os.environ.get("GRUMPYADMIN_ROBOT_RATE_LIMIT", "1.0")),
            robot_speak_confirm_threshold=int(os.environ.get("GRUMPYADMIN_SPEAK_CONFIRM_THRESHOLD", "80")),
            autostart_robot=os.environ.get("GRUMPYADMIN_AUTOSTART_ROBOT", "true").strip().lower() in {"1", "true", "yes", "on"},
        )
