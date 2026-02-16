"""Persist grumpyreachy observations into grumpyclaw memory."""

from __future__ import annotations

from grumpyclaw.memory.indexer import Indexer
from grumpyreachy.observer import ObservationEvent


class MemoryBridge:
    """Bridge from observation events to grumpyclaw memory index."""

    SOURCE_TYPE = "reachy_observation"

    def __init__(self, indexer: Indexer | None = None):
        self.indexer = indexer or Indexer()

    def store_observation(self, event: ObservationEvent) -> int:
        doc = {
            "id": event.event_id,
            "title": f"Reachy observation {event.created_at}",
            "text": event.summary,
        }
        return self.indexer.index_documents([doc], source_type=self.SOURCE_TYPE)
