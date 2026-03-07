from __future__ import annotations

from api.backend.config import ApiConfig
from api.backend.event_bus import EventBus
from api.backend.robot_service import RobotService


def test_to_control_action_maps_play_emotion() -> None:
    action = RobotService._to_control_action({"action": "play_emotion", "name": "happy", "duration": 3.0})
    assert action is not None
    assert action.name == "play_emotion"
    assert action.payload["name"] == "happy"
    assert action.payload["duration"] == 3.0


def test_to_control_action_maps_dance_with_defaults() -> None:
    action = RobotService._to_control_action({"action": "dance"})
    assert action is not None
    assert action.name == "dance"
    assert action.payload["name"] == "default"
    assert action.payload["duration"] == 10.0


def test_to_control_action_maps_stop_actions() -> None:
    stop_emotion = RobotService._to_control_action({"action": "stop_emotion"})
    stop_dance = RobotService._to_control_action({"action": "stop_dance"})
    assert stop_emotion is not None
    assert stop_dance is not None
    assert stop_emotion.name == "stop_emotion"
    assert stop_dance.name == "stop_dance"


def test_to_control_action_defaults_missing_expression_durations() -> None:
    play = RobotService._to_control_action({"action": "play_emotion", "name": "happy", "duration": None})
    dance = RobotService._to_control_action({"action": "dance", "name": "default", "duration": None})
    look = RobotService._to_control_action({"action": "look_at", "duration": None})

    assert play is not None
    assert dance is not None
    assert look is not None
    assert play.payload["duration"] == 5.0
    assert dance.payload["duration"] == 10.0
    assert look.payload["duration"] == 1.0


def test_get_motion_catalog_returns_empty_when_robot_not_running() -> None:
    service = RobotService(event_bus=EventBus(), config=ApiConfig())

    catalog = service.get_motion_catalog()

    assert catalog == {"available": False, "emotions": [], "dances": []}


def test_get_motion_catalog_forwards_controller_catalog() -> None:
    class _Controller:
        def get_motion_catalog(self) -> dict[str, object]:
            return {"available": True, "emotions": ["happy", "curious"], "dances": ["default"]}

    class _App:
        _controller = _Controller()

    service = RobotService(event_bus=EventBus(), config=ApiConfig())
    service._app = _App()  # type: ignore[assignment]

    catalog = service.get_motion_catalog()

    assert catalog["available"] is True
    assert catalog["emotions"] == ["happy", "curious"]
    assert catalog["dances"] == ["default"]
