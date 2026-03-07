from __future__ import annotations

import asyncio
import base64
import collections
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
import numpy as np
from openai import AsyncOpenAI

from ..openai_tls import build_websocket_connection_options, resolve_tls_verify
from .tools import ToolDispatcher

LOG = logging.getLogger("grumpyadmin.assistant.realtime")

_TALK_OVERLAP_MODES = {"strict_anti_loop", "balanced", "barge_in"}
_VOICE_EFFECT_MODES = {"none", "chipmunk"}


def _normalize_talk_overlap_mode(raw: str) -> str:
    mode = str(raw or "").strip().lower()
    if mode in _TALK_OVERLAP_MODES:
        return mode
    return "strict_anti_loop"


def _normalize_voice_effect_mode(raw: str) -> str:
    mode = str(raw or "").strip().lower()
    if mode in _VOICE_EFFECT_MODES:
        return mode
    return "chipmunk"


def _resample_int16(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample mono int16 audio with linear interpolation."""
    if src_rate == dst_rate or samples.size == 0:
        return samples.astype(np.int16, copy=False)
    src = samples.astype(np.float32)
    src_x = np.arange(src.shape[0], dtype=np.float32)
    dst_len = int(round(src.shape[0] * float(dst_rate) / float(src_rate)))
    if dst_len <= 1:
        return samples[:1].astype(np.int16, copy=False)
    dst_x = np.linspace(0.0, float(src.shape[0] - 1), num=dst_len, dtype=np.float32)
    out = np.interp(dst_x, src_x, src)
    out = np.clip(out, -32768.0, 32767.0).astype(np.int16)
    return out


def _chipmunk_robotize_int16(samples: np.ndarray) -> np.ndarray:
    """
    Apply a chipmunk-like robot voice effect.

    This deliberately prioritizes timbre over strict duration preservation:
    1) speed/pitch-up via resampling
    2) light saturation
    3) coarse quantization for synthetic robot texture
    """
    if samples.size == 0:
        return samples.astype(np.int16, copy=False)

    # >1.0 means faster/higher pitch ("chipmunk-like").
    pitch_factor = 1.35
    pitched = _resample_int16(
        samples,
        src_rate=24000,
        dst_rate=max(6000, int(round(24000.0 / pitch_factor))),
    )
    if pitched.size == 0:
        return pitched

    wave = pitched.astype(np.float32) / 32768.0
    wave = np.tanh(wave * 1.65)
    quant_levels = 96.0
    wave = np.round(wave * quant_levels) / quant_levels
    return np.clip(wave * 32767.0, -32768.0, 32767.0).astype(np.int16)


def _apply_voice_effect(samples: np.ndarray, *, mode: str) -> np.ndarray:
    if samples.size == 0:
        return samples.astype(np.int16, copy=False)
    if mode == "chipmunk":
        return _chipmunk_robotize_int16(samples)
    return samples.astype(np.int16, copy=False)


def _resolve_output_sample_rate(media: Any, default_rate: int = 16000) -> int:
    get_output_audio_samplerate = getattr(media, "get_output_audio_samplerate", None)
    if callable(get_output_audio_samplerate):
        try:
            candidate = int(get_output_audio_samplerate())
            if candidate > 0:
                return candidate
        except Exception:
            pass
    return default_rate


def _is_input_suppressed(now_monotonic: float, suppress_until_monotonic: float) -> bool:
    return suppress_until_monotonic > 0.0 and now_monotonic < suppress_until_monotonic


def _reference_echo_suppression(
    near_end: np.ndarray,
    far_end: np.ndarray,
    *,
    strength: float,
    corr_threshold: float,
) -> np.ndarray:
    """
    Lightweight reference-based echo suppression.

    This is not a full adaptive AEC, but it removes strongly correlated
    far-end energy from the near-end microphone signal.
    """
    if near_end.size == 0 or far_end.size == 0:
        return near_end.astype(np.int16, copy=False)

    near = near_end.astype(np.float32)
    far = far_end.astype(np.float32)

    near_energy = float(np.dot(near, near))
    far_energy = float(np.dot(far, far))
    if near_energy <= 1e-6 or far_energy <= 1e-6:
        return near_end.astype(np.int16, copy=False)

    cross = float(np.dot(near, far))
    corr = abs(cross) / ((near_energy * far_energy) ** 0.5 + 1e-6)
    if corr < corr_threshold:
        return near_end.astype(np.int16, copy=False)

    gain = cross / (far_energy + 1e-6)
    gain = max(-4.0, min(4.0, gain))
    cleaned = near - (far * gain * strength)
    return np.clip(cleaned, -32768.0, 32767.0).astype(np.int16)


class _FarEndReferenceBuffer:
    """FIFO int16 sample buffer used as far-end reference for AEC."""

    def __init__(self, delay_samples: int = 0):
        self._chunks: collections.deque[np.ndarray] = collections.deque()
        self._offset = 0
        self._buffered = 0
        self.reset(delay_samples=delay_samples)

    def reset(self, *, delay_samples: int = 0) -> None:
        self._chunks.clear()
        self._offset = 0
        self._buffered = 0
        if delay_samples > 0:
            self.append(np.zeros(delay_samples, dtype=np.int16))

    def append(self, samples: np.ndarray) -> None:
        arr = np.asarray(samples, dtype=np.int16).reshape(-1)
        if arr.size == 0:
            return
        self._chunks.append(arr)
        self._buffered += int(arr.size)

    def consume(self, length: int) -> np.ndarray:
        if length <= 0:
            return np.zeros(0, dtype=np.int16)
        out = np.zeros(length, dtype=np.int16)
        pos = 0
        while pos < length and self._chunks:
            head = self._chunks[0]
            available = head.size - self._offset
            take = min(available, length - pos)
            start = self._offset
            end = start + take
            out[pos : pos + take] = head[start:end]
            pos += take
            self._buffered -= take
            if end >= head.size:
                self._chunks.popleft()
                self._offset = 0
            else:
                self._offset = end
        return out


def _strip_image_data_url(value: Any) -> tuple[Any, str | None]:
    """Return a copy of value without image_data_url and the first removed data URL."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        found: str | None = None
        for key, item in value.items():
            if key == "image_data_url":
                if found is None and isinstance(item, str):
                    found = item
                continue
            cleaned, child_found = _strip_image_data_url(item)
            out[key] = cleaned
            if found is None and child_found:
                found = child_found
        return out, found
    if isinstance(value, list):
        out_list: list[Any] = []
        found: str | None = None
        for item in value:
            cleaned, child_found = _strip_image_data_url(item)
            out_list.append(cleaned)
            if found is None and child_found:
                found = child_found
        return out_list, found
    return value, None


class OpenAIRealtimeService:
    """Server-side OpenAI Realtime websocket runtime."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        ca_bundle: str,
        model: str,
        input_gain: float,
        output_gain: float,
        mic_suppression_seconds: float,
        talk_overlap_mode: str,
        post_playback_hold_seconds: float,
        voice_effect_mode: str,
        aec_enabled: bool,
        aec_delay_ms: int,
        aec_strength: float,
        aec_corr_threshold: float,
        instructions: str,
        tools: ToolDispatcher,
        on_event: Callable[[str, dict[str, Any]], None],
        get_robot_mini: Callable[[], Any | None],
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._ca_bundle = ca_bundle
        self._model = model
        self._input_gain = max(0.1, float(input_gain))
        self._output_gain = max(0.1, float(output_gain))
        self._mic_suppression_seconds = max(0.0, float(mic_suppression_seconds))
        self._talk_overlap_mode = _normalize_talk_overlap_mode(talk_overlap_mode)
        self._post_playback_hold_seconds = max(0.0, float(post_playback_hold_seconds))
        self._voice_effect_mode = _normalize_voice_effect_mode(voice_effect_mode)
        self._aec_enabled = bool(aec_enabled)
        self._aec_delay_ms = max(0, int(aec_delay_ms))
        self._aec_strength = max(0.0, min(1.0, float(aec_strength)))
        self._aec_corr_threshold = max(0.0, min(1.0, float(aec_corr_threshold)))
        self._instructions = str(instructions or "").strip()
        self._tools = tools
        self._on_event = on_event
        self._get_robot_mini = get_robot_mini

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._started_at: str | None = None
        self._connected = False
        self._last_error: str | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection: Any = None
        self._mic_task: asyncio.Task[Any] | None = None
        self._speaker_started = False
        self._mic_suppressed_until = 0.0
        self._aec_reference = _FarEndReferenceBuffer(delay_samples=self._aec_delay_samples())
        self._dispatched_tool_call_ids: set[str] = set()
        self._last_user_transcript: str = ""
        self._recent_robot_actions: collections.deque[str] = collections.deque(maxlen=6)
        self._last_user_activity_monotonic = 0.0
        self._last_assistant_activity_monotonic = 0.0

    def start(self, instructions: str | None = None) -> dict[str, Any]:
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY is required for realtime")
        purge_runtime_cache = getattr(self._tools, "purge_runtime_cache", None)
        if callable(purge_runtime_cache):
            try:
                purge_runtime_cache()
            except Exception:
                LOG.debug("realtime image cache purge failed", exc_info=True)
        with self._lock:
            if instructions is not None:
                self._instructions = str(instructions or "").strip()
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            self._dispatched_tool_call_ids.clear()
            self._recent_robot_actions.clear()
            self._last_user_transcript = ""
            self._last_user_activity_monotonic = 0.0
            self._last_assistant_activity_monotonic = 0.0
            self._reset_far_end_reference()
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._last_error = None
            self._thread = threading.Thread(target=self._thread_main, name="assistant-realtime", daemon=True)
            self._thread.start()
        self._emit_status()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        loop = self._loop
        conn = self._connection
        if loop and conn:
            try:
                asyncio.run_coroutine_threadsafe(conn.close(), loop)
            except Exception:
                pass
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=4.0)
        self._stop_robot_playback()
        self._mic_suppressed_until = 0.0
        self._last_user_transcript = ""
        self._last_user_activity_monotonic = 0.0
        self._last_assistant_activity_monotonic = 0.0
        self._reset_far_end_reference()
        self._connected = False
        self._emit_status()
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            thread_alive = bool(self._thread and self._thread.is_alive())
            return {
                "running": thread_alive and not self._stop.is_set(),
                "thread_alive": thread_alive,
                "connected": self._connected,
                "conversation_active": self.conversation_active(),
                "model": self._model,
                "aec_enabled": self._aec_enabled,
                "talk_overlap_mode": self._talk_overlap_mode,
                "voice_effect_mode": self._voice_effect_mode,
                "post_playback_hold_seconds": self._post_playback_hold_seconds,
                "started_at": self._started_at,
                "last_error": self._last_error,
            }

    def _aec_delay_samples(self) -> int:
        # Realtime wire format runs at 24 kHz.
        return int(round((self._aec_delay_ms / 1000.0) * 24000.0))

    def _reset_far_end_reference(self) -> None:
        self._aec_reference.reset(delay_samples=self._aec_delay_samples())

    def _extend_mic_suppression_for_output_chunk(
        self,
        *,
        now_monotonic: float,
        chunk_samples_24k: int,
    ) -> None:
        if self._talk_overlap_mode == "barge_in":
            return
        if self._talk_overlap_mode == "balanced":
            if self._mic_suppression_seconds > 0.0:
                self._mic_suppressed_until = max(
                    self._mic_suppressed_until,
                    now_monotonic + self._mic_suppression_seconds,
                )
            return

        chunk_duration_seconds = max(0.0, float(chunk_samples_24k) / 24000.0)
        tail_seconds = max(self._mic_suppression_seconds, self._post_playback_hold_seconds)
        if chunk_duration_seconds <= 0.0 and tail_seconds <= 0.0:
            return
        self._mic_suppressed_until = max(
            self._mic_suppressed_until,
            now_monotonic + chunk_duration_seconds + tail_seconds,
        )

    def _apply_post_playback_tail_hold(self, *, now_monotonic: float | None = None) -> None:
        if self._talk_overlap_mode != "strict_anti_loop":
            return
        if self._post_playback_hold_seconds <= 0.0:
            return
        now = time.monotonic() if now_monotonic is None else now_monotonic
        self._mic_suppressed_until = max(
            self._mic_suppressed_until,
            now + self._post_playback_hold_seconds,
        )

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            LOG.exception("Realtime thread crashed")
            self._last_error = str(exc)
            self._connected = False
            self._emit_status()

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        verify = resolve_tls_verify(self._ca_bundle)
        websocket_connection_options = build_websocket_connection_options(verify)

        try:
            async with httpx.AsyncClient(verify=verify) as http_client:
                kwargs["http_client"] = http_client
                client = AsyncOpenAI(**kwargs)
                async with client.realtime.connect(
                    model=self._model,
                    websocket_connection_options=websocket_connection_options,
                ) as conn:
                    self._connection = conn
                    self._connected = True
                    self._emit_status()
                    interrupt_response = self._talk_overlap_mode != "strict_anti_loop"

                    await conn.session.update(
                        session={
                            "type": "realtime",
                            "instructions": self._instructions,
                            "output_modalities": ["audio"],
                            "audio": {
                                "input": {
                                    "format": {"type": "audio/pcm", "rate": 24000},
                                    "turn_detection": {
                                        "type": "server_vad",
                                        "create_response": True,
                                        "interrupt_response": interrupt_response,
                                    },
                                    "transcription": {"model": "whisper-1"},
                                },
                                "output": {
                                    "format": {"type": "audio/pcm", "rate": 24000},
                                },
                            },
                            "tools": self._tools.definitions(),
                            "tool_choice": "auto",
                        }
                    )

                    self._mic_task = asyncio.create_task(self._pump_robot_microphone(conn))
                    async for event in conn:
                        if self._stop.is_set():
                            break
                        await self._handle_event(conn, event)
        except Exception as exc:
            self._last_error = str(exc)
            self._on_event(
                "assistant.realtime.status",
                {
                    "state": "error",
                    "error": str(exc),
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )
            LOG.exception("Realtime connection error")
        finally:
            if self._mic_task:
                self._mic_task.cancel()
                self._mic_task = None
            self._stop_robot_playback()
            self._mic_suppressed_until = 0.0
            self._last_user_transcript = ""
            self._last_user_activity_monotonic = 0.0
            self._last_assistant_activity_monotonic = 0.0
            self._reset_far_end_reference()
            self._connection = None
            self._connected = False
            self._emit_status()

    async def _handle_event(self, conn: Any, event: Any) -> None:
        etype = str(getattr(event, "type", "") or "")

        if etype in {"conversation.item.input_audio_transcription.delta"}:
            delta = str(getattr(event, "delta", "") or "")
            if delta:
                self._last_user_activity_monotonic = time.monotonic()
                self._on_event(
                    "assistant.realtime.transcript.delta",
                    {
                        "role": "user",
                        "delta": delta,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
            return

        if etype == "conversation.item.input_audio_transcription.completed":
            transcript = str(getattr(event, "transcript", "") or "")
            if transcript:
                self._last_user_transcript = transcript
                self._last_user_activity_monotonic = time.monotonic()
                self._on_event(
                    "assistant.realtime.transcript",
                    {
                        "role": "user",
                        "content": transcript,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
            return

        if etype in {
            "response.audio_transcript.delta",
            "response.output_audio_transcript.delta",
            "response.text.delta",
            "response.output_text.delta",
        }:
            delta = str(getattr(event, "delta", "") or "")
            if delta:
                self._last_assistant_activity_monotonic = time.monotonic()
                self._on_event(
                    "assistant.realtime.transcript.delta",
                    {
                        "role": "assistant",
                        "delta": delta,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
            return

        if etype in {"response.audio_transcript.done", "response.output_audio_transcript.done"}:
            transcript = str(getattr(event, "transcript", "") or "")
            if transcript:
                self._last_assistant_activity_monotonic = time.monotonic()
                self._on_event(
                    "assistant.realtime.transcript",
                    {
                        "role": "assistant",
                        "content": transcript,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
            return

        if etype in {"response.audio.delta", "response.output_audio.delta"}:
            delta = getattr(event, "delta", None)
            if delta:
                self._last_assistant_activity_monotonic = time.monotonic()
                self._play_robot_audio(str(delta))
            return

        if etype in {"response.audio.done", "response.output_audio.done", "response.done"}:
            self._apply_post_playback_tail_hold()
            return

        if etype in {"response.text.done", "response.output_text.done"}:
            text = str(getattr(event, "text", "") or "")
            if text:
                self._last_assistant_activity_monotonic = time.monotonic()
                self._on_event(
                    "assistant.realtime.transcript",
                    {
                        "role": "assistant",
                        "content": text,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
            return

        if etype == "response.function_call_arguments.done":
            await self._dispatch_tool_call(
                conn=conn,
                name=str(getattr(event, "name", "") or ""),
                arguments=getattr(event, "arguments", None),
                call_id=str(getattr(event, "call_id", "") or ""),
                source_event=etype,
            )
            return

        # Compatibility: function calls may arrive as completed output items.
        if etype == "response.output_item.done":
            item = getattr(event, "item", None)
            if item and str(getattr(item, "type", "")) == "function_call":
                item_status = str(getattr(item, "status", "") or "").strip().lower()
                if item_status and item_status != "completed":
                    return
                await self._dispatch_tool_call(
                    conn=conn,
                    name=str(getattr(item, "name", "") or ""),
                    arguments=getattr(item, "arguments", None),
                    call_id=str(getattr(item, "call_id", "") or getattr(item, "id", "") or ""),
                    source_event=etype,
                )
            return

        # Compatibility fallback for older event shape.
        if etype == "conversation.item.added":
            item = getattr(event, "item", None)
            if item and str(getattr(item, "type", "")) == "function_call":
                await self._dispatch_tool_call(
                    conn=conn,
                    name=str(getattr(item, "name", "") or ""),
                    arguments=getattr(item, "arguments", None),
                    call_id=str(getattr(item, "call_id", "") or getattr(item, "id", "") or ""),
                    source_event=etype,
                )
            return

        if etype == "error":
            message = str(getattr(event, "error", "") or "")
            self._on_event(
                "assistant.realtime.status",
                {
                    "state": "error",
                    "error": message,
                    "ts": datetime.now(timezone.utc).isoformat(),
                },
            )

    async def _dispatch_tool_call(
        self,
        conn: Any,
        name: str,
        arguments: Any,
        call_id: str,
        source_event: str | None = None,
    ) -> None:
        if not call_id:
            return
        if call_id in self._dispatched_tool_call_ids:
            return
        parsed_any: Any
        if isinstance(arguments, dict):
            parsed_any = arguments
        elif isinstance(arguments, str):
            stripped_arguments = arguments.strip()
            # Provisional function-call events may be emitted for interrupted/incomplete responses.
            if source_event == "response.function_call_arguments.done" and not stripped_arguments:
                return
            try:
                parsed_any = json.loads(stripped_arguments) if stripped_arguments else {}
            except json.JSONDecodeError:
                if source_event == "response.function_call_arguments.done":
                    return
                parsed_any = {}
        elif arguments is None:
            if source_event == "response.function_call_arguments.done":
                return
            parsed_any = {}
        elif hasattr(arguments, "model_dump") and callable(getattr(arguments, "model_dump")):
            try:
                parsed_any = arguments.model_dump()
            except Exception:
                parsed_any = {}
        else:
            parsed_any = {}
        parsed = parsed_any if isinstance(parsed_any, dict) else {}

        if name == "robot_action":
            parsed = dict(parsed)
            action = str(parsed.get("action", "")).strip()
            user_text = self._last_user_transcript
            catalog = self._get_motion_catalog()
            emotion_intent = self._is_emotion_intent(self._last_user_transcript)
            dance_intent = self._is_dance_intent(self._last_user_transcript)
            movement_intent = self._is_movement_intent(self._last_user_transcript)
            weak_actions = {"", "nod", "look_at", "antenna_feedback"}

            if dance_intent and action in weak_actions:
                parsed["action"] = "dance"
                parsed["name"] = self._select_dance_name(
                    preferred=str(parsed.get("name", "")).strip() or user_text,
                    available=catalog.get("dances", []),
                )
                action = "dance"
            elif emotion_intent and action in weak_actions:
                canonical = self._canonical_emotion_label(user_text)
                parsed["action"] = "play_emotion"
                parsed["name"] = self._select_emotion_name(
                    preferred=canonical,
                    available=catalog.get("emotions", []),
                )
                action = "play_emotion"
            elif source_event != "response.function_call_arguments.done" and not action:
                inferred_action, inferred_name = self._infer_robot_action_from_user_text(user_text)
                parsed["action"] = inferred_action
                if inferred_name and not str(parsed.get("name", "")).strip():
                    parsed["name"] = inferred_name
                action = inferred_action

            if source_event == "response.function_call_arguments.done" and not action:
                return

            # Break repeated weak-action loops unless the user explicitly asked for nodding.
            if (
                action in {"nod", "look_at", "antenna_feedback"}
                and self._is_repeating_weak_action(action)
                and not self._is_explicit_nod_request(user_text)
            ):
                if dance_intent or movement_intent:
                    parsed["action"] = "dance"
                    parsed["name"] = self._select_dance_name(
                        preferred=str(parsed.get("name", "")).strip() or user_text,
                        available=catalog.get("dances", []),
                    )
                    action = "dance"
                else:
                    parsed["action"] = "play_emotion"
                    parsed["name"] = self._select_emotion_name(
                        preferred=self._canonical_emotion_label(user_text),
                        available=catalog.get("emotions", []),
                    )
                    action = "play_emotion"

            if action == "play_emotion":
                preferred_raw = str(parsed.get("name", "")).strip()
                preferred = preferred_raw or self._canonical_emotion_label(user_text)
                parsed["name"] = self._select_emotion_name(
                    preferred=preferred,
                    available=catalog.get("emotions", []),
                )
            elif action == "dance":
                parsed["name"] = self._select_dance_name(
                    preferred=str(parsed.get("name", "")).strip() or user_text,
                    available=catalog.get("dances", []),
                )

            self._recent_robot_actions.append(action)

        self._dispatched_tool_call_ids.add(call_id)
        raw_result = self._tools.execute(name, parsed)
        result, image_data_url = _strip_image_data_url(raw_result)

        image_injection_error: str | None = None
        if image_data_url:
            try:
                await conn.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": image_data_url,
                            }
                        ],
                    }
                )
            except Exception as exc:
                image_injection_error = str(exc)
                if isinstance(result, dict):
                    if isinstance(result.get("result"), dict):
                        result_result = dict(result["result"])
                        result_result["image_injection_error"] = image_injection_error
                        result = dict(result)
                        result["result"] = result_result
                    else:
                        result = dict(result)
                        result["image_injection_error"] = image_injection_error
                else:
                    result = {
                        "ok": False,
                        "error": "failed to inject image context",
                        "image_injection_error": image_injection_error,
                    }

        self._on_event(
            "assistant.tool",
            {
                "call_id": call_id,
                "name": name,
                "arguments": parsed,
                "result": result,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )

        await conn.conversation.item.create(
            item={
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result, ensure_ascii=True),
            }
        )
        await conn.response.create()

    @staticmethod
    def _infer_robot_action_from_user_text(user_text: str) -> tuple[str, str | None]:
        text = str(user_text or "").strip().lower()
        if not text:
            return ("nod", None)

        emotion_name: str | None = None
        emotion_hints: tuple[tuple[str, str], ...] = (
            ("happy", "happy"),
            ("joy", "happy"),
            ("glad", "happy"),
            ("excited", "happy"),
            ("sad", "sad"),
            ("upset", "sad"),
            ("angry", "angry"),
            ("mad", "angry"),
            ("curious", "curious"),
        )
        for keyword, mapped in emotion_hints:
            if keyword in text:
                emotion_name = mapped
                break

        if any(
            keyword in text
            for keyword in (
                "emotion",
                "emotions",
                "feeling",
                "feelings",
                "express",
                "happy",
                "sad",
                "angry",
                "curious",
            )
        ):
            return ("play_emotion", emotion_name or "happy")

        if any(keyword in text for keyword in ("dance", "dancing", "celebrate", "party")):
            return ("dance", "default")

        if any(keyword in text for keyword in ("nod", "yes")):
            return ("nod", None)

        return ("nod", None)

    @staticmethod
    def _is_emotion_intent(user_text: str) -> bool:
        text = str(user_text or "").strip().lower()
        if not text:
            return False
        return any(
            keyword in text
            for keyword in (
                "emotion",
                "emotions",
                "feeling",
                "feelings",
                "mood",
                "happy",
                "joy",
                "joyful",
                "exciting",
                "excited",
                "sad",
                "upset",
                "angry",
                "mad",
                "curious",
                "wondering",
                "calm",
                "neutral",
            )
        )

    @staticmethod
    def _is_dance_intent(user_text: str) -> bool:
        text = str(user_text or "").strip().lower()
        if not text:
            return False
        return any(
            keyword in text
            for keyword in (
                "dance",
                "dances",
                "dancing",
                "groove",
                "party",
                "celebrate",
                "celebration",
                "chicken",
            )
        )

    @staticmethod
    def _is_movement_intent(user_text: str) -> bool:
        text = str(user_text or "").strip().lower()
        if not text:
            return False
        return any(
            keyword in text
            for keyword in (
                "move",
                "moves",
                "motion",
                "motions",
                "gesture",
                "gestures",
            )
        )

    @staticmethod
    def _is_explicit_nod_request(user_text: str) -> bool:
        text = str(user_text or "").strip().lower()
        if not text:
            return False
        return any(keyword in text for keyword in ("nod", "nodding", "say yes", "yes motion"))

    def _is_repeating_weak_action(self, action: str) -> bool:
        if action not in {"nod", "look_at", "antenna_feedback"}:
            return False
        if len(self._recent_robot_actions) < 2:
            return False
        return all(name == action for name in list(self._recent_robot_actions)[-2:])

    @staticmethod
    def _canonical_emotion_label(user_text: str) -> str:
        text = str(user_text or "").strip().lower()
        if not text:
            return "happy"

        groups: tuple[tuple[tuple[str, ...], str], ...] = (
            (("exciting", "excited", "joyful", "joy", "happy", "glad"), "happy"),
            (("calm", "neutral", "relaxed"), "neutral"),
            (("sad", "upset", "down"), "sad"),
            (("curious", "wondering", "interested"), "curious"),
            (("angry", "mad", "furious"), "angry"),
        )
        for keywords, canonical in groups:
            if any(keyword in text for keyword in keywords):
                return canonical
        return "happy"

    @staticmethod
    def _select_emotion_name(preferred: str, available: list[str] | tuple[str, ...] | None) -> str:
        normalized_available = [str(name).strip() for name in (available or []) if str(name).strip()]
        normalized_available = sorted(set(normalized_available), key=str.lower)

        preferred_label = OpenAIRealtimeService._canonical_emotion_label(preferred)
        if not normalized_available:
            return preferred_label or "happy"

        lower_to_original = {name.lower(): name for name in normalized_available}
        if preferred.lower() in lower_to_original:
            return lower_to_original[preferred.lower()]
        if preferred_label in lower_to_original:
            return lower_to_original[preferred_label]

        keyword_groups: dict[str, tuple[str, ...]] = {
            "happy": ("happy", "joy", "smile", "excit", "enthusias", "cheer", "celebrat"),
            "neutral": ("neutral", "calm", "idle", "relax", "rest", "attentive"),
            "sad": ("sad", "upset", "down", "blue"),
            "curious": ("curious", "wonder", "interest", "listen", "attention"),
            "angry": ("angry", "mad", "furious", "annoy", "error"),
        }

        for keyword in keyword_groups.get(preferred_label, ()):
            for available_name in normalized_available:
                if keyword in available_name.lower():
                    return available_name

        if "happy" in lower_to_original:
            return lower_to_original["happy"]
        return normalized_available[0]

    @staticmethod
    def _select_dance_name(preferred: str, available: list[str] | tuple[str, ...] | None) -> str:
        normalized_available = [str(name).strip() for name in (available or []) if str(name).strip()]
        normalized_available = sorted(set(normalized_available), key=str.lower)
        if not normalized_available:
            return "default"

        lower_to_original = {name.lower(): name for name in normalized_available}
        preferred_lower = str(preferred or "").strip().lower()
        if preferred_lower and preferred_lower in lower_to_original:
            return lower_to_original[preferred_lower]

        for token in preferred_lower.replace("-", " ").replace("_", " ").split():
            if len(token) < 3:
                continue
            for name in normalized_available:
                if token in name.lower():
                    return name

        if "default" in lower_to_original:
            return lower_to_original["default"]
        return normalized_available[0]

    def _get_motion_catalog(self) -> dict[str, Any]:
        robot_service = getattr(self._tools, "_robot_service", None)
        getter = getattr(robot_service, "get_motion_catalog", None)
        if not callable(getter):
            return {"available": False, "emotions": [], "dances": []}
        try:
            raw = getter()
        except Exception:
            return {"available": False, "emotions": [], "dances": []}
        if not isinstance(raw, dict):
            return {"available": False, "emotions": [], "dances": []}

        emotions = [str(name).strip() for name in raw.get("emotions", []) if str(name).strip()]
        dances = [str(name).strip() for name in raw.get("dances", []) if str(name).strip()]
        return {
            "available": bool(raw.get("available")) and bool(emotions or dances),
            "emotions": emotions,
            "dances": dances,
        }

    async def _pump_robot_microphone(self, conn: Any) -> None:
        while not self._stop.is_set():
            mini = self._get_robot_mini()
            media = getattr(mini, "media", None) if mini else None
            if not media:
                await asyncio.sleep(0.25)
                continue

            get_audio_sample = getattr(media, "get_audio_sample", None)
            start_recording = getattr(media, "start_recording", None)
            stop_recording = getattr(media, "stop_recording", None)
            get_input_audio_samplerate = getattr(media, "get_input_audio_samplerate", None)
            if not get_audio_sample or not start_recording or not stop_recording:
                await asyncio.sleep(0.25)
                continue

            input_sample_rate = 16000
            if get_input_audio_samplerate:
                try:
                    candidate = int(get_input_audio_samplerate())
                    if candidate > 0:
                        input_sample_rate = candidate
                except Exception:
                    LOG.debug("unable to read robot input sample rate", exc_info=True)

            try:
                start_recording()
                while not self._stop.is_set():
                    sample = get_audio_sample()
                    if sample is None:
                        await asyncio.sleep(0.02)
                        continue
                    arr = np.asarray(sample)
                    if arr.size == 0:
                        await asyncio.sleep(0.02)
                        continue
                    if _is_input_suppressed(time.monotonic(), self._mic_suppressed_until):
                        await asyncio.sleep(0.02)
                        continue
                    if arr.ndim > 1:
                        # ReSpeaker returns multi-channel input; mix down to mono for Realtime.
                        arr = np.mean(arr.astype(np.float32), axis=1)
                    else:
                        arr = arr.reshape(-1)
                    if arr.dtype != np.int16:
                        if np.issubdtype(arr.dtype, np.integer):
                            arr = np.clip(arr.astype(np.int32), -32768, 32767).astype(np.int16)
                        else:
                            arr = np.clip(arr.astype(np.float32), -1.0, 1.0)
                            arr = (arr * 32767.0).astype(np.int16)
                    if self._input_gain != 1.0:
                        boosted = arr.astype(np.float32) * self._input_gain
                        arr = np.clip(boosted, -32768.0, 32767.0).astype(np.int16)
                    # Realtime PCM input expects 24kHz mono.
                    arr = _resample_int16(arr, src_rate=input_sample_rate, dst_rate=24000)
                    if self._aec_enabled:
                        far_reference = self._aec_reference.consume(arr.size)
                        arr = _reference_echo_suppression(
                            arr,
                            far_reference,
                            strength=self._aec_strength,
                            corr_threshold=self._aec_corr_threshold,
                        )
                    b64 = base64.b64encode(arr.tobytes()).decode("utf-8")
                    await conn.input_audio_buffer.append(audio=b64)
                    await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                return
            except Exception:
                LOG.debug("robot microphone bridge unavailable", exc_info=True)
                await asyncio.sleep(0.5)
            finally:
                try:
                    stop_recording()
                except Exception:
                    pass

    def _play_robot_audio(self, delta_b64: str) -> None:
        mini = self._get_robot_mini()
        media = getattr(mini, "media", None) if mini else None
        if not media:
            return
        push_audio_sample = getattr(media, "push_audio_sample", None)
        start_playing = getattr(media, "start_playing", None)
        if not push_audio_sample or not start_playing:
            return

        try:
            if not self._speaker_started and hasattr(media, "start_playing"):
                start_playing()
                self._speaker_started = True
            raw = base64.b64decode(delta_b64)
            int16_audio = np.frombuffer(raw, dtype=np.int16)
            if int16_audio.size == 0:
                return
            int16_audio = _apply_voice_effect(int16_audio, mode=self._voice_effect_mode)
            if int16_audio.size == 0:
                return
            self._extend_mic_suppression_for_output_chunk(
                now_monotonic=time.monotonic(),
                chunk_samples_24k=int(int16_audio.size),
            )
            if self._aec_enabled:
                self._aec_reference.append(int16_audio)
            # Realtime output PCM is 24kHz. Match active output device sample rate.
            output_sample_rate = _resolve_output_sample_rate(media)
            int16_audio = _resample_int16(int16_audio, src_rate=24000, dst_rate=output_sample_rate)
            float_audio = int16_audio.astype(np.float32) / 32768.0
            if self._output_gain != 1.0:
                float_audio = np.clip(float_audio * self._output_gain, -1.0, 1.0)
            float_audio = float_audio.reshape(-1, 1)
            push_audio_sample(float_audio)
        except Exception:
            self._speaker_started = False
            LOG.debug("robot speaker bridge unavailable", exc_info=True)

    def _stop_robot_playback(self) -> None:
        mini = self._get_robot_mini()
        media = getattr(mini, "media", None) if mini else None
        stop_playing = getattr(media, "stop_playing", None) if media else None
        if not stop_playing:
            self._speaker_started = False
            return
        try:
            stop_playing()
        except Exception:
            LOG.debug("robot stop_playing failed", exc_info=True)
        finally:
            self._speaker_started = False

    def _emit_status(self) -> None:
        payload = {
            "state": "running" if self._connected else "stopped",
            "status": self.status(),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._on_event("assistant.realtime.status", payload)

    def conversation_active(self) -> bool:
        now = time.monotonic()
        return bool(
            self._connected
            and (
                self._speaker_started
                or (self._mic_suppressed_until > now)
                or ((now - self._last_user_activity_monotonic) < 5.0 if self._last_user_activity_monotonic else False)
                or (
                    (now - self._last_assistant_activity_monotonic) < 5.0
                    if self._last_assistant_activity_monotonic
                    else False
                )
            )
        )
