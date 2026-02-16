from __future__ import annotations

import json
import queue
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Generator


@dataclass(frozen=True)
class StreamEvent:
    event: str
    data: dict[str, Any]


class EventBus:
    """Thread-safe pub/sub used by SSE endpoints."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[str, list[queue.Queue[StreamEvent]]] = defaultdict(list)

    def subscribe(self, channel: str) -> queue.Queue[StreamEvent]:
        q: queue.Queue[StreamEvent] = queue.Queue(maxsize=500)
        with self._lock:
            self._subs[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: queue.Queue[StreamEvent]) -> None:
        with self._lock:
            items = self._subs.get(channel)
            if not items:
                return
            self._subs[channel] = [item for item in items if item is not q]

    def publish(self, channel: str, event: StreamEvent) -> None:
        with self._lock:
            targets = list(self._subs.get(channel, []))
        for q in targets:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


def sse_stream(channel: str, bus: EventBus) -> Generator[str, None, None]:
    q = bus.subscribe(channel)
    try:
        while True:
            try:
                evt = q.get(timeout=15.0)
                payload = json.dumps(evt.data, ensure_ascii=True)
                yield f"event: {evt.event}\ndata: {payload}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    finally:
        bus.unsubscribe(channel, q)
