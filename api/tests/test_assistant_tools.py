from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grumpyclaw.memory.db import init_db

from api.backend.assistant.image_cache import RealtimeImageCache
from api.backend.assistant.tools import ToolDispatcher


class _DummyRetriever:
    def hybrid_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        return [{"query": query, "top_k": top_k}]


class _DummyWorker:
    def __init__(self, frame: bytes | None):
        self._frame = frame

    def get_latest_frame(self) -> bytes | None:
        return self._frame


@dataclass
class _DummyActionResult:
    accepted: bool = True
    action_id: str = "action-1"
    reason: str = ""


class _DummyRobotService:
    def __init__(self, worker: Any | None = None):
        self._worker = worker
        self.payloads: list[dict[str, Any]] = []

    def get_camera_worker(self) -> Any | None:
        return self._worker

    def enqueue_action(self, payload: dict[str, Any]) -> _DummyActionResult:
        self.payloads.append(payload)
        return _DummyActionResult()


class _FakeIndexer:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.calls: list[tuple[list[dict[str, Any]], str]] = []

    def index_documents(self, documents: list[dict[str, Any]], source_type: str = "google_docs") -> int:
        conn = init_db(self.db_path)
        try:
            cur = conn.cursor()
            for doc in documents:
                cur.execute(
                    """
                    INSERT INTO chunks (source_type, source_id, title, content, embedding)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source_type,
                        str(doc["id"]),
                        str(doc.get("title", "")),
                        str(doc.get("text", "")),
                        "[]",
                    ),
                )
                chunk_id = int(cur.lastrowid)
                cur.execute("INSERT INTO chunks_fts (chunk_id, content) VALUES (?, ?)", (chunk_id, str(doc.get("text", ""))))
            conn.commit()
        finally:
            conn.close()
        self.calls.append((documents, source_type))
        return len(documents)


class _BrokenImageCache:
    def purge_expired(self) -> int:
        return 0

    def store_jpeg(self, image_bytes: bytes):  # noqa: ANN001
        del image_bytes
        raise RuntimeError("boom")


def _build_dispatcher(tmp_path: Path, *, worker: Any | None = None, image_cache: Any | None = None) -> ToolDispatcher:
    cache = image_cache or RealtimeImageCache(cache_dir=tmp_path / "img-cache", ttl_seconds=60)
    return ToolDispatcher(
        robot_service=_DummyRobotService(worker=worker),
        retriever=_DummyRetriever(),
        indexer=_FakeIndexer(tmp_path / "memory.db"),
        image_cache=cache,
    )


def test_definitions_include_new_tools_and_actions(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)
    defs = {item["name"]: item for item in dispatcher.definitions()}

    assert "capture_camera_context" in defs
    assert "save_memory" in defs
    actions = set(defs["robot_action"]["parameters"]["properties"]["action"]["enum"])
    assert {"play_emotion", "stop_emotion", "dance", "stop_dance"} <= actions


def test_capture_camera_context_success(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path, worker=_DummyWorker(frame=b"\xff\xd8\xff\xe0\x00\x10JFIF"))
    out = dispatcher.execute("capture_camera_context", {})

    assert out["ok"] is True
    result = out["result"]
    assert "image_data_url" in result
    assert result["image_data_url"].startswith("data:image/jpeg;base64,")
    assert Path(result["cache_file"]).is_file()
    assert result["byte_size"] > 0


def test_capture_camera_context_missing_worker(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path, worker=None)
    out = dispatcher.execute("capture_camera_context", {})

    assert out["ok"] is False
    assert out["code"] == "camera_unavailable"


def test_capture_camera_context_missing_frame(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path, worker=_DummyWorker(frame=None))
    out = dispatcher.execute("capture_camera_context", {})

    assert out["ok"] is False
    assert out["code"] == "camera_frame_unavailable"


def test_capture_camera_context_cache_failure(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(
        tmp_path,
        worker=_DummyWorker(frame=b"\xff\xd8\xff\xe0\x00\x10JFIF"),
        image_cache=_BrokenImageCache(),
    )
    out = dispatcher.execute("capture_camera_context", {})

    assert out["ok"] is False
    assert out["code"] == "camera_cache_failed"


def test_save_memory_stores_then_dedupes(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)
    first = dispatcher.execute("save_memory", {"memory": "I like oat milk lattes."})
    second = dispatcher.execute("save_memory", {"memory": "I like   oat milk lattes."})

    assert first["ok"] is True
    assert first["result"]["stored"] is True
    assert first["result"]["deduped"] is False
    assert second["ok"] is True
    assert second["result"]["stored"] is False
    assert second["result"]["deduped"] is True
    assert first["result"]["memory_id"] == second["result"]["memory_id"]


def test_save_memory_blocks_sensitive_content(tmp_path: Path) -> None:
    dispatcher = _build_dispatcher(tmp_path)
    out = dispatcher.execute("save_memory", {"memory": "api_key=sk-1234567890abcdefghijklmnop"})

    assert out["ok"] is False
    assert out["code"] == "sensitive_content_blocked"


def test_robot_action_passes_expressive_fields(tmp_path: Path) -> None:
    robot = _DummyRobotService()
    dispatcher = ToolDispatcher(
        robot_service=robot,
        retriever=_DummyRetriever(),
        indexer=_FakeIndexer(tmp_path / "memory.db"),
        image_cache=RealtimeImageCache(cache_dir=tmp_path / "img-cache", ttl_seconds=60),
    )
    out = dispatcher.execute(
        "robot_action",
        {"action": "dance", "name": "celebration", "duration": 2.5, "confirm": True},
    )

    assert out["ok"] is True
    assert robot.payloads[-1]["action"] == "dance"
    assert robot.payloads[-1]["name"] == "celebration"
    assert robot.payloads[-1]["duration"] == 2.5


def test_robot_action_requires_action_field(tmp_path: Path) -> None:
    robot = _DummyRobotService()
    dispatcher = ToolDispatcher(
        robot_service=robot,
        retriever=_DummyRetriever(),
        indexer=_FakeIndexer(tmp_path / "memory.db"),
        image_cache=RealtimeImageCache(cache_dir=tmp_path / "img-cache", ttl_seconds=60),
    )
    out = dispatcher.execute("robot_action", {})

    assert out["ok"] is False
    assert out["code"] == "action_required"
    assert robot.payloads == []


def test_robot_action_rejects_unknown_action_before_enqueue(tmp_path: Path) -> None:
    robot = _DummyRobotService()
    dispatcher = ToolDispatcher(
        robot_service=robot,
        retriever=_DummyRetriever(),
        indexer=_FakeIndexer(tmp_path / "memory.db"),
        image_cache=RealtimeImageCache(cache_dir=tmp_path / "img-cache", ttl_seconds=60),
    )
    out = dispatcher.execute("robot_action", {"action": "spin_around_like_a_top"})

    assert out["ok"] is False
    assert out["code"] == "unsupported_action"
    assert "allowed_actions" in out
    assert robot.payloads == []
