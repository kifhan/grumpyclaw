"""MovementManager: 100Hz control loop, primary queue + secondary offsets."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from grumpyreachy.dance_emotion_moves import (
    BreathingMove,
    DanceMove,
    EmotionMove,
    GotoPoseMove,
    Move,
    PoseState,
)

LOG = logging.getLogger("grumpyreachy.moves")

IDLE_TIMEOUT_S = 8.0
CONTROL_HZ = 100
CONTROL_DT = 1.0 / CONTROL_HZ


def _add_antenna(a: list[float], b: list[float]) -> list[float]:
    if len(a) < 2:
        return list(b) if len(b) >= 2 else [0.0, 0.0]
    if len(b) < 2:
        return list(a)
    return [a[0] + b[0], a[1] + b[1]]


class MovementManager:
    """
    Runs a 100Hz control loop: primary move queue (dances, emotions, goto, breathing)
    plus secondary offsets (head tracking, speech wobble). Fuses poses and sends to robot.
    """

    def __init__(self, robot_controller: Any):
        self._robot = robot_controller
        self._primary_queue: queue.Queue[Move] = queue.Queue()
        self._current_move: Move | None = None
        self._current_move_start: float = 0.0
        self._head_tracking_enabled: bool = False
        self._head_tracking_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._speech_wobble_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._listening_mode: bool = False
        self._last_activity: float = time.monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0: float = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._control_loop, name="grumpyreachy-moves", daemon=True)
        self._thread.start()
        LOG.info("MovementManager started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        LOG.info("MovementManager stopped")

    def queue_head_direction(self, direction: str, duration: float = 0.5) -> None:
        self._primary_queue.put(GotoPoseMove(direction=direction, duration=duration))
        self._last_activity = time.monotonic()

    def queue_dance(self, name: str, duration: float = 10.0) -> None:
        self._primary_queue.put(DanceMove(robot_controller=self._robot, move_name=name, duration=duration))
        self._last_activity = time.monotonic()

    def queue_emotion(self, name: str, duration: float = 5.0) -> None:
        self._primary_queue.put(EmotionMove(robot_controller=self._robot, emotion_name=name, duration=duration))
        self._last_activity = time.monotonic()

    def clear_dance_queue(self) -> None:
        cleared = 0
        new_queue: queue.Queue[Move] = queue.Queue()
        try:
            while True:
                m = self._primary_queue.get_nowait()
                if isinstance(m, DanceMove):
                    cleared += 1
                else:
                    new_queue.put(m)
        except queue.Empty:
            pass
        self._primary_queue = new_queue
        if cleared:
            LOG.debug("Cleared %s dance(s) from queue", cleared)

    def clear_emotion_queue(self) -> None:
        cleared = 0
        new_queue: queue.Queue[Move] = queue.Queue()
        try:
            while True:
                m = self._primary_queue.get_nowait()
                if isinstance(m, EmotionMove):
                    cleared += 1
                else:
                    new_queue.put(m)
        except queue.Empty:
            pass
        self._primary_queue = new_queue
        if cleared:
            LOG.debug("Cleared %s emotion(s) from queue", cleared)

    def set_head_tracking_enabled(self, enabled: bool) -> None:
        self._head_tracking_enabled = enabled
        if not enabled:
            self._head_tracking_offset = (0.0, 0.0, 0.0)

    def set_head_tracking_offset(self, dx: float, dy: float, dz: float) -> None:
        self._head_tracking_offset = (dx, dy, dz)

    def set_speech_wobble_offset(self, dx: float, dy: float, dz: float) -> None:
        self._speech_wobble_offset = (dx, dy, dz)

    def set_listening_mode(self, listening: bool) -> None:
        self._listening_mode = listening

    def _get_primary_pose(self, t: float) -> PoseState | None:
        if self._current_move is None:
            try:
                self._current_move = self._primary_queue.get_nowait()
                self._current_move_start = t
            except queue.Empty:
                # Idle: inject breathing after timeout
                if time.monotonic() - self._last_activity > IDLE_TIMEOUT_S:
                    self._current_move = BreathingMove(period=2.0, amplitude=0.08)
                    self._current_move_start = t
                return PoseState(antenna_pos=[0.0, 0.0]) if self._listening_mode else None

        if self._current_move is None:
            return None
        pose = self._current_move.sample(t - self._current_move_start)
        if pose is None:
            self._current_move = None
            return self._get_primary_pose(t)
        return pose

    def _combine_pose(self, primary: PoseState | None) -> None:
        if not self._robot or not self._robot.connected:
            return
        look_at = primary.look_at if primary else None
        antenna = list(primary.antenna_pos) if primary and primary.antenna_pos else [0.0, 0.0]

        if self._head_tracking_enabled and (self._head_tracking_offset[0] or self._head_tracking_offset[1] or self._head_tracking_offset[2]):
            x, y, z = 0.35, 0.0, 0.1
            x += self._head_tracking_offset[0]
            y += self._head_tracking_offset[1]
            z += self._head_tracking_offset[2]
            look_at = (x, y, z)
        elif look_at:
            x, y, z = look_at
            x += self._speech_wobble_offset[0]
            y += self._speech_wobble_offset[1]
            z += self._speech_wobble_offset[2]
            look_at = (x, y, z)

        if look_at:
            try:
                self._robot.look_at(look_at[0], look_at[1], look_at[2], duration=CONTROL_DT * 2)
            except Exception:
                pass
        if not self._listening_mode:
            self._robot.set_target_antenna(antenna)

    def _control_loop(self) -> None:
        while not self._stop.is_set():
            t = time.monotonic() - self._t0
            primary = self._get_primary_pose(t)
            self._combine_pose(primary)
            self._stop.wait(timeout=CONTROL_DT)
