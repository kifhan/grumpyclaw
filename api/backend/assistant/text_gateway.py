from __future__ import annotations

import json
import logging
from collections.abc import Generator
from typing import Any

import httpx
from openai import OpenAI

from ..openai_tls import resolve_tls_verify
from .tools import ToolDispatcher

LOG = logging.getLogger("grumpyadmin.assistant.text")


def _strip_image_data_url(value: Any) -> Any:
    """Remove internal realtime-only image payload fields from tool outputs."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "image_data_url":
                continue
            out[key] = _strip_image_data_url(item)
        return out
    if isinstance(value, list):
        return [_strip_image_data_url(item) for item in value]
    return value


class OpenAITextGateway:
    """Responses API text gateway with tool-call loop."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        ca_bundle: str,
        model: str,
        tools: ToolDispatcher,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._ca_bundle = ca_bundle
        self._model = model
        self._tools = tools
        self._client: OpenAI | None = None
        self._http_client: httpx.Client | None = None

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def stream_reply(
        self,
        *,
        instructions: str,
        messages: list[dict[str, Any]],
        max_rounds: int = 8,
    ) -> Generator[dict[str, Any], None, None]:
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY is required for assistant text replies")

        input_items = self._to_input_items(messages)
        previous_response_id: str | None = None
        tool_definitions = self._tool_definitions_for_text()

        for round_no in range(max_rounds):
            tool_calls: dict[str, dict[str, str]] = {}

            kwargs: dict[str, Any] = {
                "model": self._model,
                "instructions": instructions,
                "input": input_items,
                "tools": tool_definitions,
                "tool_choice": "auto",
            }
            if previous_response_id:
                kwargs["previous_response_id"] = previous_response_id

            with self._get_client().responses.stream(**kwargs) as stream:
                for event in stream:
                    etype = getattr(event, "type", "")
                    if etype in {"response.output_text.delta", "response.text.delta"}:
                        delta = str(getattr(event, "delta", "") or "")
                        if delta:
                            yield {"type": "token", "delta": delta}
                        continue

                    if etype == "response.function_call_arguments.done":
                        call_id = str(getattr(event, "call_id", "") or "")
                        if call_id:
                            tool_calls[call_id] = {
                                "call_id": call_id,
                                "name": str(getattr(event, "name", "") or ""),
                                "arguments": str(getattr(event, "arguments", "") or "{}"),
                            }
                        continue

                    # Compatibility: sometimes function_call appears as output item.
                    if etype == "response.output_item.done":
                        item = getattr(event, "item", None)
                        if item and getattr(item, "type", "") == "function_call":
                            call_id = str(getattr(item, "call_id", "") or "")
                            if call_id and call_id not in tool_calls:
                                tool_calls[call_id] = {
                                    "call_id": call_id,
                                    "name": str(getattr(item, "name", "") or ""),
                                    "arguments": str(getattr(item, "arguments", "") or "{}"),
                                }

                final = stream.get_final_response()

            previous_response_id = str(getattr(final, "id", "") or "") or previous_response_id
            if not tool_calls:
                yield {"type": "final", "text": getattr(final, "output_text", "") or ""}
                return

            next_inputs: list[dict[str, Any]] = []
            for call in tool_calls.values():
                raw_args = call["arguments"] or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = {}

                result = _strip_image_data_url(self._tools.execute(call["name"], parsed_args))
                yield {
                    "type": "tool",
                    "call_id": call["call_id"],
                    "name": call["name"],
                    "arguments": parsed_args,
                    "result": result,
                }
                next_inputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": json.dumps(result, ensure_ascii=True),
                    }
                )

            input_items = next_inputs
            LOG.debug("responses tool round=%s calls=%s", round_no + 1, len(next_inputs))

        raise RuntimeError("Exceeded max tool-call rounds")

    def complete_text(
        self,
        *,
        instructions: str,
        messages: list[dict[str, Any]],
    ) -> str:
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY is required for assistant text replies")

        response = self._get_client().responses.create(
            model=self._model,
            instructions=instructions,
            input=self._to_input_items(messages),
        )
        return str(getattr(response, "output_text", "") or "").strip()

    def _get_client(self) -> OpenAI:
        if self._client is not None:
            return self._client
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        if self._http_client is None:
            verify = resolve_tls_verify(self._ca_bundle)
            self._http_client = httpx.Client(verify=verify)
        kwargs["http_client"] = self._http_client
        self._client = OpenAI(**kwargs)
        return self._client

    def _tool_definitions_for_text(self) -> list[dict[str, Any]]:
        # Camera image capture is realtime-specific and can produce large data URLs.
        return [
            tool
            for tool in self._tools.definitions()
            if str(tool.get("name", "")) != "capture_camera_context"
        ]

    @staticmethod
    def _to_input_items(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for msg in messages:
            role = str(msg.get("role", "user") or "user").strip().lower()
            content = str(msg.get("content", "") or "")
            if not content:
                continue
            if role not in {"user", "assistant", "developer"}:
                role = "user"
            out.append({"role": role, "content": content})
        return out
