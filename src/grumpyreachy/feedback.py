"""Feedback event handling for tool execution lifecycle."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from grumpyreachy.robot_controller import RobotController


@dataclass(frozen=True)
class FeedbackEvent:
    event_type: str
    tool_name: str
    message: str
    created_at: str


class FeedbackManager:
    """Maps lifecycle events to robot feedback and structured logs."""

    def __init__(self, controller: RobotController, enabled: bool = True):
        self.controller = controller
        self.enabled = enabled
        self.log = logging.getLogger("grumpyreachy.feedback")

    def update_controller(self, controller: RobotController) -> None:
        self.controller = controller

    def emit(self, event_type: str, tool_name: str, message: str = "") -> FeedbackEvent:
        event = FeedbackEvent(
            event_type=event_type,
            tool_name=tool_name,
            message=message,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.log.info("feedback_event=%s", json.dumps(asdict(event), ensure_ascii=True))
        if self.enabled:
            self._dispatch_robot_feedback(event)
        return event

    def _dispatch_robot_feedback(self, event: FeedbackEvent) -> None:
        if event.event_type == "tool_started":
            self.controller.antenna_feedback("attention")
            return
        if event.event_type == "tool_progress":
            return
        if event.event_type == "tool_succeeded":
            self.controller.antenna_feedback("success")
            if event.message:
                self.controller.speak(event.message)
            return
        if event.event_type == "tool_failed":
            self.controller.antenna_feedback("error")
            if event.message:
                self.controller.speak(event.message)
