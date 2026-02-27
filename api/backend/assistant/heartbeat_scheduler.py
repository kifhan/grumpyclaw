from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable


class HeartbeatScheduler:
    """In-process heartbeat scheduler with manual trigger support."""

    def __init__(self, interval_seconds: int, run_once: Callable[[str], dict[str, Any]]):
        self._interval_seconds = max(30, int(interval_seconds))
        self._run_once = run_once
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_run_at: str | None = None
        self._last_result: dict[str, Any] | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="assistant-heartbeat", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def run_now(self) -> dict[str, Any]:
        result = self._safe_run("manual")
        with self._lock:
            self._last_result = result
            self._last_run_at = datetime.now(timezone.utc).isoformat()
        return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            running = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
            return {
                "running": running,
                "interval_seconds": self._interval_seconds,
                "last_run_at": self._last_run_at,
                "last_result": self._last_result,
            }

    def _loop(self) -> None:
        while not self._stop.wait(timeout=float(self._interval_seconds)):
            result = self._safe_run("scheduled")
            with self._lock:
                self._last_result = result
                self._last_run_at = datetime.now(timezone.utc).isoformat()

    def _safe_run(self, trigger: str) -> dict[str, Any]:
        try:
            return self._run_once(trigger)
        except Exception as exc:
            return {
                "status": "HEARTBEAT_OK",
                "message": "",
                "trigger": trigger,
                "error": str(exc),
            }
