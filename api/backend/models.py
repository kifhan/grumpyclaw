from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ChatMode = Literal["grumpyclaw", "grumpyreachy"]
RobotActionName = Literal["nod", "look_at", "antenna_feedback", "speak"]


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
