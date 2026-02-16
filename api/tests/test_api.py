from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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


def test_chat_session_create_and_post(client: TestClient) -> None:
    r = client.post("/api/v1/chat/sessions", json={"mode": "grumpyclaw"})
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    r = client.post(f"/api/v1/chat/sessions/{session_id}/messages", json={"content": "hello"})
    assert r.status_code == 200
    assert r.json()["queued"] is True


def test_robot_requires_confirm_for_look(client: TestClient) -> None:
    r = client.post("/api/v1/robot/actions", json={"action": "look_at", "x": 0.1, "y": 0.1, "z": 0.2})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is False
    assert "confirm" in body["reason"]


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
