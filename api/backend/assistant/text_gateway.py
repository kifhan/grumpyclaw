from __future__ import annotations

import json
import logging
from collections.abc import Generator
from typing import Any

from openai import OpenAI

from .tools import ToolDispatcher

LOG = logging.getLogger("grumpyadmin.assistant.text")


class OpenAITextGateway:
    """Responses API text gateway with tool-call loop."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        tools: ToolDispatcher,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._tools = tools
        self._client: OpenAI | None = None

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

        for round_no in range(max_rounds):
            tool_calls: dict[str, dict[str, str]] = {}

            kwargs: dict[str, Any] = {
                "model": self._model,
                "instructions": instructions,
                "input": input_items,
                "tools": self._tools.definitions(),
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

                result = self._tools.execute(call["name"], parsed_args)
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

    def _get_client(self) -> OpenAI:
        if self._client is not None:
            return self._client
        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = OpenAI(**kwargs)
        return self._client

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
