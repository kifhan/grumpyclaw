"""Shared FastEmbed model-loading helpers."""

from __future__ import annotations

import os
from pathlib import Path

from grumpyclaw.memory.db import get_embedding_cache_dir

_MISSING_MODEL_ERROR_MARKERS = (
    "NO_SUCHFILE",
    "File doesn't exist",
    "Load model from",
)


def _embedding_providers() -> list[str] | None:
    providers_raw = os.environ.get("GRUMPYCLAW_EMBEDDING_PROVIDERS", "CPUExecutionProvider").strip()
    if not providers_raw or providers_raw.lower() == "auto":
        return None
    providers = [p.strip() for p in providers_raw.split(",") if p.strip()]
    return providers or None


def _is_missing_model_error(exc: Exception) -> bool:
    message = str(exc)
    return any(marker in message for marker in _MISSING_MODEL_ERROR_MARKERS)


def _cache_attempts(cache_dir: Path) -> list[Path]:
    # Keep a recovery path separate from the primary cache to recover from partial/corrupt downloads.
    return [cache_dir, cache_dir / "recovered"]


def create_text_embedding(model_name: str):
    from fastembed import TextEmbedding

    providers = _embedding_providers()
    cache_dir = get_embedding_cache_dir()
    last_error: Exception | None = None
    for attempt_dir in _cache_attempts(cache_dir):
        attempt_dir.mkdir(parents=True, exist_ok=True)
        try:
            return TextEmbedding(
                model_name=model_name,
                cache_dir=str(attempt_dir),
                max_length=512,
                providers=providers,
                cuda=False,
            )
        except Exception as exc:
            if not _is_missing_model_error(exc):
                raise
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("Failed to initialize embedding model.")
