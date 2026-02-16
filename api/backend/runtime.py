from __future__ import annotations

import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .db import dump_json, get_conn
from .event_bus import EventBus, StreamEvent

ALLOWED_PROCESSES = {
    "grumpyreachy-run": ["uv", "run", "grumpyreachy-run"],
    "slack-bot": ["uv", "run", "slack-bot"],
    "heartbeat": ["uv", "run", "heartbeat"],
    "grumpyreachy-heartbeat": ["uv", "run", "grumpyreachy-heartbeat"],
}


@dataclass
class ProcessState:
    name: str
    command: list[str]
    proc: subprocess.Popen[str] | None = None
    status: str = "stopped"
    pid: int | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    uptime_seconds: float = 0.0
    retries: int = 0
    health: str = "idle"
    logs: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=300))


class RuntimeManager:
    def __init__(self, event_bus: EventBus) -> None:
        self._lock = threading.Lock()
        self._states = {name: ProcessState(name=name, command=cmd) for name, cmd in ALLOWED_PROCESSES.items()}
        self._event_bus = event_bus
        self._stop_event = threading.Event()

    def shutdown(self) -> None:
        self._stop_event.set()
        for name in ALLOWED_PROCESSES:
            self.stop(name)

    def status(self) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(timezone.utc)
            out: dict[str, Any] = {}
            for name, state in self._states.items():
                uptime = 0.0
                if state.started_at and state.status == "running":
                    try:
                        dt = datetime.fromisoformat(state.started_at)
                        uptime = (now - dt).total_seconds()
                    except ValueError:
                        uptime = 0.0
                out[name] = {
                    "status": state.status,
                    "pid": state.pid,
                    "started_at": state.started_at,
                    "stopped_at": state.stopped_at,
                    "uptime_seconds": round(uptime, 2),
                    "health": state.health,
                    "retries": state.retries,
                }
            return out

    def start(self, name: str) -> str:
        if name not in self._states:
            raise ValueError(f"Unsupported process: {name}")
        with self._lock:
            state = self._states[name]
            if state.proc and state.proc.poll() is None:
                return "running"
            cmd = list(state.command)
            state.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            state.pid = state.proc.pid
            state.status = "running"
            state.health = "running"
            state.started_at = datetime.now(timezone.utc).isoformat()
            state.stopped_at = None
            self._emit(name, "process.started", {"pid": state.pid, "command": cmd}, level="INFO")
            threading.Thread(target=self._read_logs, args=(name,), daemon=True).start()
            threading.Thread(target=self._watch_exit, args=(name,), daemon=True).start()
            return state.status

    def stop(self, name: str) -> str:
        if name not in self._states:
            raise ValueError(f"Unsupported process: {name}")
        with self._lock:
            state = self._states[name]
            proc = state.proc
            if not proc or proc.poll() is not None:
                state.status = "stopped"
                state.health = "idle"
                return state.status
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        with self._lock:
            state.status = "stopped"
            state.health = "idle"
            state.stopped_at = datetime.now(timezone.utc).isoformat()
            self._emit(name, "process.stopped", {"pid": state.pid}, level="INFO")
        return "stopped"

    def restart(self, name: str) -> str:
        self.stop(name)
        time.sleep(0.2)
        return self.start(name)

    def _read_logs(self, name: str) -> None:
        with self._lock:
            state = self._states[name]
            proc = state.proc
        if not proc or not proc.stdout:
            return
        for line in iter(proc.stdout.readline, ""):
            msg = line.rstrip()
            if not msg:
                continue
            event = {
                "line": msg,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            with self._lock:
                state.logs.append(event)
            self._emit(name, "process.log", event, level=_infer_level_from_log_line(msg))

    def _watch_exit(self, name: str) -> None:
        with self._lock:
            state = self._states[name]
            proc = state.proc
        if not proc:
            return
        code = proc.wait()
        with self._lock:
            state.status = "stopped"
            state.health = "exited" if code != 0 else "idle"
            state.stopped_at = datetime.now(timezone.utc).isoformat()
            level = "ERROR" if code != 0 else "INFO"
            self._emit(name, "process.exit", {"code": code, "pid": state.pid}, level=level)
            if code != 0 and state.retries < 2 and not self._stop_event.is_set():
                state.retries += 1
                threading.Thread(target=self._restart_with_cooldown, args=(name,), daemon=True).start()

    def _restart_with_cooldown(self, name: str) -> None:
        time.sleep(2.0)
        try:
            self.start(name)
        except Exception:
            return

    def _emit(
        self,
        process_name: str,
        event_type: str,
        payload: dict[str, Any],
        level: str = "INFO",
        source: str = "runtime",
    ) -> None:
        envelope = {
            "process_name": process_name,
            "source": source,
            "level": level,
            "event_type": event_type,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO app_process_events(process_name, source, level, event_type, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (process_name, source, level, event_type, dump_json(payload)),
            )
            conn.commit()
        finally:
            conn.close()
        self._event_bus.publish("runtime", StreamEvent(event=event_type, data=envelope))


def _infer_level_from_log_line(line: str) -> str:
    upper = line.upper()
    if "ERROR" in upper or "EXCEPTION" in upper or "TRACEBACK" in upper:
        return "ERROR"
    if "WARN" in upper:
        return "WARNING"
    if "DEBUG" in upper:
        return "DEBUG"
    return "INFO"
