from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ChatMode = Literal["grumpyclaw", "grumpyreachy"]
RobotActionName = Literal[
    "nod",
    "look_at",
    "antenna_feedback",
    "speak",
    "play_emotion",
    "stop_emotion",
    "dance",
    "stop_dance",
]
CompanionTriggerName = Literal["looked_at", "called", "petted", "idle_heartbeat"]
CompanionReactionActionName = Literal["play_emotion", "dance"]
DetectorStatusName = Literal["available", "degraded", "unavailable"]
IdleModeName = Literal["normal", "patrol", "heartbeat_ready"]
PatrolDirectionName = Literal["front", "left", "right", "up", "down"]


class CreateSessionRequest(BaseModel):
    mode: ChatMode
    title: str | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    mode: ChatMode
    created_at: datetime


class PostMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class PostMessageResponse(BaseModel):
    message_id: str
    queued: bool


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    status: str
    created_at: str
    meta: dict[str, Any] = Field(default_factory=dict)


class ProcessActionResponse(BaseModel):
    process_name: str
    status: str


class SkillRunRequest(BaseModel):
    skill_id: str


class RobotActionRequest(BaseModel):
    action: RobotActionName
    name: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    duration: float | None = None
    state: Literal["attention", "success", "error", "neutral"] | None = None
    text: str | None = None
    confirm: bool = False


class RobotActionResponse(BaseModel):
    accepted: bool
    action_id: str
    reason: str = ""


def _default_wake_phrases() -> list[str]:
    return ["grumpy", "grumpyclaw", "reachy"]


def _default_patrol_scan_pattern() -> list[PatrolDirectionName]:
    return ["front", "left", "right", "up", "front"]


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(lowered)
    return out


class CompanionTriggerConfig(BaseModel):
    enabled: bool = True
    cooldown_seconds: int = Field(ge=0, default=0)
    allowed_reaction_types: list[CompanionReactionActionName] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("allowed_reaction_types", mode="before")
    @classmethod
    def _normalize_allowed_reaction_types(cls, value: Any) -> list[CompanionReactionActionName]:
        items = _normalize_string_list(value)
        return [item for item in items if item in {"play_emotion", "dance"}]


class CompanionTriggersConfig(BaseModel):
    looked_at: CompanionTriggerConfig = Field(
        default_factory=lambda: CompanionTriggerConfig(
            enabled=True,
            cooldown_seconds=8,
            allowed_reaction_types=["play_emotion"],
        )
    )
    called: CompanionTriggerConfig = Field(
        default_factory=lambda: CompanionTriggerConfig(
            enabled=True,
            cooldown_seconds=5,
            allowed_reaction_types=["play_emotion"],
        )
    )
    petted: CompanionTriggerConfig = Field(
        default_factory=lambda: CompanionTriggerConfig(
            enabled=True,
            cooldown_seconds=4,
            allowed_reaction_types=["play_emotion"],
        )
    )
    idle_heartbeat: CompanionTriggerConfig = Field(
        default_factory=lambda: CompanionTriggerConfig(
            enabled=True,
            cooldown_seconds=90,
            allowed_reaction_types=["play_emotion", "dance"],
        )
    )

    model_config = {"extra": "forbid"}


class CompanionConfig(BaseModel):
    enabled: bool = True
    idle_interval_seconds: int = Field(ge=1, default=90)
    wake_phrases: list[str] = Field(default_factory=_default_wake_phrases)
    queue_policy: Literal["queue_next"] = "queue_next"
    patrol_enabled: bool = True
    patrol_start_after_seconds: int = Field(ge=1, default=20)
    patrol_scan_pattern: list[PatrolDirectionName] = Field(default_factory=_default_patrol_scan_pattern)
    patrol_step_duration_seconds: float = Field(gt=0.0, default=1.0)
    look_dwell_ms: int = Field(ge=100, default=1200)
    triggers: CompanionTriggersConfig = Field(default_factory=CompanionTriggersConfig)

    model_config = {"extra": "forbid"}

    @field_validator("wake_phrases", mode="before")
    @classmethod
    def _normalize_wake_phrases(cls, value: Any) -> list[str]:
        phrases = _normalize_string_list(value)
        return phrases or _default_wake_phrases()

    @field_validator("patrol_scan_pattern", mode="before")
    @classmethod
    def _normalize_patrol_scan_pattern(cls, value: Any) -> list[PatrolDirectionName]:
        allowed = {"front", "left", "right", "up", "down"}
        items = _normalize_string_list(value)
        normalized = [item for item in items if item in allowed]
        return normalized or _default_patrol_scan_pattern()


class CompanionSimulateRequest(BaseModel):
    trigger: CompanionTriggerName
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    model_config = {"extra": "forbid"}
