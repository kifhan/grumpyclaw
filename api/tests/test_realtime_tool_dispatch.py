from __future__ import annotations

import asyncio
import json
from typing import Any

from api.backend.assistant.realtime_service import OpenAIRealtimeService


class _StubTools:
    def __init__(self, result: dict[str, Any]):
        self._result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def definitions(self) -> list[dict[str, Any]]:
        return []

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        return self._result

    def purge_runtime_cache(self) -> int:
        return 0


class _ConversationItem:
    def __init__(self, parent: "_Conn"):
        self._parent = parent

    async def create(self, item: dict[str, Any]) -> None:
        if item.get("type") == "message" and self._parent.fail_on_image_message:
            raise RuntimeError("inject failed")
        self._parent.calls.append(("conversation.item.create", item))


class _Conversation:
    def __init__(self, parent: "_Conn"):
        self.item = _ConversationItem(parent)


class _Response:
    def __init__(self, parent: "_Conn"):
        self._parent = parent

    async def create(self) -> None:
        self._parent.calls.append(("response.create", None))


class _Conn:
    def __init__(self, *, fail_on_image_message: bool = False):
        self.fail_on_image_message = fail_on_image_message
        self.calls: list[tuple[str, Any]] = []
        self.conversation = _Conversation(self)
        self.response = _Response(self)


def _build_service(*, tool_result: dict[str, Any], events: list[tuple[str, dict[str, Any]]]) -> OpenAIRealtimeService:
    tools = _StubTools(tool_result)
    return OpenAIRealtimeService(
        api_key="test",
        base_url="",
        ca_bundle="",
        model="gpt-realtime",
        input_gain=1.0,
        output_gain=1.0,
        mic_suppression_seconds=0.0,
        talk_overlap_mode="strict_anti_loop",
        post_playback_hold_seconds=0.9,
        voice_effect_mode="none",
        aec_enabled=False,
        aec_delay_ms=0,
        aec_strength=0.0,
        aec_corr_threshold=0.0,
        instructions="test instructions",
        tools=tools,
        on_event=lambda event_type, payload: events.append((event_type, payload)),
        get_robot_mini=lambda: None,
    )


def test_dispatch_tool_call_with_image_injects_and_sanitizes() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(
        tool_result={
            "ok": True,
            "result": {
                "cache_file": "/tmp/a.jpg",
                "image_data_url": "data:image/jpeg;base64,AAAA",
            },
        },
        events=events,
    )
    conn = _Conn()

    asyncio.run(service._dispatch_tool_call(conn, "capture_camera_context", "{}", "call-1"))

    assert [name for name, _ in conn.calls] == [
        "conversation.item.create",
        "conversation.item.create",
        "response.create",
    ]
    image_item = conn.calls[0][1]
    assert image_item["type"] == "message"
    assert image_item["content"][0]["type"] == "input_image"
    function_output_item = conn.calls[1][1]
    output = json.loads(function_output_item["output"])
    assert "image_data_url" not in json.dumps(output)
    assert output["result"]["cache_file"] == "/tmp/a.jpg"

    tool_events = [payload for event_type, payload in events if event_type == "assistant.tool"]
    assert len(tool_events) == 1
    assert "image_data_url" not in json.dumps(tool_events[0]["result"])


def test_dispatch_tool_call_injection_failure_still_returns_output() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(
        tool_result={
            "ok": True,
            "result": {
                "cache_file": "/tmp/a.jpg",
                "image_data_url": "data:image/jpeg;base64,AAAA",
            },
        },
        events=events,
    )
    conn = _Conn(fail_on_image_message=True)

    asyncio.run(service._dispatch_tool_call(conn, "capture_camera_context", "{}", "call-1"))

    assert [name for name, _ in conn.calls] == ["conversation.item.create", "response.create"]
    function_output_item = conn.calls[0][1]
    payload = json.loads(function_output_item["output"])
    assert "image_injection_error" in json.dumps(payload)
    assert "image_data_url" not in json.dumps(payload)


def test_dispatch_tool_call_without_image_uses_standard_sequence() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"foo": "bar"}}, events=events)
    conn = _Conn()

    asyncio.run(service._dispatch_tool_call(conn, "search_memory", "{}", "call-2"))

    assert [name for name, _ in conn.calls] == ["conversation.item.create", "response.create"]
    function_output_item = conn.calls[0][1]
    payload = json.loads(function_output_item["output"])
    assert payload["result"]["foo"] == "bar"


def test_handle_event_output_item_done_dispatches_tool_call() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"foo": "bar"}}, events=events)
    conn = _Conn()
    event = type(
        "Evt",
        (),
        {
            "type": "response.output_item.done",
            "item": type(
                "Item",
                (),
                {
                    "type": "function_call",
                    "name": "robot_action",
                    "arguments": "{\"action\":\"nod\"}",
                    "call_id": "call-3",
                    "id": "item-3",
                },
            )(),
        },
    )()

    asyncio.run(service._handle_event(conn, event))

    assert [name for name, _ in conn.calls] == ["conversation.item.create", "response.create"]
    tool_events = [payload for event_type, payload in events if event_type == "assistant.tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["call_id"] == "call-3"


def test_handle_event_output_item_done_with_dict_arguments_dispatches_tool_call() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"foo": "bar"}}, events=events)
    conn = _Conn()
    event = type(
        "Evt",
        (),
        {
            "type": "response.output_item.done",
            "item": type(
                "Item",
                (),
                {
                    "type": "function_call",
                    "name": "robot_action",
                    "arguments": {"action": "nod"},
                    "call_id": "call-dict-args",
                    "id": "item-dict-args",
                },
            )(),
        },
    )()

    asyncio.run(service._handle_event(conn, event))

    assert [name for name, _ in conn.calls] == ["conversation.item.create", "response.create"]
    tool_events = [payload for event_type, payload in events if event_type == "assistant.tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "robot_action"
    assert tool_events[0]["arguments"]["action"] == "nod"


def test_handle_event_output_item_done_ignores_incomplete_function_call() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"foo": "bar"}}, events=events)
    conn = _Conn()
    event = type(
        "Evt",
        (),
        {
            "type": "response.output_item.done",
            "item": type(
                "Item",
                (),
                {
                    "type": "function_call",
                    "status": "incomplete",
                    "name": "robot_action",
                    "arguments": "{\"action\":\"nod\"}",
                    "call_id": "call-incomplete",
                    "id": "item-incomplete",
                },
            )(),
        },
    )()

    asyncio.run(service._handle_event(conn, event))

    assert conn.calls == []
    tool_events = [payload for event_type, payload in events if event_type == "assistant.tool"]
    assert tool_events == []


def test_handle_event_dedupes_duplicate_function_call_events() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"foo": "bar"}}, events=events)
    conn = _Conn()
    first = type(
        "Evt",
        (),
        {
            "type": "response.function_call_arguments.done",
            "name": "robot_action",
            "arguments": "{\"action\":\"nod\"}",
            "call_id": "call-dup",
        },
    )()
    second = type(
        "Evt",
        (),
        {
            "type": "response.output_item.done",
            "item": type(
                "Item",
                (),
                {
                    "type": "function_call",
                    "name": "robot_action",
                    "arguments": "{\"action\":\"nod\"}",
                    "call_id": "call-dup",
                    "id": "item-dup",
                },
            )(),
        },
    )()

    asyncio.run(service._handle_event(conn, first))
    asyncio.run(service._handle_event(conn, second))

    assert [name for name, _ in conn.calls] == ["conversation.item.create", "response.create"]
    tool_events = [payload for event_type, payload in events if event_type == "assistant.tool"]
    assert len(tool_events) == 1


def test_handle_event_ignores_provisional_empty_robot_action_and_uses_output_item_done() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"foo": "bar"}}, events=events)
    conn = _Conn()
    provisional = type(
        "Evt",
        (),
        {
            "type": "response.function_call_arguments.done",
            "name": "robot_action",
            "arguments": "{}",
            "call_id": "call-empty-then-full",
        },
    )()
    authoritative = type(
        "Evt",
        (),
        {
            "type": "response.output_item.done",
            "item": type(
                "Item",
                (),
                {
                    "type": "function_call",
                    "name": "robot_action",
                    "arguments": "{\"action\":\"nod\"}",
                    "call_id": "call-empty-then-full",
                    "id": "item-empty-then-full",
                },
            )(),
        },
    )()

    asyncio.run(service._handle_event(conn, provisional))
    assert conn.calls == []

    asyncio.run(service._handle_event(conn, authoritative))

    assert [name for name, _ in conn.calls] == ["conversation.item.create", "response.create"]
    tool_events = [payload for event_type, payload in events if event_type == "assistant.tool"]
    assert len(tool_events) == 1
    assert tool_events[0]["name"] == "robot_action"


def test_empty_robot_action_is_inferred_from_recent_user_transcript() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"accepted": True}}, events=events)
    # Simulate the latest user utterance before the model emits an empty function call.
    user_event = type(
        "Evt",
        (),
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": "Show happy emotions",
        },
    )()
    asyncio.run(service._handle_event(object(), user_event))

    conn = _Conn()
    empty_call = type(
        "Evt",
        (),
        {
            "type": "response.output_item.done",
            "item": type(
                "Item",
                (),
                {
                    "type": "function_call",
                    "name": "robot_action",
                    "arguments": {},
                    "call_id": "call-infer-emotion",
                    "id": "item-infer-emotion",
                },
            )(),
        },
    )()
    asyncio.run(service._handle_event(conn, empty_call))

    # Tool execution should use inferred action/name rather than empty arguments.
    tools = service._tools  # type: ignore[attr-defined]
    assert tools.calls[-1][0] == "robot_action"
    assert tools.calls[-1][1]["action"] == "play_emotion"
    assert tools.calls[-1][1]["name"] == "happy"


def test_emotion_intent_rewrites_weak_nod_to_play_emotion() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"accepted": True}}, events=events)
    service._last_user_transcript = "Maybe exciting."

    class _RobotService:
        def get_motion_catalog(self) -> dict[str, object]:
            return {"available": True, "emotions": ["attentive2", "happy_wave"], "dances": []}

    service._tools._robot_service = _RobotService()  # type: ignore[attr-defined]
    conn = _Conn()

    asyncio.run(
        service._dispatch_tool_call(
            conn,
            "robot_action",
            "{\"action\":\"nod\"}",
            "call-rewrite-nod",
            source_event="response.output_item.done",
        )
    )

    tools = service._tools  # type: ignore[attr-defined]
    assert tools.calls[-1][0] == "robot_action"
    assert tools.calls[-1][1]["action"] == "play_emotion"
    assert tools.calls[-1][1]["name"] == "happy_wave"


def test_emotion_intent_rewrites_missing_action_to_play_emotion() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"accepted": True}}, events=events)
    service._last_user_transcript = "I feel upset."
    conn = _Conn()

    asyncio.run(
        service._dispatch_tool_call(
            conn,
            "robot_action",
            "{}",
            "call-rewrite-missing-action",
            source_event="response.output_item.done",
        )
    )

    tools = service._tools  # type: ignore[attr-defined]
    assert tools.calls[-1][0] == "robot_action"
    assert tools.calls[-1][1]["action"] == "play_emotion"
    assert tools.calls[-1][1]["name"] == "sad"


def test_non_emotion_turn_keeps_nod_unchanged() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"accepted": True}}, events=events)
    service._last_user_transcript = "Can you check the time?"
    conn = _Conn()

    asyncio.run(
        service._dispatch_tool_call(
            conn,
            "robot_action",
            "{\"action\":\"nod\"}",
            "call-keep-nod",
            source_event="response.output_item.done",
        )
    )

    tools = service._tools  # type: ignore[attr-defined]
    assert tools.calls[-1][0] == "robot_action"
    assert tools.calls[-1][1]["action"] == "nod"


def test_dance_intent_rewrites_nod_to_dance_with_catalog_match() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"accepted": True}}, events=events)
    service._last_user_transcript = "Show me dances, chicken style."

    class _RobotService:
        def get_motion_catalog(self) -> dict[str, object]:
            return {
                "available": True,
                "emotions": ["happy"],
                "dances": ["spin_intro", "chicken_peck"],
            }

    service._tools._robot_service = _RobotService()  # type: ignore[attr-defined]
    conn = _Conn()

    asyncio.run(
        service._dispatch_tool_call(
            conn,
            "robot_action",
            "{\"action\":\"nod\"}",
            "call-dance-rewrite",
            source_event="response.output_item.done",
        )
    )

    tools = service._tools  # type: ignore[attr-defined]
    assert tools.calls[-1][0] == "robot_action"
    assert tools.calls[-1][1]["action"] == "dance"
    assert tools.calls[-1][1]["name"] == "chicken_peck"


def test_repeated_nod_is_broken_to_play_emotion_when_not_explicit_nod_request() -> None:
    events: list[tuple[str, dict[str, Any]]] = []
    service = _build_service(tool_result={"ok": True, "result": {"accepted": True}}, events=events)
    service._last_user_transcript = "okay, cool"
    service._recent_robot_actions.extend(["nod", "nod"])

    class _RobotService:
        def get_motion_catalog(self) -> dict[str, object]:
            return {
                "available": True,
                "emotions": ["happy", "neutral_pose"],
                "dances": [],
            }

    service._tools._robot_service = _RobotService()  # type: ignore[attr-defined]
    conn = _Conn()

    asyncio.run(
        service._dispatch_tool_call(
            conn,
            "robot_action",
            "{\"action\":\"nod\"}",
            "call-break-repeat-nod",
            source_event="response.output_item.done",
        )
    )

    tools = service._tools  # type: ignore[attr-defined]
    assert tools.calls[-1][0] == "robot_action"
    assert tools.calls[-1][1]["action"] == "play_emotion"
    assert tools.calls[-1][1]["name"] == "happy"
