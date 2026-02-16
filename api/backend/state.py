from __future__ import annotations

from dataclasses import dataclass

from .admin_service import AdminDataService
from .chat_service import ChatService
from .config import ApiConfig
from .event_bus import EventBus
from .robot_service import RobotService
from .runtime import RuntimeManager


@dataclass
class AppState:
    config: ApiConfig
    events: EventBus
    runtime: RuntimeManager
    robot: RobotService
    chat: ChatService
    admin: AdminDataService


def build_state() -> AppState:
    config = ApiConfig.from_env()
    events = EventBus()
    robot = RobotService(event_bus=events, config=config)
    state = AppState(
        config=config,
        events=events,
        runtime=RuntimeManager(event_bus=events),
        robot=robot,
        chat=ChatService(event_bus=events, feedback_bridge=robot.feedback_bridge),
        admin=AdminDataService(),
    )
    return state
