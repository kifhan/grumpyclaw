from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config/public")
def config_public(request: Request) -> dict[str, object]:
    cfg = request.app.state.container.config
    return {
        "auth": "disabled_dev_only",
        "cors_origin": cfg.cors_origin,
        "robot_rate_limit_seconds": cfg.robot_rate_limit_seconds,
        "robot_speak_confirm_threshold": cfg.robot_speak_confirm_threshold,
        "openai_text_model": cfg.openai_text_model,
        "openai_realtime_model": cfg.openai_realtime_model,
        "heartbeat_interval_seconds": cfg.heartbeat_interval_seconds,
        "realtime_input_gain": cfg.realtime_input_gain,
        "realtime_output_gain": cfg.realtime_output_gain,
        "realtime_mic_suppression_seconds": cfg.realtime_mic_suppression_seconds,
        "realtime_talk_overlap_mode": cfg.realtime_talk_overlap_mode,
        "realtime_post_playback_hold_seconds": cfg.realtime_post_playback_hold_seconds,
        "realtime_voice_effect_mode": cfg.realtime_voice_effect_mode,
        "realtime_aec_enabled": cfg.realtime_aec_enabled,
        "realtime_aec_delay_ms": cfg.realtime_aec_delay_ms,
        "realtime_aec_strength": cfg.realtime_aec_strength,
        "realtime_aec_corr_threshold": cfg.realtime_aec_corr_threshold,
        "realtime_image_cache_dir": cfg.realtime_image_cache_dir,
        "realtime_image_cache_ttl_seconds": cfg.realtime_image_cache_ttl_seconds,
    }
