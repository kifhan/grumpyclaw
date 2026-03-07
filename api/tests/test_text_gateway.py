from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from api.backend.assistant.text_gateway import OpenAITextGateway


class _StubTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "capture_camera_context",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "type": "function",
                "name": "search_memory",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, dict(arguments)))
        return {
            "ok": True,
            "result": {
                "cache_file": "/tmp/frame.jpg",
                "image_data_url": "data:image/jpeg;base64,AAAA",
            },
        }


class _FakeStream:
    def __init__(self, events: list[Any], final_response: Any):
        self._events = events
        self._final = final_response

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        del exc_type, exc, tb
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_response(self) -> Any:
        return self._final


class _FakeResponses:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs) -> _FakeStream:  # noqa: ANN003
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return _FakeStream(
                events=[
                    SimpleNamespace(
                        type="response.function_call_arguments.done",
                        call_id="call-1",
                        name="capture_camera_context",
                        arguments="{}",
                    )
                ],
                final_response=SimpleNamespace(id="resp-1", output_text=""),
            )
        return _FakeStream(
            events=[],
            final_response=SimpleNamespace(id="resp-2", output_text="done"),
        )


class _FakeClient:
    def __init__(self):
        self.responses = _FakeResponses()


def test_text_gateway_filters_camera_tool_and_strips_image_payloads() -> None:
    tools = _StubTools()
    gateway = OpenAITextGateway(
        api_key="test",
        base_url="",
        ca_bundle="",
        model="gpt-5-mini",
        tools=tools,
    )
    fake_client = _FakeClient()
    gateway._client = fake_client

    events = list(
        gateway.stream_reply(
            instructions="test",
            messages=[{"role": "user", "content": "hello"}],
            max_rounds=2,
        )
    )

    first_round_tools = fake_client.responses.calls[0]["tools"]
    assert "capture_camera_context" not in {str(item.get("name", "")) for item in first_round_tools}

    tool_events = [event for event in events if event["type"] == "tool"]
    assert len(tool_events) == 1
    assert "image_data_url" not in json.dumps(tool_events[0]["result"])

    second_round_input = fake_client.responses.calls[1]["input"]
    assert len(second_round_input) == 1
    assert second_round_input[0]["type"] == "function_call_output"
    assert "image_data_url" not in second_round_input[0]["output"]
