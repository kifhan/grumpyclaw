from __future__ import annotations

from grumpyreachy.app import _resolve_reachy_media_backend


def test_media_backend_uses_default_when_camera_enabled() -> None:
    backend = _resolve_reachy_media_backend(camera_enabled=True, no_camera=False)
    assert backend == "default"


def test_media_backend_uses_audio_only_when_camera_disabled_in_config() -> None:
    backend = _resolve_reachy_media_backend(camera_enabled=False, no_camera=False)
    assert backend == "default_no_video"


def test_media_backend_uses_audio_only_when_no_camera_flag_set() -> None:
    backend = _resolve_reachy_media_backend(camera_enabled=True, no_camera=True)
    assert backend == "default_no_video"
