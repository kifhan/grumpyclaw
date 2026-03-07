from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.backend.robot_service import RobotActionResult
from api.main import create_app


@pytest.fixture()
def client(tmp_path: Path):
    os.environ["GRUMPYCLAW_DB_PATH"] = str(tmp_path / "test.db")
    os.environ["GRUMPYADMIN_AUTOSTART_ROBOT"] = "false"
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_healthz(client: TestClient) -> None:
    r = client.get("/api/v1/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_public_config_includes_realtime_overlap_controls(client: TestClient) -> None:
    r = client.get("/api/v1/config/public")
    assert r.status_code == 200
    body = r.json()
    assert "realtime_talk_overlap_mode" in body
    assert "realtime_post_playback_hold_seconds" in body


def test_assistant_session_create_and_post(client: TestClient) -> None:
    r = client.post("/api/v1/assistant/sessions", json={"mode": "assistant"})
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    r = client.post(f"/api/v1/assistant/sessions/{session_id}/messages", json={"content": "hello"})
    assert r.status_code == 200
    assert r.json()["queued"] is True


def test_robot_requires_confirm_for_look(client: TestClient) -> None:
    r = client.post("/api/v1/robot/actions", json={"action": "look_at", "x": 0.1, "y": 0.1, "z": 0.2})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert "confirm" in body["reason"]


def test_robot_expressive_action_enum_is_accepted(client: TestClient) -> None:
    r = client.post("/api/v1/robot/actions", json={"action": "dance", "name": "happy", "duration": 1.5})
    assert r.status_code == 200
    body = r.json()
    assert "accepted" in body
    assert "action_id" in body


def test_runtime_heartbeat_controls(client: TestClient) -> None:
    r = client.get("/api/v1/runtime/status")
    assert r.status_code == 200
    assert "heartbeat" in r.json()

    r = client.post("/api/v1/runtime/heartbeat/run-now")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "trigger" in body


def test_companion_endpoints(client: TestClient) -> None:
    r = client.get("/api/v1/companion/config")
    assert r.status_code == 200
    assert "triggers" in r.json()

    client.app.state.container.robot.enqueue_action = (  # type: ignore[method-assign]
        lambda payload, source="robot", bypass_rate_limit=False: RobotActionResult(
            accepted=True,
            action_id="test-action",
            reason="",
        )
    )

    r = client.post("/api/v1/companion/events/simulate", json={"trigger": "looked_at"})
    assert r.status_code == 200
    assert r.json()["accepted"] is True
    assert "status" in r.json()

    r = client.get("/api/v1/companion/status")
    assert r.status_code == 200
    assert "detectors" in r.json()


def test_old_chat_and_conversation_routes_removed(client: TestClient) -> None:
    assert client.get("/api/v1/chat/sessions").status_code == 404
    assert client.get("/api/v1/conversation/status").status_code == 404


def test_logs_filter_by_source_level_and_query(client: TestClient) -> None:
    r = client.post("/api/v1/robot/actions", json={"action": "look_at", "x": 0.1, "y": 0.1, "z": 0.2})
    assert r.status_code == 200
    assert r.json()["accepted"] is False

    r = client.get(
        "/api/v1/logs",
        params={
            "source": "robot",
            "level": "warning",
            "event_type": "robot.action",
            "q": "confirm",
            "limit": 10,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "robot"
    assert body["level"] == "warning"
    assert body["event_type"] == "robot.action"
    assert len(body["items"]) >= 1
    for item in body["items"]:
        assert item["source"] == "robot"
        assert item["level"] == "WARNING"
        assert item["event_type"] == "robot.action"
