"""OpenAI-compatible LLM client for OpenAI and OpenCode Zen."""

from __future__ import annotations

import os
from typing import Any, Generator

from openai import OpenAI


def _get_config() -> tuple[str, str, str]:
    """Return (api_key, base_url, model). Prefer OpenCode Zen if key set."""
    opencode_key = os.environ.get("OPENCODE_API_KEY", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()

    if opencode_key:
        api_key = opencode_key
        base_url = base_url or "https://opencode.ai/zen/v1"
        model = model or "opencode/gpt-5-nano"
    elif openai_key:
        api_key = openai_key
        base_url = base_url or "https://api.openai.com/v1"
        model = model or "gpt-5-nano"
    else:
        raise ValueError(
            "Set OPENCODE_API_KEY or OPENAI_API_KEY (and optionally LLM_BASE_URL, LLM_MODEL)"
        )

    return api_key, base_url, model


def get_client() -> OpenAI:
    """Return configured OpenAI client (works with OpenCode Zen via base_url)."""
    api_key, base_url, _ = _get_config()
    return OpenAI(api_key=api_key, base_url=base_url)


def chat(
    messages: list[dict[str, Any]],
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """
    Send messages to the LLM and return the assistant reply.

    messages: list of {"role": "user"|"assistant"|"system", "content": "..."}
    stream: if True, yield content chunks; otherwise return full content string.
    """
    _, _, model = _get_config()
    client = get_client()

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=stream,
    )

    if stream:
        def gen() -> Generator[str, None, None]:
            for chunk in resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        return gen()

    if not resp.choices:
        return ""
    return resp.choices[0].message.content or ""
