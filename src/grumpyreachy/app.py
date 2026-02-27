"""Core app lifecycle for grumpyreachy: robot, movement, observer, and conversation support."""

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
from grumpyreachy.moves import MovementManager
from grumpyreachy.observer import ObservationEvent, Observer
from grumpyreachy.robot_controller import RobotController
from grumpyreachy.tools.core_tools import ToolDependencies, get_tools_for_profile


class RunState(enum.Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


def _parse_device_preferences(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _find_device_index(
    devices: list[dict[str, Any]],
    *,
    io_type: str,
    preferences: list[str],
) -> int | None:
    channel_key = f"max_{io_type}_channels"
    for pref in preferences:
        needle = pref.lower()
        for index, device in enumerate(devices):
            channels_raw = device.get(channel_key, 0)
            try:
                channels = int(channels_raw)
            except (TypeError, ValueError):
                channels = 0
            if channels <= 0:
                continue
            if needle in str(device.get("name", "")).lower():
                return index
    return None


def _device_info(devices: list[dict[str, Any]], index: int | None) -> dict[str, Any] | None:
    if index is None or index < 0 or index >= len(devices):
        return None
    entry = devices[index]
    return {
        "id": index,
        "name": str(entry.get("name", "")),
        "max_input_channels": int(entry.get("max_input_channels", 0) or 0),
        "max_output_channels": int(entry.get("max_output_channels", 0) or 0),
        "default_samplerate": float(entry.get("default_samplerate", 0.0) or 0.0),
    }


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
    """Application runner: queue-based control, movement manager, observer, and conversation support."""

    def __init__(self, config: GrumpyReachyConfig | None = None, no_camera: bool = False):
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
        self._movement_manager: MovementManager | None = None
        self._camera_worker: Any = None
        self._no_camera = no_camera
        self._observer = Observer(
            interval_seconds=self.config.observe_interval_seconds,
            capture=self._capture_observation_summary,
        )
        self._profiles_dir = Path(__file__).resolve().parent / "profiles"
        self._external_tools_dir = Path(self.config.external_tools_dir) if self.config.external_tools_dir else None
        self._external_profiles_dir = Path(self.config.external_profiles_dir) if self.config.external_profiles_dir else None
        self._audio_device_status: dict[str, Any] = {"configured": False, "reason": "not_initialized"}

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
                self._configure_audio_devices(mini)
                self._movement_manager = MovementManager(self._controller)
                self._movement_manager.start()
                if not self._no_camera and self.config.camera_enabled:
                    try:
                        from grumpyreachy.camera_worker import CameraWorker

                        frame_source = None
                        if mini is not None and hasattr(mini, "media") and mini.media is not None:
                            frame_source = mini.media.get_frame
                            self.log.info("Camera: using reachy_mini media manager as frame source")

                        self._camera_worker = CameraWorker(
                            device_index=self.config.camera_index,
                            frame_source=frame_source,
                        )
                        if self._camera_worker.start():
                            self.log.info("Camera worker started")
                        else:
                            self._camera_worker = None
                    except Exception:
                        self._camera_worker = None
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
        if self._movement_manager:
            self._movement_manager.stop()
            self._movement_manager = None
        if self._camera_worker:
            self._camera_worker.stop()
            self._camera_worker = None
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

    def get_audio_device_status(self) -> dict[str, Any]:
        """Return the latest resolved audio device selection status."""
        return dict(self._audio_device_status)

    def _configure_audio_devices(self, mini: Any | None) -> None:
        if mini is None:
            self._audio_device_status = {"configured": False, "reason": "robot_disconnected"}
            return

        media = getattr(mini, "media", None)
        audio = getattr(media, "audio", None) if media is not None else None
        if audio is None:
            self._audio_device_status = {"configured": False, "reason": "media_audio_unavailable"}
            return

        try:
            import sounddevice as sd
        except Exception:
            self._audio_device_status = {"configured": False, "reason": "sounddevice_unavailable"}
            return

        try:
            devices_raw = sd.query_devices()
        except Exception as exc:
            self._audio_device_status = {"configured": False, "reason": f"query_failed: {exc}"}
            return

        devices = [dict(item) for item in devices_raw]
        selected_input = getattr(audio, "_input_device_id", None)
        selected_output = getattr(audio, "_output_device_id", None)
        try:
            selected_input = int(selected_input) if selected_input is not None else None
        except (TypeError, ValueError):
            selected_input = None
        try:
            selected_output = int(selected_output) if selected_output is not None else None
        except (TypeError, ValueError):
            selected_output = None

        input_preferences = _parse_device_preferences(self.config.preferred_input_device)
        output_preferences = _parse_device_preferences(self.config.preferred_output_device)

        target_input = _find_device_index(
            devices,
            io_type="input",
            preferences=input_preferences,
        )
        target_output = _find_device_index(
            devices,
            io_type="output",
            preferences=output_preferences,
        )

        input_changed = False
        output_changed = False
        if target_input is not None and target_input != selected_input:
            setattr(audio, "_input_device_id", target_input)
            selected_input = target_input
            input_changed = True

        if target_output is not None and target_output != selected_output:
            setattr(audio, "_output_device_id", target_output)
            selected_output = target_output
            output_changed = True

        input_info = _device_info(devices, selected_input)
        output_info = _device_info(devices, selected_output)
        self._audio_device_status = {
            "configured": True,
            "input_preferences": input_preferences,
            "output_preferences": output_preferences,
            "input_changed": input_changed,
            "output_changed": output_changed,
            "selected_input": input_info,
            "selected_output": output_info,
        }
        self.log.info(
            "Audio selection: input=%s output=%s",
            (input_info or {}).get("name", "unknown"),
            (output_info or {}).get("name", "unknown"),
        )

    def get_tool_deps(self) -> ToolDependencies:
        """Build tool dependencies for the Realtime handler."""
        return ToolDependencies(
            robot_controller=self._controller,
            movement_manager=self._movement_manager,
            camera_worker=self._camera_worker,
            memory_bridge=self._memory_bridge,
            feedback_manager=self._feedback,
        )

    def get_profile_instructions_and_tools(self, profile_name: str) -> tuple[str, str | None]:
        """Load instructions and tools.txt for a profile. Uses external dir if set."""
        profiles_dir = self._external_profiles_dir if self._external_profiles_dir and (self._external_profiles_dir / profile_name).is_dir() else self._profiles_dir
        profile_dir = profiles_dir / profile_name
        instructions_path = profile_dir / "instructions.txt"
        tools_path = profile_dir / "tools.txt"
        instructions = instructions_path.read_text(encoding="utf-8") if instructions_path.is_file() else "You are a helpful Reachy Mini robot."
        tools_txt = tools_path.read_text(encoding="utf-8") if tools_path.is_file() else None
        from grumpyreachy.prompts import load_instructions

        prompts_dir = self._profiles_dir.parent / "prompts"
        instructions = load_instructions(instructions, prompts_dir)
        return instructions, tools_txt

    def create_realtime_handler(self, profile_name: str | None = None, on_transcript: Any = None) -> Any:
        """Create an OpenaiRealtimeHandler for the given profile (for use with fastrtc.Stream)."""
        from grumpyreachy.openai_realtime import OpenaiRealtimeHandler

        profile_name = profile_name or self.config.custom_profile or "default"
        if self.config.locked_profile:
            profile_name = self.config.locked_profile
        instructions, tools_txt = self.get_profile_instructions_and_tools(profile_name)
        profiles_dir = self._external_profiles_dir if self._external_profiles_dir and (self._external_profiles_dir / profile_name).is_dir() else self._profiles_dir
        tool_classes = get_tools_for_profile(profile_name, tools_txt, profiles_dir, self._external_tools_dir)
        deps = self.get_tool_deps()
        if not self.config.openai_api_key:
            raise ValueError("OPENAI_API_KEY required for conversation")
        return OpenaiRealtimeHandler(
            api_key=self.config.openai_api_key,
            model_name=self.config.model_name,
            instructions=instructions,
            tool_classes=tool_classes,
            tool_deps=deps,
            profiles_dir=profiles_dir,
            external_tools_dir=self._external_tools_dir,
            on_transcript=on_transcript,
        )

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
