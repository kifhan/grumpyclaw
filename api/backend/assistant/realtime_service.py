from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
from openai import AsyncOpenAI

from .tools import ToolDispatcher

LOG = logging.getLogger("grumpyadmin.assistant.realtime")


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


class OpenAIRealtimeService:
    """Server-side OpenAI Realtime websocket runtime."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        input_gain: float,
        output_gain: float,
        tools: ToolDispatcher,
        on_event: Callable[[str, dict[str, Any]], None],
        get_robot_mini: Callable[[], Any | None],
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._input_gain = max(0.1, float(input_gain))
        self._output_gain = max(0.1, float(output_gain))
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

    def start(self) -> dict[str, Any]:
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY is required for realtime")
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
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
                "model": self._model,
                "started_at": self._started_at,
                "last_error": self._last_error,
            }

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
        client = AsyncOpenAI(**kwargs)

        try:
            async with client.realtime.connect(model=self._model) as conn:
                self._connection = conn
                self._connected = True
                self._emit_status()

                await conn.session.update(
                    session={
                        "type": "realtime",
                        "output_modalities": ["audio"],
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": 24000},
                                "turn_detection": {
                                    "type": "server_vad",
                                    "create_response": True,
                                    "interrupt_response": True,
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
            self._connection = None
            self._connected = False
            self._emit_status()

    async def _handle_event(self, conn: Any, event: Any) -> None:
        etype = str(getattr(event, "type", "") or "")

        if etype == "conversation.item.input_audio_transcription.completed":
            transcript = str(getattr(event, "transcript", "") or "")
            if transcript:
                self._on_event(
                    "assistant.realtime.transcript",
                    {
                        "role": "user",
                        "content": transcript,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                )
            return

        if etype in {"response.audio_transcript.done", "response.output_audio_transcript.done"}:
            transcript = str(getattr(event, "transcript", "") or "")
            if transcript:
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
                self._play_robot_audio(str(delta))
            return

        if etype in {"response.text.done", "response.output_text.done"}:
            text = str(getattr(event, "text", "") or "")
            if text:
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
                arguments=str(getattr(event, "arguments", "") or "{}"),
                call_id=str(getattr(event, "call_id", "") or ""),
            )
            return

        # Compatibility fallback for older event shape.
        if etype == "conversation.item.added":
            item = getattr(event, "item", None)
            if item and str(getattr(item, "type", "")) == "function_call":
                await self._dispatch_tool_call(
                    conn=conn,
                    name=str(getattr(item, "name", "") or ""),
                    arguments=str(getattr(item, "arguments", "") or "{}"),
                    call_id=str(getattr(item, "call_id", "") or getattr(item, "id", "") or ""),
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

    async def _dispatch_tool_call(self, conn: Any, name: str, arguments: str, call_id: str) -> None:
        if not call_id:
            return
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
        result = self._tools.execute(name, parsed)

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
            # Realtime output PCM is 24kHz; robot media expects 16kHz float32.
            int16_audio = _resample_int16(int16_audio, src_rate=24000, dst_rate=16000)
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
