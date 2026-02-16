"""Safe robot primitives for Reachy Mini."""

from __future__ import annotations

import logging
from typing import Any


class RobotController:
    """Thin wrapper around ReachyMini with guarded operations."""

    def __init__(self, mini: Any | None = None):
        self._mini = mini
        self._log = logging.getLogger("grumpyreachy.robot")

    @property
    def connected(self) -> bool:
        return self._mini is not None

    def look_at(self, x: float, y: float, z: float, duration: float = 1.0) -> None:
        if not self._mini:
            self._log.info("look_at skipped (robot not connected): (%s, %s, %s)", x, y, z)
            return
        try:
            self._mini.look_at_world([x, y, z], duration=duration)
        except Exception:
            self._log.exception("look_at failed")

    def nod(self) -> None:
        if not self._mini:
            self._log.info("nod skipped (robot not connected)")
            return
        try:
            self._mini.look_at_world([0.35, 0.0, -0.05], duration=0.25)
            self._mini.look_at_world([0.35, 0.0, 0.15], duration=0.25)
            self._mini.look_at_world([0.35, 0.0, 0.05], duration=0.25)
        except Exception:
            self._log.exception("nod failed")

    def antenna_feedback(self, state: str = "attention") -> None:
        if not self._mini:
            self._log.info("antenna_feedback skipped (robot not connected): %s", state)
            return
        patterns = {
            "attention": [0.15, -0.15],
            "success": [0.4, -0.4],
            "error": [-0.25, 0.25],
            "neutral": [0.0, 0.0],
        }
        target = patterns.get(state, patterns["neutral"])
        try:
            self._mini.set_target_antenna_joint_positions(target)
        except Exception:
            self._log.exception("antenna_feedback failed for state=%s", state)

    def speak(self, text: str) -> None:
        # Reachy Mini text-to-speech backend may vary by deployment.
        self._log.info("speak: %s", text)

    def neutral_pose(self) -> None:
        self.antenna_feedback("neutral")
