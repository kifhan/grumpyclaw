from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from grumpyreachy.actions import ControlAction
from grumpyreachy.app import GrumpyReachyApp, RunState

from .config import ApiConfig
from .db import dump_json, get_conn
from .event_bus import EventBus, StreamEvent


class ApiFeedbackBridge:
    """Adapter that forwards FeedbackManager events to API SSE channels."""

    def __init__(self, event_bus: EventBus):
        self._event_bus = event_bus

    def emit(self, event_type: str, tool_name: str, message: str = "") -> dict[str, Any]:
        data = {
            "tool_name": tool_name,
            "phase": event_type,
            "message": message,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._event_bus.publish("robot-feedback", StreamEvent(event="tool.event", data=data))
        if event_type in {"tool_succeeded", "tool_failed"}:
            state = "success" if event_type == "tool_succeeded" else "error"
            self._event_bus.publish(
                "robot-feedback",
                StreamEvent(
                    event="robot.feedback",
                    data={"state": state, "message": message, "ts": data["ts"]},
                ),
            )
        return data


@dataclass
class RobotActionResult:
    accepted: bool
    action_id: str
    reason: str = ""


def _status_payload(
    run_state: str,
    robot_connected: bool,
    thread_alive: bool,
) -> dict[str, Any]:
    return {
        "run_state": run_state,
        "robot_connected": robot_connected,
        "thread_alive": thread_alive,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


class RobotService:
    def __init__(self, event_bus: EventBus, config: ApiConfig):
        self._event_bus = event_bus
        self._config = config
        self._app: GrumpyReachyApp | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_action_at: dict[str, float] = {}
        self.feedback_bridge = ApiFeedbackBridge(event_bus=event_bus)
        self._last_emitted_status: dict[str, Any] | None = None
        self._status_poller_thread: threading.Thread | None = None
        self._status_poller_stop = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._app = GrumpyReachyApp()
            self._thread = threading.Thread(target=self._app.run_forever, name="api-grumpyreachy", daemon=True)
            self._thread.start()
            if self._status_poller_thread is None or not self._status_poller_thread.is_alive():
                self._status_poller_stop.clear()
                self._status_poller_thread = threading.Thread(
                    target=self._status_poller_loop,
                    name="robot-service-status-poller",
                    daemon=True,
                )
                self._status_poller_thread.start()

    def _status_poller_loop(self) -> None:
        while not self._status_poller_stop.wait(timeout=2.0):
            payload = self.status()
            with self._lock:
                last = self._last_emitted_status
            if last is None or (
                last.get("run_state") != payload["run_state"]
                or last.get("robot_connected") != payload["robot_connected"]
                or last.get("thread_alive") != payload["thread_alive"]
            ):
                with self._lock:
                    self._last_emitted_status = dict(payload)
                self._event_bus.publish(
                    "runtime",
                    StreamEvent(event="robot.status", data=payload),
                )

    def status(self) -> dict[str, Any]:
        """Return current robot service state for API/UI (run_state, robot_connected, thread_alive, ts)."""
        with self._lock:
            app = self._app
            thread = self._thread
        if app is None:
            return _status_payload("stopped", False, False)
        thread_alive = thread is not None and thread.is_alive()
        run_state = app.state.name
        robot_connected = getattr(app._controller, "connected", False)
        return _status_payload(run_state, robot_connected, thread_alive)

    def get_app(self) -> GrumpyReachyApp | None:
        """Return the running GrumpyReachyApp instance, or None if not started."""
        with self._lock:
            return self._app

    def stop(self) -> None:
        self._status_poller_stop.set()
        with self._lock:
            if self._app:
                self._app.stop()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
            self._last_emitted_status = None

    def enqueue_action(self, payload: dict[str, Any]) -> RobotActionResult:
        self.start()
        action = str(payload.get("action", "")).strip()
        action_id = str(uuid.uuid4())
        now = time.monotonic()
        with self._lock:
            last = self._last_action_at.get(action, 0.0)
            if now - last < self._config.robot_rate_limit_seconds:
                reason = "Action rate limited"
                self._record_action(action_id, action, payload, False, reason)
                return RobotActionResult(accepted=False, action_id=action_id, reason=reason)
            self._last_action_at[action] = now
        if action == "look_at" and not bool(payload.get("confirm")):
            reason = "look_at requires confirm=true"
            self._record_action(action_id, action, payload, False, reason)
            return RobotActionResult(accepted=False, action_id=action_id, reason=reason)
        if action == "speak":
            text = str(payload.get("text", ""))
            if len(text) >= self._config.robot_speak_confirm_threshold and not bool(payload.get("confirm")):
                reason = "long speak requires confirm=true"
                self._record_action(action_id, action, payload, False, reason)
                return RobotActionResult(accepted=False, action_id=action_id, reason=reason)

        ca = self._to_control_action(payload)
        if not ca:
            reason = f"Unsupported action: {action}"
            self._record_action(action_id, action, payload, False, reason)
            return RobotActionResult(accepted=False, action_id=action_id, reason=reason)

        ok = bool(self._app and self._app.enqueue(ca))
        reason = "" if ok else "robot runtime unavailable"
        self._record_action(action_id, action, payload, ok, reason)
        return RobotActionResult(accepted=ok, action_id=action_id, reason=reason)

    @staticmethod
    def _to_control_action(payload: dict[str, Any]) -> ControlAction | None:
        action = str(payload.get("action", ""))
        if action == "nod":
            return ControlAction(name="nod")
        if action == "look_at":
            return ControlAction(
                name="look_at",
                payload={
                    "x": float(payload.get("x", 0.35)),
                    "y": float(payload.get("y", 0.0)),
                    "z": float(payload.get("z", 0.1)),
                    "duration": float(payload.get("duration", 1.0)),
                },
            )
        if action == "antenna_feedback":
            return ControlAction(name="antenna_feedback", payload={"state": str(payload.get("state", "attention"))})
        if action == "speak":
            return ControlAction(name="speak", payload={"text": str(payload.get("text", ""))})
        return None

    def _record_action(self, action_id: str, action: str, payload: dict[str, Any], accepted: bool, reason: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        level = "INFO" if accepted else "WARNING"
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO app_robot_actions(id, source, level, action, payload_json, accepted, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (action_id, "robot", level, action, dump_json(payload), 1 if accepted else 0, reason, ts),
            )
            conn.commit()
        finally:
            conn.close()
        self._event_bus.publish(
            "runtime",
            StreamEvent(
                event="robot.action",
                data={
                    "action_id": action_id,
                    "action": action,
                    "accepted": accepted,
                    "level": level,
                    "reason": reason,
                    "ts": ts,
                },
            ),
        )
