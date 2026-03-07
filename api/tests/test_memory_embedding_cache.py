from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from grumpyclaw.memory import db as memory_db
from grumpyclaw.memory import embedding as memory_embedding


def test_embedding_cache_default_uses_project_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GRUMPYCLAW_EMBEDDING_CACHE_DIR", raising=False)
    monkeypatch.setattr(memory_db, "get_project_root", lambda: tmp_path)

    cache_dir = memory_db.get_embedding_cache_dir()

    assert cache_dir == tmp_path / "data" / "fastembed_cache"
    assert cache_dir.is_dir()


def test_embedding_cache_respects_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom = tmp_path / "custom-fastembed-cache"
    monkeypatch.setenv("GRUMPYCLAW_EMBEDDING_CACHE_DIR", str(custom))

    cache_dir = memory_db.get_embedding_cache_dir()

    assert cache_dir == custom
    assert cache_dir.is_dir()


def test_create_text_embedding_retries_with_recovery_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "emb-cache"
    monkeypatch.setattr(memory_embedding, "get_embedding_cache_dir", lambda: cache_root)
    monkeypatch.setenv("GRUMPYCLAW_EMBEDDING_PROVIDERS", "CPUExecutionProvider")

    calls: list[str | None] = []

    class _FakeTextEmbedding:
        def __init__(self, *args, **kwargs):  # noqa: ANN002,ANN003
            del args
            calls.append(kwargs.get("cache_dir"))
            if len(calls) == 1:
                raise RuntimeError("NO_SUCHFILE: model.onnx failed. File doesn't exist")
            self.cache_dir = kwargs.get("cache_dir")

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=_FakeTextEmbedding))

    model = memory_embedding.create_text_embedding("sentence-transformers/all-MiniLM-L6-v2")

    assert model.cache_dir == str(cache_root / "recovered")
    assert calls == [str(cache_root), str(cache_root / "recovered")]
