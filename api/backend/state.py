from __future__ import annotations

from dataclasses import dataclass

from .admin_service import AdminDataService
from .assistant import AssistantManager
from .companion_service import CompanionService
from .config import ApiConfig
from .event_bus import EventBus
from .robot_service import RobotService


@dataclass
class AppState:
    config: ApiConfig
    events: EventBus
    robot: RobotService
    assistant: AssistantManager
    companion: CompanionService
    admin: AdminDataService


def build_state() -> AppState:
    config = ApiConfig.from_env()
    events = EventBus()
    robot = RobotService(event_bus=events, config=config)
    assistant = AssistantManager(event_bus=events, config=config, robot_service=robot)
    companion = CompanionService(
        event_bus=events,
        config=config,
        robot_service=robot,
        conversation_active=assistant.conversation_active,
        reaction_resolver=assistant.resolve_companion_reaction,
    )
    state = AppState(
        config=config,
        events=events,
        robot=robot,
        assistant=assistant,
        companion=companion,
        admin=AdminDataService(),
    )
    assistant.start()
    companion.start()
    return state
