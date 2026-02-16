"""Core app lifecycle for grumpyreachy."""

from __future__ import annotations

import enum
import logging
import queue
import signal
import sys
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from types import TracebackType
from typing import Any

from grumpyreachy.actions import ControlAction
from grumpyreachy.config import GrumpyReachyConfig
from grumpyreachy.feedback import FeedbackManager
from grumpyreachy.memory_bridge import MemoryBridge
from grumpyreachy.observer import ObservationEvent, Observer
from grumpyreachy.robot_controller import RobotController


class RunState(enum.Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


def _load_reachy_mini_cls() -> Any | None:
    try:
        from reachy_mini.reachy_mini import ReachyMini
        return ReachyMini
    except ImportError:
        local_src = Path(__file__).resolve().parents[2] / "reachy_mini" / "src"
        if local_src.is_dir() and str(local_src) not in sys.path:
            sys.path.insert(0, str(local_src))
        try:
            from reachy_mini.reachy_mini import ReachyMini
            return ReachyMini
        except ImportError:
            return None


class GrumpyReachyApp:
    """Application runner with queue-based control and graceful shutdown."""

    def __init__(self, config: GrumpyReachyConfig | None = None):
        self.config = config or GrumpyReachyConfig.from_env()
        self.log = logging.getLogger("grumpyreachy.app")
        self.stop_event = threading.Event()
        self.state = RunState.STARTING
        self.control_queue: queue.Queue[ControlAction] = queue.Queue(maxsize=200)
        self._worker_thread: threading.Thread | None = None
        self._observer_thread: threading.Thread | None = None
        self._controller = RobotController(mini=None)
        self._feedback = FeedbackManager(controller=self._controller, enabled=self.config.feedback_enabled)
        self._memory_bridge = MemoryBridge()
        self._observer = Observer(
            interval_seconds=self.config.observe_interval_seconds,
            capture=self._capture_observation_summary,
        )

    def run_forever(self) -> int:
        self._install_signal_handlers()
        self.state = RunState.STARTING
        reachy_cls = _load_reachy_mini_cls()
        conn_ctx = nullcontext(None)
        connection_mode = "localhost_only" if self.config.reachy_mode == "lite" else "auto"
        if reachy_cls is not None:
            try:
                conn_ctx = reachy_cls(connection_mode=connection_mode)
            except Exception:
                self.log.exception("Failed to instantiate ReachyMini; continuing without robot")
        else:
            self.log.warning("ReachyMini import unavailable; running in no-robot mode")

        try:
            with conn_ctx as mini:
                self._controller = RobotController(mini=mini)
                self._feedback.update_controller(self._controller)
                self._start_worker()
                self._start_observer()
                self.state = RunState.RUNNING
                self.log.info("grumpyreachy running; Ctrl+C to stop")
                self.enqueue(ControlAction(name="antenna_feedback", payload={"state": "attention"}))
                while not self.stop_event.is_set():
                    time.sleep(0.2)
        except Exception:
            self.state = RunState.ERROR
            self.log.exception("grumpyreachy app crashed")
            return 1
        finally:
            self._shutdown()
        return 0

    def enqueue(self, action: ControlAction) -> bool:
        if self.stop_event.is_set():
            return False
        try:
            self.control_queue.put(action, timeout=0.2)
            return True
        except queue.Full:
            self.log.warning("control queue full; dropping action %s", action.name)
            return False

    def stop(self) -> None:
        self.stop_event.set()

    @property
    def feedback_manager(self) -> FeedbackManager:
        return self._feedback

    def _start_worker(self) -> None:
        self._worker_thread = threading.Thread(target=self._control_worker, name="grumpyreachy-control", daemon=True)
        self._worker_thread.start()

    def _start_observer(self) -> None:
        self._observer_thread = threading.Thread(
            target=self._observer.run_loop,
            kwargs={"stop_event": self.stop_event, "on_event": self._on_observation_event},
            name="grumpyreachy-observer",
            daemon=True,
        )
        self._observer_thread.start()

    def _control_worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                action = self.control_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self._execute_action(action)
            except Exception:
                self.log.exception("Control action failed: %s", action.name)
            finally:
                self.control_queue.task_done()

    def _execute_action(self, action: ControlAction) -> None:
        payload = action.payload
        if action.name == "look_at":
            self._controller.look_at(
                float(payload.get("x", 0.35)),
                float(payload.get("y", 0.0)),
                float(payload.get("z", 0.1)),
                duration=float(payload.get("duration", 1.0)),
            )
            return
        if action.name == "nod":
            self._controller.nod()
            return
        if action.name == "antenna_feedback":
            self._controller.antenna_feedback(str(payload.get("state", "attention")))
            return
        if action.name == "speak":
            self._controller.speak(str(payload.get("text", "")))
            return
        self.log.debug("Unknown action ignored: %s", action.name)

    def _capture_observation_summary(self) -> str:
        robot_state = "connected" if self._controller.connected else "disconnected"
        camera_status = self._camera_analyzer_status()
        audio_status = self._analyzer_status_from_config(self.config.audio_analyzer_enabled)
        return (
            "Environment heartbeat snapshot. "
            f"Robot={robot_state}. CameraAnalyzer={camera_status}. AudioAnalyzer={audio_status}."
        )

    def _camera_analyzer_status(self) -> str:
        configured = self.config.camera_analyzer_enabled
        if configured is not None:
            return self._analyzer_status_from_config(configured)
        if self._linux_camera_device_detected():
            return "device_detected"
        return "not_configured"

    @staticmethod
    def _analyzer_status_from_config(enabled: bool | None) -> str:
        if enabled is True:
            return "connected"
        if enabled is False:
            return "disconnected"
        return "not_configured"

    @staticmethod
    def _linux_camera_device_detected() -> bool:
        dev_dir = Path("/dev")
        if not dev_dir.is_dir():
            return False
        try:
            return any(dev_dir.glob("video*"))
        except OSError:
            return False

    def _on_observation_event(self, event: ObservationEvent) -> None:
        try:
            chunks = self._memory_bridge.store_observation(event)
            self.log.info("Observation stored: id=%s chunks=%s", event.event_id, chunks)
        except Exception:
            self.log.exception("Failed to store observation event: %s", event.event_id)

    def _shutdown(self) -> None:
        self.state = RunState.STOPPING
        self.stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        if self._observer_thread and self._observer_thread.is_alive():
            self._observer_thread.join(timeout=2.0)
        try:
            self._controller.neutral_pose()
        except Exception:
            self.log.exception("Failed to restore neutral pose")
        self.state = RunState.STOPPED
        self.log.info("grumpyreachy stopped")

    def _install_signal_handlers(self) -> None:
        def _handler(signum: int, _frame: Any | None) -> None:
            self.log.info("Signal received: %s", signum)
            self.stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except ValueError:
                # Signal handlers can only be set from the main thread.
                pass

    def __enter__(self) -> "GrumpyReachyApp":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
