"""Move types for the primary queue: dance, emotion, goto pose, breathing."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("grumpyreachy.moves")


@dataclass
class PoseState:
    """Head and antenna target state for one timestep."""

    head_pos: dict[str, float] = field(default_factory=dict)  # joint names -> position
    antenna_pos: list[float] = field(default_factory=lambda: [0.0, 0.0])
    look_at: tuple[float, float, float] | None = None  # (x, y, z) world


class Move(ABC):
    """One item in the primary move queue; can be sampled over time."""

    @abstractmethod
    def sample(self, t: float) -> PoseState | None:
        """Return pose at time t (seconds since start), or None if move finished."""
        ...


class GotoPoseMove(Move):
    """Static pose for head direction (left/right/up/down/front)."""

    _LOOK_AT_MAP = {
        "front": (0.35, 0.0, 0.1),
        "left": (0.35, 0.25, 0.1),
        "right": (0.35, -0.25, 0.1),
        "up": (0.35, 0.0, 0.25),
        "down": (0.35, 0.0, -0.05),
    }

    def __init__(self, direction: str, duration: float = 0.5):
        self.direction = direction.lower()
        self.duration = duration
        self._start: float | None = None

    def sample(self, t: float) -> PoseState | None:
        if self._start is None:
            self._start = t
        elapsed = t - self._start
        if elapsed >= self.duration:
            return None
        xyz = self._LOOK_AT_MAP.get(self.direction, self._LOOK_AT_MAP["front"])
        return PoseState(look_at=xyz)


class BreathingMove(Move):
    """Idle breathing: gentle antenna oscillation."""

    def __init__(self, period: float = 2.0, amplitude: float = 0.08):
        self.period = period
        self.amplitude = amplitude
        self._start: float | None = None

    def sample(self, t: float) -> PoseState | None:
        if self._start is None:
            self._start = t
        import math

        elapsed = t - self._start
        phase = (elapsed / self.period) * 2 * math.pi
        a = self.amplitude * math.sin(phase)
        return PoseState(antenna_pos=[a, -a])


class DanceMove(Move):
    """Play a dance from the library; duration from move or fixed."""

    def __init__(self, robot_controller: Any, move_name: str, duration: float = 10.0):
        self._controller = robot_controller
        self.move_name = move_name
        self.duration = duration
        self._start: float | None = None
        self._played = False

    def sample(self, t: float) -> PoseState | None:
        if self._start is None:
            self._start = t
        elapsed = t - self._start
        if not self._played and self._controller and hasattr(self._controller, "_play_builtin_motion"):
            candidates = (self.move_name.lower(),)
            if self._controller._play_builtin_motion(candidates, initial_goto_duration=0.25):
                self._played = True
        if elapsed >= self.duration:
            return None
        return PoseState()


class EmotionMove(Move):
    """Play an emotion clip from the library."""

    def __init__(self, robot_controller: Any, emotion_name: str, duration: float = 5.0):
        self._controller = robot_controller
        self.emotion_name = emotion_name
        self.duration = duration
        self._start: float | None = None
        self._played = False

    def sample(self, t: float) -> PoseState | None:
        if self._start is None:
            self._start = t
        elapsed = t - self._start
        if not self._played and self._controller and hasattr(self._controller, "_play_builtin_motion"):
            candidates = (
                self.emotion_name.lower(),
                "neutral",
                "happy",
                "sad",
                "curious",
            )
            if self._controller._play_builtin_motion(candidates, initial_goto_duration=0.2):
                self._played = True
        if elapsed >= self.duration:
            return None
        return PoseState()
