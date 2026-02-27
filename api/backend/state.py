from __future__ import annotations

from dataclasses import dataclass

from .admin_service import AdminDataService
from .assistant import AssistantManager
from .config import ApiConfig
from .event_bus import EventBus
from .robot_service import RobotService


@dataclass
class AppState:
    config: ApiConfig
    events: EventBus
    robot: RobotService
    assistant: AssistantManager
    admin: AdminDataService


def build_state() -> AppState:
    config = ApiConfig.from_env()
    events = EventBus()
    robot = RobotService(event_bus=events, config=config)
    assistant = AssistantManager(event_bus=events, config=config, robot_service=robot)
    state = AppState(
        config=config,
        events=events,
        robot=robot,
        assistant=assistant,
        admin=AdminDataService(),
    )
    assistant.start()
    return state
