from __future__ import annotations

import time
from pathlib import Path

from api.backend.companion_service import CompanionService
from api.backend.config import ApiConfig
from api.backend.db import init_app_db
from api.backend.event_bus import EventBus
from api.backend.robot_service import RobotActionResult


class _FakeRobotService:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], str, bool]] = []
        self.movement = {
            "available": True,
            "control_queue_size": 0,
            "primary_queue_size": 0,
            "active_interrupting": False,
            "active_move_type": "none",
            "active_move_name": "",
            "listening_mode": False,
        }

    def status(self) -> dict[str, object]:
        return {"run_state": "RUNNING", "robot_connected": False, "thread_alive": False}

    def movement_status(self) -> dict[str, object]:
        return dict(self.movement)

    def get_motion_catalog(self) -> dict[str, object]:
        return {
            "available": True,
            "emotions": ["happy", "curious_mode", "neutral_pose"],
            "dances": ["celebration", "default"],
        }

    def get_camera_worker(self) -> object:
        return object()

    def get_audio_device_status(self) -> dict[str, object]:
        return {"configured": True}

    def enqueue_action(
        self,
        payload: dict[str, object],
        *,
        source: str = "robot",
        bypass_rate_limit: bool = False,
    ) -> RobotActionResult:
        self.calls.append((dict(payload), source, bypass_rate_limit))
        return RobotActionResult(accepted=True, action_id=f"action-{len(self.calls)}", reason="")


def _build_service(tmp_path: Path) -> tuple[CompanionService, _FakeRobotService]:
    robot = _FakeRobotService()
    service = CompanionService(
        event_bus=EventBus(),
        config=ApiConfig(),
        robot_service=robot,
        conversation_active=lambda: False,
    )
    return service, robot


def test_companion_trigger_queues_and_dispatches(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GRUMPYCLAW_DB_PATH", str(tmp_path / "companion.db"))
    init_app_db()
    service, robot = _build_service(tmp_path)

    result = service.handle_trigger("looked_at", source="simulation", confidence=0.9)
    assert result["accepted"] is True

    queued = service.status()["queue"]["queued_reaction"]
    assert queued["trigger"] == "looked_at"
    assert queued["name"] == "curious_mode"

    service._tick()

    assert robot.calls[-1][0]["action"] == "play_emotion"
    assert robot.calls[-1][0]["name"] == "curious_mode"
    assert service.status()["queue"]["active_reaction"]["trigger"] == "looked_at"

    events = service.events()
    assert any(item["event_type"] == "companion.trigger_detected" for item in events)
    assert any(item["event_type"] == "companion.reaction_executed" for item in events)


def test_companion_high_priority_trigger_replaces_queued_idle_heartbeat(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GRUMPYCLAW_DB_PATH", str(tmp_path / "companion-replace.db"))
    init_app_db()
    service, _robot = _build_service(tmp_path)

    first = service.handle_trigger("idle_heartbeat", source="simulation")
    assert first["accepted"] is True
    assert service.status()["queue"]["queued_reaction"]["trigger"] == "idle_heartbeat"

    second = service.handle_trigger("petted", source="simulation")
    assert second["accepted"] is True
    assert second["replaced"]["trigger"] == "idle_heartbeat"
    assert service.status()["queue"]["queued_reaction"]["trigger"] == "petted"


def test_companion_patrol_starts_after_idle_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GRUMPYCLAW_DB_PATH", str(tmp_path / "companion-patrol.db"))
    init_app_db()
    service, robot = _build_service(tmp_path)

    now = time.monotonic()
    service._last_presence_monotonic = now - 30.0
    service._last_idle_block_monotonic = now - 30.0
    service._tick()

    patrol = service.status()["patrol"]
    assert patrol["active"] is True

    service._tick()
    assert robot.calls[-1][0]["action"] == "move_head"
