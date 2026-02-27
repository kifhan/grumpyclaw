"""OpenAI Realtime API handler with tool dispatch and transcript output."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
from openai import AsyncOpenAI

from grumpyreachy.prompts import load_instructions
from grumpyreachy.tools.core_tools import ToolDependencies, get_tools_for_profile

try:
    from fastrtc import AdditionalOutputs, AsyncStreamHandler, wait_for_item
except ImportError:
    AdditionalOutputs = None  # type: ignore[misc, assignment]
    AsyncStreamHandler = None  # type: ignore[misc, assignment]
    wait_for_item = None  # type: ignore[assignment]

LOG = logging.getLogger("grumpyreachy.realtime")

SAMPLE_RATE = 24000


def _tool_definitions(tool_classes: list) -> list[dict[str, Any]]:
    """Build Realtime API tools config from Tool classes."""
    out = []
    for cls in tool_classes:
        out.append({
            "type": "function",
            "name": cls.name,
            "description": cls.description or "",
            "parameters": cls.parameters_schema or {"type": "object", "properties": {}},
        })
    return out


async def _dispatch_tool(
    name: str,
    arguments: str,
    deps: ToolDependencies,
    tool_classes: list,
) -> str:
    """Run tool by name with JSON arguments; return JSON string output."""
    tool_map = {t.name: t for t in tool_classes}
    tool_cls = tool_map.get(name)
    if not tool_cls:
        return json.dumps({"ok": False, "error": f"Unknown tool: {name}"})
    try:
        kwargs = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"Invalid arguments: {e}"})
    try:
        instance = tool_cls()
        result = await instance(deps, **kwargs)
        return json.dumps(result, ensure_ascii=True)
    except Exception as e:
        LOG.exception("Tool %s failed", name)
        return json.dumps({"ok": False, "error": str(e)})


class OpenaiRealtimeHandler(AsyncStreamHandler if AsyncStreamHandler else object):
    """
    AsyncStreamHandler that connects to OpenAI Realtime API, handles tool calls,
    and pushes audio + transcript to output_queue.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str,
        instructions: str,
        tool_classes: list,
        tool_deps: ToolDependencies,
        profiles_dir: Path,
        external_tools_dir: Path | None = None,
        on_transcript: Any = None,
    ):
        if AsyncStreamHandler is None:
            raise RuntimeError("fastrtc not installed")
        super().__init__(
            expected_layout="mono",
            output_sample_rate=SAMPLE_RATE,
            input_sample_rate=SAMPLE_RATE,
        )
        self._api_key = api_key
        self._model_name = model_name
        self._instructions = instructions
        self._tool_classes = tool_classes
        self._tool_deps = tool_deps
        self._profiles_dir = profiles_dir
        self._external_tools_dir = external_tools_dir
        self._on_transcript = on_transcript
        self._connection = None
        self._output_queue: asyncio.Queue = asyncio.Queue()
        self._client: AsyncOpenAI | None = None

    def copy(self) -> "OpenaiRealtimeHandler":
        return OpenaiRealtimeHandler(
            api_key=self._api_key,
            model_name=self._model_name,
            instructions=self._instructions,
            tool_classes=self._tool_classes,
            tool_deps=self._tool_deps,
            profiles_dir=self._profiles_dir,
            external_tools_dir=self._external_tools_dir,
            on_transcript=self._on_transcript,
        )

    async def start_up(self) -> None:
        self._client = AsyncOpenAI(api_key=self._api_key)
        tools_config = _tool_definitions(self._tool_classes)
        async with self._client.realtime.connect(model=self._model_name) as conn:
            self._connection = conn
            await conn.session.update(
                session={
                    "type": "realtime",
                    "instructions": self._instructions,
                    "audio": {
                        "input": {
                            "turn_detection": {"type": "server_vad"},
                            "transcription": {"model": "whisper-1"},
                        }
                    },
                    "tools": tools_config,
                    "tool_choice": "auto",
                },
            )
            async for event in conn:
                await self._handle_event(event)

    async def _handle_event(self, event: Any) -> None:
        etype = getattr(event, "type", None) or getattr(event, "event", "")
        if etype == "input_audio_buffer.speech_started":
            self.clear_queue()
            if self._tool_deps.movement_manager and hasattr(self._tool_deps.movement_manager, "set_listening_mode"):
                self._tool_deps.movement_manager.set_listening_mode(True)

        if etype == "input_audio_buffer.speech_stopped":
            if self._tool_deps.movement_manager and hasattr(self._tool_deps.movement_manager, "set_listening_mode"):
                self._tool_deps.movement_manager.set_listening_mode(False)

        if etype == "response.function_call_arguments.done":
            name = str(getattr(event, "name", "") or "")
            arguments = str(getattr(event, "arguments", "") or "{}")
            call_id = str(getattr(event, "call_id", "") or "")
            output = await _dispatch_tool(name, arguments, self._tool_deps, self._tool_classes)
            if self._connection and call_id:
                await self._connection.conversation.item.create(
                    item={
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output,
                    }
                )
                await self._connection.response.create()
            if self._on_transcript:
                self._on_transcript({"tool": name, "output": output[:200]})

        # Backward-compat fallback for older event shapes.
        if etype == "conversation.item.added":
            item = getattr(event, "item", None)
            if item is None and hasattr(event, "__dict__"):
                item = getattr(event, "item", None)
            itype = getattr(item, "type", None) if item else None
            if item and itype == "function_call":
                name = getattr(item, "name", "") or ""
                arguments = getattr(item, "arguments", "") or "{}"
                call_id = getattr(item, "call_id", None) or getattr(item, "id", "") or ""
                output = await _dispatch_tool(name, arguments, self._tool_deps, self._tool_classes)
                if self._connection:
                    await self._connection.send({
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": output,
                        },
                    })
                    await self._connection.response.create()
                if self._on_transcript:
                    self._on_transcript({"tool": name, "output": output[:200]})

        if etype == "conversation.item.input_audio_transcription.completed":
            transcript = getattr(event, "transcript", "") or ""
            if transcript and self._output_queue:
                await self._output_queue.put(AdditionalOutputs({"role": "user", "content": transcript}))
            if self._on_transcript:
                self._on_transcript({"role": "user", "content": transcript})

        if etype == "response.audio_transcript.done":
            transcript = getattr(event, "transcript", "") or ""
            if transcript and self._output_queue:
                await self._output_queue.put(AdditionalOutputs({"role": "assistant", "content": transcript}))
            if self._on_transcript:
                self._on_transcript({"role": "assistant", "content": transcript})

        if etype == "response.audio.delta":
            delta = getattr(event, "delta", None)
            if delta and self._output_queue:
                arr = np.frombuffer(base64.b64decode(delta), dtype=np.int16).reshape(1, -1)
                await self._output_queue.put((self.output_sample_rate, arr))

        if etype == "response.done":
            if self._tool_deps.movement_manager and hasattr(self._tool_deps.movement_manager, "set_listening_mode"):
                self._tool_deps.movement_manager.set_listening_mode(False)

    async def receive(self, frame: tuple[int, Any]) -> None:
        if not self._connection:
            return
        _, array = frame
        if hasattr(array, "squeeze"):
            array = array.squeeze()
        if hasattr(array, "tobytes"):
            raw = array.tobytes()
        else:
            raw = bytes(array)
        audio_message = base64.b64encode(raw).decode("utf-8")
        await self._connection.input_audio_buffer.append(audio=audio_message)

    async def emit(self) -> Any:
        if wait_for_item is None:
            return None
        return await wait_for_item(self._output_queue)

    async def shutdown(self) -> None:
        if self._connection:
            try:
                await self._connection.close()
            except Exception:
                pass
            self._connection = None
        self._client = None

    def apply_personality(self, profile_name: str, instructions_txt: str, tools_txt: str | None) -> None:
        """Update instructions and optionally tool set (tool_classes reload from profile)."""
        prompts_dir = self._profiles_dir.parent / "prompts"
        self._instructions = load_instructions(instructions_txt, prompts_dir)
        if tools_txt is not None:
            self._tool_classes = get_tools_for_profile(
                profile_name,
                tools_txt,
                self._profiles_dir,
                self._external_tools_dir,
            )
        if self._connection:
            asyncio.create_task(self._update_session())

    async def _update_session(self) -> None:
        if not self._connection:
            return
        await self._connection.session.update(
            session={
                "type": "realtime",
                "instructions": self._instructions,
                "tools": _tool_definitions(self._tool_classes),
            },
        )
