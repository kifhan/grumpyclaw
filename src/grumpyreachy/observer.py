"""Observation loop and event schema."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass(frozen=True)
class ObservationEvent:
    event_id: str
    created_at: str
    summary: str
    source: str = "reachy_observer"

    @classmethod
    def new(cls, summary: str, source: str = "reachy_observer") -> "ObservationEvent":
        return cls(
            event_id=f"obs-{uuid.uuid4().hex[:12]}",
            created_at=datetime.now(timezone.utc).isoformat(),
            summary=summary.strip(),
            source=source,
        )


class Observer:
    """Produces compact observation events on a fixed schedule."""

    def __init__(
        self,
        interval_seconds: int,
        capture: Callable[[], str | None],
    ):
        self.interval_seconds = max(5, int(interval_seconds))
        self.capture = capture
        self._last_summary: str = ""

    def run_loop(
        self,
        stop_event: threading.Event,
        on_event: Callable[[ObservationEvent], None],
    ) -> None:
        # Emit one observation at startup so heartbeat has immediate context.
        self._emit_once(on_event)
        while not stop_event.wait(timeout=self.interval_seconds):
            self._emit_once(on_event)

    def _emit_once(self, on_event: Callable[[ObservationEvent], None]) -> None:
        summary = (self.capture() or "").strip()
        if not summary:
            return
        # Simple de-duplication for periodic observer noise.
        if summary == self._last_summary:
            return
        self._last_summary = summary
        on_event(ObservationEvent.new(summary=summary))
