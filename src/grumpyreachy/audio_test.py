"""
Test Reachy Mini's speaker and microphone via mini.media (Reachy SDK).
Used by the Device Test API to verify robot audio hardware.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import numpy as np

LOG = logging.getLogger("grumpyreachy.audio_test")

# Reachy Mini media uses 16 kHz, float32
MEDIA_SAMPLE_RATE = 16000
TONE_HZ = 440
TONE_DURATION_S = 0.4
RECORD_DURATION_S = 1.0
TONE_GAIN = float(os.environ.get("GRUMPYREACHY_TEST_TONE_GAIN", "0.35"))


def run_robot_speaker_test(mini: Any) -> dict[str, Any]:
    """
    Play a short test tone through the robot's speaker (mini.media).
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    if mini is None:
        return {"ok": False, "error": "No robot connection"}
    media = getattr(mini, "media", None)
    if media is None:
        return {"ok": False, "error": "Robot has no media API (mini.media)"}
    start_playing = getattr(media, "start_playing", None)
    push_audio_sample = getattr(media, "push_audio_sample", None)
    stop_playing = getattr(media, "stop_playing", None)
    if not all([start_playing, push_audio_sample, stop_playing]):
        return {"ok": False, "error": "Robot media missing start_playing/push_audio_sample/stop_playing"}
    try:
        start_playing()
        # Generate 0.4 s of 440 Hz sine, float32, 16 kHz. Shape (samples,) or (samples, 1).
        n = int(MEDIA_SAMPLE_RATE * TONE_DURATION_S)
        t = np.arange(n, dtype=np.float32) / MEDIA_SAMPLE_RATE
        tone = (TONE_GAIN * np.sin(2 * np.pi * TONE_HZ * t)).astype(np.float32)
        # SDK may expect (samples, 1) or (samples, 2)
        if tone.ndim == 1:
            tone = tone[:, np.newaxis]
        chunk_size = 1024
        for i in range(0, len(tone), chunk_size):
            chunk = tone[i : i + chunk_size]
            push_audio_sample(chunk)
        time.sleep(TONE_DURATION_S + 0.1)
        stop_playing()
        return {"ok": True, "message": f"Played {TONE_HZ} Hz tone for {TONE_DURATION_S}s gain={TONE_GAIN}"}
    except Exception as e:
        LOG.exception("Robot speaker test failed")
        try:
            stop_playing()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}


def run_robot_mic_test(mini: Any) -> dict[str, Any]:
    """
    Record from the robot's microphone for ~1 s and return level summary.
    Returns {"ok": True, "level": float, "samples": int} or {"ok": False, "error": "..."}.
    """
    if mini is None:
        return {"ok": False, "error": "No robot connection"}
    media = getattr(mini, "media", None)
    if media is None:
        return {"ok": False, "error": "Robot has no media API (mini.media)"}
    start_recording = getattr(media, "start_recording", None)
    get_audio_sample = getattr(media, "get_audio_sample", None)
    stop_recording = getattr(media, "stop_recording", None)
    if not all([start_recording, get_audio_sample, stop_recording]):
        return {"ok": False, "error": "Robot media missing start_recording/get_audio_sample/stop_recording"}
    try:
        start_recording()
        deadline = time.monotonic() + RECORD_DURATION_S
        chunks: list[np.ndarray] = []
        while time.monotonic() < deadline:
            try:
                sample = get_audio_sample()
            except Exception:
                break
            if sample is not None and sample.size > 0:
                chunks.append(np.asarray(sample))
            time.sleep(0.02)
        stop_recording()
        if not chunks:
            return {"ok": True, "level": 0.0, "samples": 0, "message": "No samples (silence or device busy)"}
        data = np.concatenate(chunks, axis=0)
        rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
        return {"ok": True, "level": round(rms, 6), "samples": int(data.size), "message": f"Recorded {data.size} samples, RMS={rms:.4f}"}
    except Exception as e:
        LOG.exception("Robot mic test failed")
        try:
            stop_recording()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
