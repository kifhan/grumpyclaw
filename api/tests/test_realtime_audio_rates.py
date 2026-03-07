from __future__ import annotations

import asyncio
import base64

import numpy as np
import pytest

from api.backend.assistant.realtime_service import (
    _FarEndReferenceBuffer,
    OpenAIRealtimeService,
    _apply_voice_effect,
    _is_input_suppressed,
    _normalize_voice_effect_mode,
    _reference_echo_suppression,
    _resolve_output_sample_rate,
)


class _MediaWithRate:
    def __init__(self, rate: int):
        self._rate = rate

    def get_output_audio_samplerate(self) -> int:
        return self._rate


class _MediaWithBadRate:
    def get_output_audio_samplerate(self) -> int:
        return -1


def test_resolve_output_sample_rate_uses_media_rate() -> None:
    assert _resolve_output_sample_rate(_MediaWithRate(48000)) == 48000


def test_resolve_output_sample_rate_falls_back_on_invalid_rate() -> None:
    assert _resolve_output_sample_rate(_MediaWithBadRate(), default_rate=16000) == 16000


def test_resolve_output_sample_rate_falls_back_when_method_missing() -> None:
    assert _resolve_output_sample_rate(object(), default_rate=16000) == 16000


def test_is_input_suppressed_window() -> None:
    assert _is_input_suppressed(1.0, 1.5) is True
    assert _is_input_suppressed(1.5, 1.5) is False
    assert _is_input_suppressed(1.0, 0.0) is False


def test_far_end_reference_buffer_respects_delay_and_fifo() -> None:
    buf = _FarEndReferenceBuffer(delay_samples=3)
    buf.append(np.array([11, 12, 13], dtype=np.int16))
    assert np.array_equal(buf.consume(4), np.array([0, 0, 0, 11], dtype=np.int16))
    assert np.array_equal(buf.consume(4), np.array([12, 13, 0, 0], dtype=np.int16))


def test_reference_echo_suppression_reduces_correlated_far_end_energy() -> None:
    steps = np.linspace(0.0, 2.0 * np.pi, num=240, endpoint=False, dtype=np.float32)
    far = (np.sin(steps * 2.0) * 12000.0).astype(np.int16)
    near_voice = (np.sin(steps * 7.0) * 3500.0).astype(np.int16)
    near = np.clip(near_voice.astype(np.float32) + (far.astype(np.float32) * 0.7), -32768.0, 32767.0).astype(np.int16)

    cleaned = _reference_echo_suppression(
        near,
        far,
        strength=0.8,
        corr_threshold=0.05,
    )

    before = abs(float(np.dot(near.astype(np.float32), far.astype(np.float32))))
    after = abs(float(np.dot(cleaned.astype(np.float32), far.astype(np.float32))))
    assert after < before


def test_normalize_voice_effect_mode_defaults_to_chipmunk() -> None:
    assert _normalize_voice_effect_mode("chipmunk") == "chipmunk"
    assert _normalize_voice_effect_mode("none") == "none"
    assert _normalize_voice_effect_mode("unknown") == "chipmunk"


def test_apply_voice_effect_chipmunk_changes_shape_and_values() -> None:
    src = np.arange(-1200, 1200, dtype=np.int16)
    out = _apply_voice_effect(src, mode="chipmunk")

    assert out.dtype == np.int16
    assert out.size < src.size
    assert not np.array_equal(out, src[: out.size])


class _DummyTools:
    def definitions(self) -> list[dict[str, str]]:
        return []

    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "name": name, "arguments": arguments}


class _DummyMedia:
    def __init__(self) -> None:
        self.started = False
        self.pushed: list[np.ndarray] = []

    def start_playing(self) -> None:
        self.started = True

    def push_audio_sample(self, sample: np.ndarray) -> None:
        self.pushed.append(sample)

    def get_output_audio_samplerate(self) -> int:
        return 24000


class _DummyMini:
    def __init__(self) -> None:
        self.media = _DummyMedia()


def _build_service(
    *,
    mini: _DummyMini,
    talk_overlap_mode: str,
    mic_suppression_seconds: float = 0.35,
    voice_effect_mode: str = "none",
) -> OpenAIRealtimeService:
    return OpenAIRealtimeService(
        api_key="test",
        base_url="",
        ca_bundle="",
        model="gpt-realtime",
        input_gain=1.0,
        output_gain=1.0,
        mic_suppression_seconds=mic_suppression_seconds,
        talk_overlap_mode=talk_overlap_mode,
        post_playback_hold_seconds=0.9,
        voice_effect_mode=voice_effect_mode,
        aec_enabled=True,
        aec_delay_ms=120,
        aec_strength=0.75,
        aec_corr_threshold=0.12,
        instructions="test instructions",
        tools=_DummyTools(),
        on_event=lambda *_: None,
        get_robot_mini=lambda: mini,
    )


def test_play_robot_audio_strict_mode_extends_by_chunk_and_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    mini = _DummyMini()
    service = _build_service(mini=mini, talk_overlap_mode="strict_anti_loop")
    monkeypatch.setattr("api.backend.assistant.realtime_service.time.monotonic", lambda: 10.0)
    # 2400 samples at 24kHz == 0.1s chunk.
    delta = base64.b64encode(np.zeros(2400, dtype=np.int16).tobytes()).decode("utf-8")

    service._play_robot_audio(delta)

    assert service._mic_suppressed_until == pytest.approx(11.0)
    assert mini.media.started is True
    assert len(mini.media.pushed) == 1
    assert service._aec_reference.consume(4).size == 4


def test_play_robot_audio_balanced_mode_uses_fixed_window(monkeypatch: pytest.MonkeyPatch) -> None:
    mini = _DummyMini()
    service = _build_service(mini=mini, talk_overlap_mode="balanced")
    monkeypatch.setattr("api.backend.assistant.realtime_service.time.monotonic", lambda: 10.0)
    delta = base64.b64encode(np.zeros(2400, dtype=np.int16).tobytes()).decode("utf-8")

    service._play_robot_audio(delta)

    assert service._mic_suppressed_until == pytest.approx(10.35)


def test_handle_event_audio_done_applies_strict_tail_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    mini = _DummyMini()
    service = _build_service(mini=mini, talk_overlap_mode="strict_anti_loop")
    service._mic_suppressed_until = 0.0
    monkeypatch.setattr("api.backend.assistant.realtime_service.time.monotonic", lambda: 12.0)

    event = type("Evt", (), {"type": "response.done"})()
    asyncio.run(service._handle_event(object(), event))

    assert service._mic_suppressed_until == pytest.approx(12.9)


def test_start_clears_stale_last_user_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    mini = _DummyMini()
    service = _build_service(mini=mini, talk_overlap_mode="strict_anti_loop")
    service._last_user_transcript = "stale from previous session"

    class _FakeThread:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            del args, kwargs
            self._alive = False

        def start(self) -> None:
            self._alive = False

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout: float | None = None) -> None:
            del timeout

    monkeypatch.setattr("api.backend.assistant.realtime_service.threading.Thread", _FakeThread)

    service.start()

    assert service._last_user_transcript == ""
