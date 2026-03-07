from __future__ import annotations

import base64
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(frozen=True)
class CachedImage:
    path: Path
    byte_size: int
    mime_type: str
    created_at: str
    expires_at: str


class RealtimeImageCache:
    """Ephemeral file cache for realtime camera snapshots."""

    def __init__(self, *, cache_dir: str | Path, ttl_seconds: int):
        self._cache_dir = Path(cache_dir)
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._lock = threading.Lock()

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def purge_expired(self, *, now_monotonic: float | None = None) -> int:
        now = time.time() if now_monotonic is None else float(now_monotonic)
        cutoff = now - float(self._ttl_seconds)
        removed = 0
        with self._lock:
            if not self._cache_dir.is_dir():
                return 0
            for path in self._cache_dir.glob("*.jpg"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                        removed += 1
                except FileNotFoundError:
                    continue
        return removed

    def store_jpeg(self, image_bytes: bytes) -> CachedImage:
        if not image_bytes:
            raise ValueError("image_bytes must not be empty")
        with self._lock:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            # Opportunistic cleanup on each write.
            self._purge_expired_unlocked(now=time.time())
            created_dt = datetime.now(timezone.utc)
            expires_dt = created_dt + timedelta(seconds=self._ttl_seconds)
            filename = f"{uuid.uuid4().hex}.jpg"
            path = self._cache_dir / filename
            path.write_bytes(image_bytes)
            return CachedImage(
                path=path,
                byte_size=len(image_bytes),
                mime_type="image/jpeg",
                created_at=created_dt.isoformat(),
                expires_at=expires_dt.isoformat(),
            )

    @staticmethod
    def to_data_url(image_bytes: bytes, *, mime_type: str = "image/jpeg") -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    def _purge_expired_unlocked(self, *, now: float) -> int:
        cutoff = now - float(self._ttl_seconds)
        removed = 0
        if not self._cache_dir.is_dir():
            return 0
        for path in self._cache_dir.glob("*.jpg"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except FileNotFoundError:
                continue
        return removed
