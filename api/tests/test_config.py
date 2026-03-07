from __future__ import annotations

from api.backend.assistant.realtime_service import OpenAIRealtimeService
from api.backend.config import ApiConfig


class _DummyTools:
    def definitions(self) -> list[dict[str, str]]:
        return []

    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "name": name, "arguments": arguments}


def test_api_config_defaults_include_talk_overlap_and_post_playback(monkeypatch) -> None:
    monkeypatch.delenv("GRUMPYREACHY_REALTIME_TALK_OVERLAP_MODE", raising=False)
    monkeypatch.delenv("GRUMPYREACHY_REALTIME_POST_PLAYBACK_HOLD_SECONDS", raising=False)
    monkeypatch.delenv("GRUMPYREACHY_REALTIME_VOICE_EFFECT_MODE", raising=False)

    cfg = ApiConfig.from_env()

    assert cfg.realtime_talk_overlap_mode == "strict_anti_loop"
    assert cfg.realtime_post_playback_hold_seconds == 0.9
    assert cfg.realtime_voice_effect_mode == "chipmunk"


def test_api_config_parses_talk_overlap_and_post_playback(monkeypatch) -> None:
    monkeypatch.setenv("GRUMPYREACHY_REALTIME_TALK_OVERLAP_MODE", "balanced")
    monkeypatch.setenv("GRUMPYREACHY_REALTIME_POST_PLAYBACK_HOLD_SECONDS", "1.5")
    monkeypatch.setenv("GRUMPYREACHY_REALTIME_VOICE_EFFECT_MODE", "none")

    cfg = ApiConfig.from_env()

    assert cfg.realtime_talk_overlap_mode == "balanced"
    assert cfg.realtime_post_playback_hold_seconds == 1.5
    assert cfg.realtime_voice_effect_mode == "none"


def test_invalid_overlap_mode_falls_back_to_strict_anti_loop() -> None:
    service = OpenAIRealtimeService(
        api_key="test",
        base_url="",
        ca_bundle="",
        model="gpt-realtime",
        input_gain=1.0,
        output_gain=1.0,
        mic_suppression_seconds=0.35,
        talk_overlap_mode="not-a-real-mode",
        post_playback_hold_seconds=0.9,
        voice_effect_mode="unknown",
        aec_enabled=True,
        aec_delay_ms=120,
        aec_strength=0.75,
        aec_corr_threshold=0.12,
        instructions="test instructions",
        tools=_DummyTools(),
        on_event=lambda *_: None,
        get_robot_mini=lambda: None,
    )

    status = service.status()
    assert status["talk_overlap_mode"] == "strict_anti_loop"
    assert status["voice_effect_mode"] == "chipmunk"
