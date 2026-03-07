from __future__ import annotations

import os
import time

from api.backend.assistant.image_cache import RealtimeImageCache


def test_store_jpeg_writes_cache_file(tmp_path) -> None:
    cache = RealtimeImageCache(cache_dir=tmp_path, ttl_seconds=60)
    image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    item = cache.store_jpeg(image_bytes)

    assert item.path.is_file()
    assert item.byte_size == len(image_bytes)
    assert item.mime_type == "image/jpeg"
    assert item.path.read_bytes() == image_bytes
    assert item.expires_at > item.created_at


def test_purge_expired_removes_old_files_only(tmp_path) -> None:
    cache = RealtimeImageCache(cache_dir=tmp_path, ttl_seconds=10)
    old_file = tmp_path / "old.jpg"
    fresh_file = tmp_path / "fresh.jpg"
    old_file.write_bytes(b"old")
    fresh_file.write_bytes(b"fresh")

    now = time.time()
    os.utime(old_file, (now - 120.0, now - 120.0))
    os.utime(fresh_file, (now, now))

    removed = cache.purge_expired(now_monotonic=now)

    assert removed == 1
    assert not old_file.exists()
    assert fresh_file.exists()
