"""Camera frame buffering and optional face/head tracking offset."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import numpy.typing as npt
import numpy as np

LOG = logging.getLogger("grumpyreachy.camera")

FrameSource = Callable[[], "npt.NDArray[np.uint8] | None"]


class CameraWorker:
    """
    Holds the latest camera frame for the camera tool and optional head-tracking.
    Can run a background capture loop or be fed frames from an external source.

    When *frame_source* is provided (e.g. ``mini.media.get_frame``), frames are
    pulled from that callable instead of opening a V4L2 device directly.  This
    avoids the exclusive-access conflict when reachy_mini already owns the camera.
    """

    def __init__(
        self,
        device_index: int = 0,
        width: int = 640,
        height: int = 480,
        frame_source: FrameSource | None = None,
    ):
        self._device_index = device_index
        self._width = width
        self._height = height
        self._frame_source = frame_source
        self._latest_frame: bytes | Any | None = None
        self._latest_t: float = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._capture: Any = None

    def start(self) -> bool:
        """Start capture loop if opencv is available."""
        if self._running:
            return True
        try:
            import cv2  # type: ignore[import-untyped]
        except ImportError:
            LOG.warning("opencv-python not installed; camera worker disabled")
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="grumpyreachy-camera", daemon=True)
        self._thread.start()
        LOG.info("CameraWorker started")
        return True

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._capture is not None:
            try:
                self._capture.release()
            except Exception:
                pass
            self._capture = None
        self._thread = None
        LOG.info("CameraWorker stopped")

    def _loop(self) -> None:
        try:
            import cv2  # type: ignore[import-untyped]
        except ImportError:
            return

        if self._frame_source is not None:
            self._loop_from_source(cv2)
        else:
            self._loop_from_device(cv2)

    def _loop_from_source(self, cv2: Any) -> None:
        """Pull frames from an external source (e.g. reachy_mini MediaManager)."""
        LOG.info("Using external frame source (reachy_mini media manager)")
        while self._running:
            try:
                frame = self._frame_source()
            except Exception:
                LOG.debug("frame_source raised; retrying", exc_info=True)
                time.sleep(0.1)
                continue
            if frame is not None:
                _, buf = cv2.imencode(".jpg", frame)
                with self._lock:
                    self._latest_frame = buf.tobytes()
                    self._latest_t = time.monotonic()
            time.sleep(0.05)

    def _loop_from_device(self, cv2: Any) -> None:
        """Open a V4L2 device directly (fallback when no external source)."""
        try:
            cv2.setLogLevel(3)  # LOG_LEVEL_ERROR — reduce V4L2 spam
        except Exception:
            pass
        indices_to_try = [self._device_index]
        if self._device_index == 0:
            indices_to_try.extend([2, 4])
        for idx in indices_to_try:
            self._capture = cv2.VideoCapture(idx)
            if not self._capture.isOpened():
                continue
            ret, frame = self._capture.read()
            if ret and frame is not None:
                break
            self._capture.release()
            self._capture = None
        if self._capture is None or not self._capture.isOpened():
            LOG.warning(
                "Could not open a valid camera (tried indices %s). "
                "Set GRUMPYREACHY_CAMERA_INDEX=2 or 4 if you have a different device, or use --no-camera.",
                indices_to_try,
            )
            return
        if self._device_index != indices_to_try[0]:
            LOG.info("Using camera index %s (index 0 was not a capture device)", indices_to_try[0])
        while self._running:
            ret, frame = self._capture.read()
            if ret and frame is not None:
                _, buf = cv2.imencode(".jpg", frame)
                with self._lock:
                    self._latest_frame = buf.tobytes()
                    self._latest_t = time.monotonic()
            time.sleep(0.05)

    def get_latest_frame(self) -> bytes | None:
        """Return latest JPEG bytes or None."""
        with self._lock:
            return self._latest_frame

    def feed_frame(self, data: bytes | Any) -> None:
        """Accept a frame from an external source."""
        with self._lock:
            self._latest_frame = data
            self._latest_t = time.monotonic()
