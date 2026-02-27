"""Safe robot primitives for Reachy Mini."""

from __future__ import annotations

import logging
import time
from typing import Any

try:
    from reachy_mini.motion.recorded_move import RecordedMoves
except Exception:  # pragma: no cover - optional dependency in no-robot mode
    RecordedMoves = None  # type: ignore[assignment]


def _is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, ConnectionError):
        return True
    return "Lost connection" in str(exc) or "ConnectionError" in type(exc).__name__


class RobotController:
    """Thin wrapper around ReachyMini with guarded operations."""

    def __init__(self, mini: Any | None = None):
        self._mini = mini
        self._log = logging.getLogger("grumpyreachy.robot")
        self._connection_lost = False
        self._last_connection_error_log: float = 0.0
        self._builtin_motion_index: dict[str, tuple[str, str]] | None = None
        self._builtin_motion_catalogs: dict[str, Any] = {}
        self._builtin_motion_load_attempted = False

    _MOTION_DATASETS = {
        "emotions": "pollen-robotics/reachy-mini-emotions-library",
        "dances": "pollen-robotics/reachy-mini-dances-library",
    }

    _MOTION_CANDIDATES = {
        "nod": ("nod", "yes", "affirmative"),
        "attention": ("attention", "curious", "listening", "interested"),
        "success": ("success", "happy", "celebrate", "joy"),
        "error": ("error", "sad", "angry", "confused"),
        "neutral": ("neutral", "idle", "calm", "rest"),
    }

    @property
    def connected(self) -> bool:
        return self._mini is not None and not self._connection_lost

    def look_at(self, x: float, y: float, z: float, duration: float = 1.0) -> None:
        if not self._mini or self._connection_lost:
            return
        try:
            self._mini.look_at_world(x=x, y=y, z=z, duration=duration)
        except Exception as e:
            if _is_connection_error(e):
                self._connection_lost = True
                self._log.warning("Robot connection lost (look_at)")
            else:
                self._log.exception("look_at failed")

    def nod(self) -> None:
        if not self._mini or self._connection_lost:
            return
        if self._play_builtin_motion(self._MOTION_CANDIDATES["nod"], initial_goto_duration=0.25):
            return
        try:
            self._mini.look_at_world(x=0.35, y=0.0, z=-0.05, duration=0.25)
            self._mini.look_at_world(x=0.35, y=0.0, z=0.15, duration=0.25)
            self._mini.look_at_world(x=0.35, y=0.0, z=0.05, duration=0.25)
        except Exception as e:
            if _is_connection_error(e):
                self._connection_lost = True
                self._log.warning("Robot connection lost (nod)")
            else:
                self._log.exception("nod failed")

    def antenna_feedback(self, state: str = "attention") -> None:
        if not self._mini or self._connection_lost:
            return
        patterns = {
            "attention": [0.15, -0.15],
            "success": [0.4, -0.4],
            "error": [-0.25, 0.25],
            "neutral": [0.0, 0.0],
        }
        if self._play_builtin_motion(
            self._MOTION_CANDIDATES.get(state, self._MOTION_CANDIDATES["neutral"]),
            initial_goto_duration=0.2,
        ):
            return
        target = patterns.get(state, patterns["neutral"])
        try:
            self._mini.set_target_antenna_joint_positions(target)
        except Exception as e:
            if _is_connection_error(e):
                self._connection_lost = True
                self._log.warning("Robot connection lost (antenna_feedback)")
            else:
                self._log.exception("antenna_feedback failed for state=%s", state)

    def speak(self, text: str) -> None:
        # Reachy Mini text-to-speech backend may vary by deployment.
        self._log.info("speak: %s", text)

    def neutral_pose(self) -> None:
        self.antenna_feedback("neutral")

    def set_target_antenna(self, positions: list[float]) -> None:
        """Set antenna joint positions directly (for 100Hz control loop)."""
        if not self._mini or self._connection_lost or len(positions) < 2:
            return
        try:
            self._mini.set_target_antenna_joint_positions(positions)
        except Exception as e:
            if _is_connection_error(e):
                self._connection_lost = True
                now = time.monotonic()
                if now - self._last_connection_error_log >= 10.0:
                    self._last_connection_error_log = now
                    self._log.warning("Robot connection lost; antenna commands paused until restart")
            # else: other exceptions are unexpected in the control loop; log at debug only
            elif self._log.isEnabledFor(logging.DEBUG):
                self._log.debug("set_target_antenna failed: %s", e)

    def _play_builtin_motion(
        self, candidates: tuple[str, ...], initial_goto_duration: float = 0.25
    ) -> bool:
        if not self._mini or not hasattr(self._mini, "play_move"):
            return False

        match = self._find_builtin_motion(candidates)
        if match is None:
            return False

        dataset_key, move_name = match
        catalog = self._builtin_motion_catalogs.get(dataset_key)
        if catalog is None:
            return False

        try:
            self._mini.play_move(
                catalog.get(move_name),
                initial_goto_duration=initial_goto_duration,
            )
            return True
        except Exception:
            self._log.exception("Built-in motion playback failed: %s/%s", dataset_key, move_name)
            return False

    def _find_builtin_motion(self, candidates: tuple[str, ...]) -> tuple[str, str] | None:
        if not self._ensure_builtin_motions_loaded():
            return None
        assert self._builtin_motion_index is not None

        lowered_candidates = [candidate.lower() for candidate in candidates]

        for candidate in lowered_candidates:
            if candidate in self._builtin_motion_index:
                return self._builtin_motion_index[candidate]

        for name_lower, motion_ref in self._builtin_motion_index.items():
            for candidate in lowered_candidates:
                if candidate in name_lower:
                    return motion_ref
        return None

    def _ensure_builtin_motions_loaded(self) -> bool:
        if self._builtin_motion_index is not None:
            return True
        if self._builtin_motion_load_attempted:
            return False

        self._builtin_motion_load_attempted = True
        if RecordedMoves is None:
            self._log.debug("RecordedMoves unavailable; skipping built-in motion loading")
            return False

        try:
            index: dict[str, tuple[str, str]] = {}
            for dataset_key, dataset_name in self._MOTION_DATASETS.items():
                catalog = RecordedMoves(dataset_name)
                self._builtin_motion_catalogs[dataset_key] = catalog
                for move_name in catalog.list_moves():
                    index[move_name.lower()] = (dataset_key, move_name)
            self._builtin_motion_index = index
            if not index:
                self._log.warning("Built-in motion datasets loaded but empty")
                return False
            self._log.info("Loaded %s built-in motions from Reachy datasets", len(index))
            return True
        except Exception:
            self._log.exception("Failed to load built-in Reachy motions")
            return False
