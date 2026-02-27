"""OpenAI-only LLM client built on the Responses API."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from typing import Any

from openai import OpenAI

LOG = logging.getLogger("grumpyclaw.llm")


def _resolve_text_model() -> str:
    text_model = os.environ.get("OPENAI_TEXT_MODEL", "").strip()
    if text_model:
        return text_model
    legacy = os.environ.get("LLM_MODEL", "").strip()
    if legacy:
        LOG.warning("Deprecated env LLM_MODEL in use. Set OPENAI_TEXT_MODEL instead.")
        return legacy
    return "gpt-5-mini"


def _get_config() -> tuple[str, str, str]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    model = _resolve_text_model()

    if not api_key:
        raise ValueError("Set OPENAI_API_KEY")
    return api_key, base_url, model


def get_client() -> OpenAI:
    api_key, base_url, _ = _get_config()
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def chat(messages: list[dict[str, Any]], stream: bool = False) -> str | Generator[str, None, None]:
    """Send chat-like messages via Responses API.

    `messages` supports role/content pairs. `system` messages are mapped to
    `instructions`.
    """
    _, _, model = _get_config()
    client = get_client()

    instructions = ""
    input_items: list[dict[str, str]] = []
    for msg in messages:
        role = str(msg.get("role", "user") or "user").strip().lower()
        content = str(msg.get("content", "") or "")
        if not content:
            continue
        if role == "system":
            instructions = f"{instructions}\n{content}".strip()
            continue
        if role not in {"user", "assistant", "developer"}:
            role = "user"
        input_items.append({"role": role, "content": content})

    if stream:
        resp = client.responses.create(
            model=model,
            instructions=instructions or None,
            input=input_items,
            stream=True,
        )

        def gen() -> Generator[str, None, None]:
            for event in resp:
                etype = str(getattr(event, "type", "") or "")
                if etype in {"response.output_text.delta", "response.text.delta"}:
                    delta = str(getattr(event, "delta", "") or "")
                    if delta:
                        yield delta

        return gen()

    response = client.responses.create(
        model=model,
        instructions=instructions or None,
        input=input_items,
    )
    return response.output_text or ""
