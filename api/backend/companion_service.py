from __future__ import annotations

import difflib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .db import dump_json, get_conn, load_json
from .event_bus import EventBus, StreamEvent
from .models import CompanionConfig

LOG = logging.getLogger("grumpyadmin.companion")

_SOCIAL_TRIGGERS = {"looked_at", "called", "petted"}
_TRIGGER_PRIORITY = {
    "petted": 1,
    "called": 2,
    "looked_at": 3,
    "idle_heartbeat": 4,
}
_REACTION_DEFAULTS = {
    "looked_at": {"action": "play_emotion", "name": "curious", "duration_seconds": 4.0},
    "called": {"action": "play_emotion", "name": "happy", "duration_seconds": 4.0},
    "petted": {"action": "play_emotion", "name": "happy", "duration_seconds": 4.0},
    "idle_heartbeat": {"action": "play_emotion", "name": "neutral", "duration_seconds": 4.0},
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _QueuedReaction:
    trigger: str
    action: str
    name: str
    duration_seconds: float
    priority: int
    source: str
    confidence: float | None
    queued_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "action": self.action,
            "name": self.name,
            "duration_seconds": self.duration_seconds,
            "priority": self.priority,
            "source": self.source,
            "confidence": self.confidence,
            "queued_at": self.queued_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class _ActiveReaction:
    trigger: str
    action: str
    name: str
    duration_seconds: float
    source: str
    started_at: str
    action_id: str
    expected_end_monotonic: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "action": self.action,
            "name": self.name,
            "duration_seconds": self.duration_seconds,
            "source": self.source,
            "started_at": self.started_at,
            "action_id": self.action_id,
        }


class CompanionService:
    """Idle/social behavior orchestration for the robot runtime."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        config: Any,
        robot_service: Any,
        conversation_active: Callable[[], bool] | None = None,
        reaction_resolver: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    ):
        self._event_bus = event_bus
        self._robot_service = robot_service
        self._conversation_active = conversation_active or (lambda: False)
        self._reaction_resolver = reaction_resolver

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._config_model = self._load_config()
        now = time.monotonic()
        self._last_presence_monotonic = now
        self._last_idle_block_monotonic = now
        self._last_idle_heartbeat_monotonic = 0.0
        self._last_trigger_monotonic: dict[str, float] = {}
        self._recent_trigger_history: list[dict[str, Any]] = []

        self._queued_reaction: _QueuedReaction | None = None
        self._active_reaction: _ActiveReaction | None = None
        self._latest_trigger: dict[str, Any] | None = None
        self._latest_executed_reaction: dict[str, Any] | None = None

        self._idle_mode = "normal"
        self._patrol_active = False
        self._patrol_step_index = 0
        self._patrol_sweeps_completed = 0
        self._patrol_started_at: str | None = None
        self._patrol_stopped_at: str | None = None
        self._patrol_last_step_at: str | None = None
        self._patrol_stop_reason = ""
        self._patrol_next_step_monotonic = 0.0
        self._patrol_step_active_until = 0.0
        self._resume_patrol_after_reaction = False

        self._detector_statuses: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="companion-service", daemon=True)
            self._thread.start()
        self._refresh_detector_status(force=True)

    def shutdown(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            return self._config_model.model_dump()

    def update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = CompanionConfig.model_validate(payload)
        self._persist_config(config)
        with self._lock:
            self._config_model = config
            if not config.enabled or not config.patrol_enabled:
                self._stop_patrol_locked(reason="disabled")
            if not config.enabled:
                self._queued_reaction = None
                self._recompute_idle_mode_locked()
        self._refresh_detector_status(force=True)
        return config.model_dump()

    def status(self) -> dict[str, Any]:
        robot_status = self._robot_service.status()
        movement_status = self._robot_service.movement_status()
        conversation_active = bool(self._conversation_active())
        with self._lock:
            return {
                "enabled": self._config_model.enabled,
                "idle_mode": self._idle_mode,
                "detectors": {name: dict(state) for name, state in self._detector_statuses.items()},
                "patrol": {
                    "active": self._patrol_active,
                    "step_index": self._patrol_step_index,
                    "sweeps_completed": self._patrol_sweeps_completed,
                    "started_at": self._patrol_started_at,
                    "stopped_at": self._patrol_stopped_at,
                    "last_step_at": self._patrol_last_step_at,
                    "stop_reason": self._patrol_stop_reason,
                },
                "queue": {
                    "queued_reaction": self._queued_reaction.to_dict() if self._queued_reaction else None,
                    "active_reaction": self._active_reaction.to_dict() if self._active_reaction else None,
                },
                "latest_trigger": dict(self._latest_trigger) if self._latest_trigger else None,
                "latest_executed_reaction": (
                    dict(self._latest_executed_reaction) if self._latest_executed_reaction else None
                ),
                "conversation_active": conversation_active,
                "robot": robot_status,
                "movement": movement_status,
                "ts": _utcnow(),
            }

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, event_type, payload_json, created_at
                FROM app_companion_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            items = [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "payload": load_json(row["payload_json"]),
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
            items.reverse()
            return items
        finally:
            conn.close()

    def simulate_trigger(self, trigger: str, confidence: float | None = None) -> dict[str, Any]:
        result = self.handle_trigger(
            trigger,
            source="simulation",
            confidence=confidence,
            metadata={"simulated": True},
        )
        result["status"] = self.status()
        return result

    def handle_trigger(
        self,
        trigger: str,
        *,
        source: str,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload_meta = dict(metadata or {})
        trigger_name = str(trigger or "").strip().lower()
        now = time.monotonic()
        ts = _utcnow()

        with self._lock:
            config_model = self._config_model
            trigger_cfg = getattr(config_model.triggers, trigger_name, None)
            if trigger_cfg is None:
                raise ValueError(f"unsupported trigger: {trigger_name}")

            event_payload = {
                "trigger": trigger_name,
                "source": source,
                "confidence": confidence,
                "metadata": payload_meta,
                "ts": ts,
                "accepted": False,
                "reason": "",
            }
            if not config_model.enabled:
                event_payload["reason"] = "subsystem_disabled"
                self._publish_event("companion.trigger_detected", event_payload, level="WARNING")
                return {"accepted": False, "reason": "subsystem_disabled"}

            if not trigger_cfg.enabled:
                event_payload["reason"] = "trigger_disabled"
                self._publish_event("companion.trigger_detected", event_payload, level="WARNING")
                return {"accepted": False, "reason": "trigger_disabled"}

            cooldown = max(0.0, float(trigger_cfg.cooldown_seconds))
            last_seen = self._last_trigger_monotonic.get(trigger_name, 0.0)
            if cooldown > 0.0 and (now - last_seen) < cooldown:
                event_payload["reason"] = "cooldown_active"
                self._publish_event("companion.trigger_detected", event_payload, level="INFO")
                return {"accepted": False, "reason": "cooldown_active"}

            self._last_trigger_monotonic[trigger_name] = now
            event_payload["accepted"] = True
            self._latest_trigger = dict(event_payload)
            if trigger_name in _SOCIAL_TRIGGERS:
                self._last_presence_monotonic = now
                self._patrol_sweeps_completed = 0
                self._resume_patrol_after_reaction = False
                if self._patrol_active:
                    if source == "patrol":
                        self._publish_event(
                            "companion.person_found",
                            {"trigger": trigger_name, "source": source, "ts": ts},
                        )
                    self._stop_patrol_locked(reason="person_detected")
            self._recent_trigger_history.append(
                {
                    "trigger": trigger_name,
                    "source": source,
                    "confidence": confidence,
                    "ts": ts,
                }
            )
            self._recent_trigger_history = self._recent_trigger_history[-10:]
            self._publish_event("companion.trigger_detected", event_payload)

            resolved = self._resolve_reaction_locked(
                trigger=trigger_name,
                source=source,
                confidence=confidence,
                trigger_config=trigger_cfg.model_dump(),
            )
            selected_payload = {
                "trigger": trigger_name,
                "source": source,
                "reaction": dict(resolved),
                "ts": _utcnow(),
            }
            self._publish_event("companion.reaction_selected", selected_payload)

            queued = _QueuedReaction(
                trigger=trigger_name,
                action=str(resolved["action"]),
                name=str(resolved["name"]),
                duration_seconds=float(resolved["duration_seconds"]),
                priority=int(_TRIGGER_PRIORITY[trigger_name]),
                source=source,
                confidence=confidence,
                queued_at=_utcnow(),
                metadata=payload_meta,
            )

            if self._queued_reaction is not None:
                if self._can_replace_queued_locked(new_reaction=queued, old_reaction=self._queued_reaction):
                    replaced = self._queued_reaction.to_dict()
                    self._queued_reaction = queued
                    self._last_idle_block_monotonic = now
                    self._publish_event(
                        "companion.reaction_queued",
                        {
                            "accepted": True,
                            "replaced": replaced,
                            "reaction": queued.to_dict(),
                            "ts": _utcnow(),
                        },
                    )
                    return {"accepted": True, "queued": queued.to_dict(), "replaced": replaced}

                self._publish_event(
                    "companion.reaction_queued",
                    {
                        "accepted": False,
                        "reason": "queue_occupied",
                        "reaction": queued.to_dict(),
                        "queued_reaction": self._queued_reaction.to_dict(),
                        "ts": _utcnow(),
                    },
                    level="INFO",
                )
                return {"accepted": False, "reason": "queue_occupied"}

            self._queued_reaction = queued
            self._last_idle_block_monotonic = now
            if self._patrol_active:
                self._stop_patrol_locked(reason="reaction_queued")
            self._publish_event(
                "companion.reaction_queued",
                {"accepted": True, "reaction": queued.to_dict(), "ts": _utcnow()},
            )
            self._recompute_idle_mode_locked()
            return {"accepted": True, "queued": queued.to_dict()}

    def _loop(self) -> None:
        next_detector_refresh = 0.0
        while not self._stop.wait(timeout=0.25):
            try:
                now = time.monotonic()
                if now >= next_detector_refresh:
                    self._refresh_detector_status()
                    next_detector_refresh = now + 2.0
                self._tick()
            except Exception:
                LOG.exception("Companion loop tick failed")

    def _tick(self) -> None:
        now = time.monotonic()
        conversation_active = bool(self._conversation_active())
        movement_status = self._robot_service.movement_status()
        motion_busy = self._motion_busy(movement_status)

        with self._lock:
            self._clear_completed_reaction_locked(now)
            config_model = self._config_model
            if not config_model.enabled:
                self._stop_patrol_locked(reason="disabled")
                self._recompute_idle_mode_locked()
                return

            if conversation_active or motion_busy or self._queued_reaction or self._active_reaction:
                self._last_idle_block_monotonic = now
                if conversation_active or self._manual_motion_busy(now, movement_status):
                    self._patrol_sweeps_completed = 0
                    if self._patrol_active and (conversation_active or self._manual_motion_busy(now, movement_status)):
                        reason = "conversation_active" if conversation_active else "robot_motion_active"
                        self._stop_patrol_locked(reason=reason)

            if self._queued_reaction and not conversation_active and not self._manual_motion_busy(now, movement_status):
                self._dispatch_queued_reaction_locked(now)
                self._recompute_idle_mode_locked()
                return

            if self._patrol_active:
                if self._queued_reaction or conversation_active or self._manual_motion_busy(now, movement_status):
                    reason = "conversation_active" if conversation_active else "robot_motion_active"
                    if self._queued_reaction:
                        reason = "reaction_queued"
                    self._stop_patrol_locked(reason=reason)
                else:
                    self._advance_patrol_locked(now)
                    if self._should_queue_idle_heartbeat_locked(now):
                        self._stop_patrol_locked(reason="idle_heartbeat")
                        self._queue_idle_heartbeat_locked(now)
                self._recompute_idle_mode_locked()
                return

            if self._should_queue_idle_heartbeat_locked(now):
                self._queue_idle_heartbeat_locked(now)
                self._recompute_idle_mode_locked()
                return

            if self._should_start_patrol_locked(now, conversation_active, movement_status):
                self._start_patrol_locked(now)
            self._recompute_idle_mode_locked()

    def _load_config(self) -> CompanionConfig:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT config_json FROM app_companion_config WHERE id = 1",
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return CompanionConfig()
        try:
            return CompanionConfig.model_validate(load_json(row["config_json"]))
        except Exception:
            LOG.warning("Failed to load companion config, using defaults", exc_info=True)
            return CompanionConfig()

    def _persist_config(self, config: CompanionConfig) -> None:
        ts = _utcnow()
        conn = get_conn()
        try:
            conn.execute(
                """
                INSERT INTO app_companion_config(id, config_json, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET config_json = excluded.config_json, updated_at = excluded.updated_at
                """,
                (dump_json(config.model_dump()), ts),
            )
            conn.commit()
        finally:
            conn.close()

    def _publish_event(self, event_type: str, payload: dict[str, Any], level: str = "INFO") -> None:
        ts = str(payload.get("ts", "") or _utcnow())
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO app_companion_events(event_type, payload_json, created_at) VALUES (?, ?, ?)",
                (event_type, dump_json(payload), ts),
            )
            conn.execute(
                """
                INSERT INTO app_process_events(process_name, source, level, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("companion", "companion", level.upper(), event_type, dump_json(payload), ts),
            )
            conn.commit()
        finally:
            conn.close()
        self._event_bus.publish("companion", StreamEvent(event=event_type, data=payload))

    def _resolve_reaction_locked(
        self,
        *,
        trigger: str,
        source: str,
        confidence: float | None,
        trigger_config: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = [
            item
            for item in trigger_config.get("allowed_reaction_types", [])
            if item in {"play_emotion", "dance"}
        ]
        default = self._default_reaction(trigger, allowed)
        catalog = self._robot_service.get_motion_catalog()
        context = {
            "trigger": trigger,
            "source": source,
            "confidence": confidence,
            "allowed_reaction_types": list(allowed),
            "idle_mode": self._idle_mode,
            "recent_trigger_history": list(self._recent_trigger_history[-5:]),
            "patrol": {
                "active": self._patrol_active,
                "sweeps_completed": self._patrol_sweeps_completed,
            },
            "motion_catalog": catalog,
            "default_reaction": default,
        }

        candidate: dict[str, Any] = {}
        if callable(self._reaction_resolver):
            try:
                resolved = self._reaction_resolver(context)
                if isinstance(resolved, dict):
                    candidate = dict(resolved)
            except Exception:
                LOG.warning("Companion reaction resolver failed; falling back", exc_info=True)

        action = str(candidate.get("action", default["action"])).strip()
        if action not in {"play_emotion", "dance"} or (allowed and action not in allowed):
            action = str(default["action"])

        requested_name = str(candidate.get("name", default["name"])).strip() or str(default["name"])
        duration_seconds = self._coerce_duration(
            candidate.get("duration_seconds"),
            default=float(default["duration_seconds"]),
        )
        resolved_name = self._match_motion_name(action=action, requested=requested_name, catalog=catalog)
        return {
            "action": action,
            "name": resolved_name,
            "duration_seconds": duration_seconds,
        }

    def _default_reaction(self, trigger: str, allowed: list[str]) -> dict[str, Any]:
        base = dict(_REACTION_DEFAULTS[trigger])
        if allowed and base["action"] not in allowed:
            base["action"] = allowed[0]
        if base["action"] == "dance" and not str(base.get("name", "")).strip():
            base["name"] = "default"
        return base

    def _match_motion_name(self, *, action: str, requested: str, catalog: dict[str, Any]) -> str:
        requested_name = requested.strip()
        fallback_name = str(_REACTION_DEFAULTS["idle_heartbeat" if action == "dance" else "looked_at"]["name"])
        available = list(catalog.get("dances" if action == "dance" else "emotions", []))
        if not available:
            if action == "dance":
                return requested_name or "default"
            return requested_name or "neutral"

        exact_index = {name.lower(): name for name in available}
        if requested_name.lower() in exact_index:
            return exact_index[requested_name.lower()]

        requested_lower = requested_name.lower()
        for name in available:
            lowered = name.lower()
            if requested_lower and (requested_lower in lowered or lowered in requested_lower):
                return name

        candidates = difflib.get_close_matches(requested_name.lower(), list(exact_index.keys()), n=1, cutoff=0.4)
        if candidates:
            return exact_index[candidates[0]]

        fallback_candidates = {
            "play_emotion": ["curious", "happy", "neutral", fallback_name],
            "dance": ["celebration", "default", requested_name],
        }[action]
        for fallback in fallback_candidates:
            lowered = fallback.lower()
            if lowered in exact_index:
                return exact_index[lowered]
            for name in available:
                if lowered and lowered in name.lower():
                    return name
        return available[0]

    @staticmethod
    def _coerce_duration(value: Any, *, default: float) -> float:
        try:
            duration = float(value)
        except (TypeError, ValueError):
            duration = default
        if duration <= 0.0:
            return default
        return min(duration, 30.0)

    def _can_replace_queued_locked(self, *, new_reaction: _QueuedReaction, old_reaction: _QueuedReaction) -> bool:
        if old_reaction.trigger != "idle_heartbeat":
            return False
        return new_reaction.priority < old_reaction.priority

    def _dispatch_queued_reaction_locked(self, now: float) -> None:
        queued = self._queued_reaction
        if queued is None:
            return
        self._queued_reaction = None
        result = self._robot_service.enqueue_action(
            {
                "action": queued.action,
                "name": queued.name,
                "duration": queued.duration_seconds,
            },
            source="companion",
        )
        payload = {
            "reaction": queued.to_dict(),
            "accepted": result.accepted,
            "action_id": result.action_id,
            "reason": result.reason,
            "ts": _utcnow(),
        }
        if result.accepted:
            self._active_reaction = _ActiveReaction(
                trigger=queued.trigger,
                action=queued.action,
                name=queued.name,
                duration_seconds=queued.duration_seconds,
                source=queued.source,
                started_at=payload["ts"],
                action_id=result.action_id,
                expected_end_monotonic=now + queued.duration_seconds + 0.25,
            )
            self._latest_executed_reaction = {
                **queued.to_dict(),
                "action_id": result.action_id,
                "started_at": payload["ts"],
            }
            self._last_idle_block_monotonic = now
            if queued.trigger == "idle_heartbeat":
                self._last_idle_heartbeat_monotonic = now
                self._resume_patrol_after_reaction = True
            else:
                self._resume_patrol_after_reaction = False
        self._publish_event(
            "companion.reaction_executed",
            payload,
            level="INFO" if result.accepted else "WARNING",
        )

    def _clear_completed_reaction_locked(self, now: float) -> None:
        active = self._active_reaction
        if active is None:
            return
        if now < active.expected_end_monotonic:
            return
        self._active_reaction = None

    def _should_start_patrol_locked(
        self,
        now: float,
        conversation_active: bool,
        movement_status: dict[str, Any],
    ) -> bool:
        if self._patrol_active or self._queued_reaction or self._active_reaction:
            return False
        if conversation_active or self._manual_motion_busy(now, movement_status):
            return False
        config_model = self._config_model
        if not config_model.patrol_enabled:
            return False
        if self._resume_patrol_after_reaction and self._patrol_sweeps_completed >= 1:
            return True
        idle_gate = max(self._last_presence_monotonic, self._last_idle_block_monotonic)
        return (now - idle_gate) >= float(config_model.patrol_start_after_seconds)

    def _start_patrol_locked(self, now: float) -> None:
        self._patrol_active = True
        self._patrol_step_index = 0
        self._patrol_started_at = _utcnow()
        self._patrol_stopped_at = None
        self._patrol_stop_reason = ""
        self._patrol_next_step_monotonic = now
        self._patrol_step_active_until = 0.0
        self._publish_event(
            "companion.patrol_started",
            {
                "scan_pattern": list(self._config_model.patrol_scan_pattern),
                "step_duration_seconds": self._config_model.patrol_step_duration_seconds,
                "ts": self._patrol_started_at,
            },
        )

    def _advance_patrol_locked(self, now: float) -> None:
        if now < self._patrol_next_step_monotonic:
            return

        scan_pattern = list(self._config_model.patrol_scan_pattern)
        if not scan_pattern:
            scan_pattern = ["front"]
        direction = str(scan_pattern[self._patrol_step_index % len(scan_pattern)])
        duration = float(self._config_model.patrol_step_duration_seconds)
        result = self._robot_service.enqueue_action(
            {"action": "move_head", "direction": direction, "duration": duration},
            source="companion",
            bypass_rate_limit=True,
        )
        ts = _utcnow()
        self._patrol_last_step_at = ts
        self._publish_event(
            "companion.patrol_step",
            {
                "direction": direction,
                "step_index": self._patrol_step_index,
                "accepted": result.accepted,
                "action_id": result.action_id,
                "reason": result.reason,
                "ts": ts,
            },
            level="INFO" if result.accepted else "WARNING",
        )
        self._patrol_step_active_until = now + duration + 0.1
        self._patrol_next_step_monotonic = self._patrol_step_active_until
        self._patrol_step_index += 1
        if self._patrol_step_index >= len(scan_pattern):
            self._patrol_step_index = 0
            self._patrol_sweeps_completed += 1

    def _stop_patrol_locked(self, *, reason: str) -> None:
        if not self._patrol_active:
            return
        self._patrol_active = False
        self._patrol_step_index = 0
        self._patrol_next_step_monotonic = 0.0
        self._patrol_step_active_until = 0.0
        self._patrol_stopped_at = _utcnow()
        self._patrol_stop_reason = reason
        self._publish_event(
            "companion.patrol_stopped",
            {
                "reason": reason,
                "sweeps_completed": self._patrol_sweeps_completed,
                "ts": self._patrol_stopped_at,
            },
        )

    def _should_queue_idle_heartbeat_locked(self, now: float) -> bool:
        if self._queued_reaction or self._active_reaction:
            return False
        if not self._config_model.triggers.idle_heartbeat.enabled:
            return False
        if self._patrol_sweeps_completed < 1:
            return False
        cooldown = float(self._config_model.triggers.idle_heartbeat.cooldown_seconds)
        last_seen = self._last_trigger_monotonic.get("idle_heartbeat", 0.0)
        if cooldown > 0.0 and (now - last_seen) < cooldown:
            return False
        return (now - self._last_idle_heartbeat_monotonic) >= float(self._config_model.idle_interval_seconds)

    def _queue_idle_heartbeat_locked(self, now: float) -> None:
        self._last_trigger_monotonic["idle_heartbeat"] = now
        self._latest_trigger = {
            "trigger": "idle_heartbeat",
            "source": "idle_scheduler",
            "confidence": None,
            "metadata": {},
            "ts": _utcnow(),
            "accepted": True,
            "reason": "",
        }
        self._publish_event("companion.trigger_detected", dict(self._latest_trigger))
        resolved = self._resolve_reaction_locked(
            trigger="idle_heartbeat",
            source="idle_scheduler",
            confidence=None,
            trigger_config=self._config_model.triggers.idle_heartbeat.model_dump(),
        )
        self._publish_event(
            "companion.reaction_selected",
            {
                "trigger": "idle_heartbeat",
                "source": "idle_scheduler",
                "reaction": dict(resolved),
                "ts": _utcnow(),
            },
        )
        self._queued_reaction = _QueuedReaction(
            trigger="idle_heartbeat",
            action=str(resolved["action"]),
            name=str(resolved["name"]),
            duration_seconds=float(resolved["duration_seconds"]),
            priority=int(_TRIGGER_PRIORITY["idle_heartbeat"]),
            source="idle_scheduler",
            confidence=None,
            queued_at=_utcnow(),
            metadata={},
        )
        self._publish_event(
            "companion.reaction_queued",
            {"accepted": True, "reaction": self._queued_reaction.to_dict(), "ts": _utcnow()},
        )

    def _manual_motion_busy(self, now: float, movement_status: dict[str, Any]) -> bool:
        if not self._motion_busy(movement_status):
            return False
        if self._patrol_active and now <= self._patrol_step_active_until:
            return False
        return True

    @staticmethod
    def _motion_busy(movement_status: dict[str, Any]) -> bool:
        if not movement_status.get("available"):
            return False
        return bool(
            movement_status.get("control_queue_size", 0)
            or movement_status.get("primary_queue_size", 0)
            or movement_status.get("active_interrupting", False)
        )

    def _recompute_idle_mode_locked(self) -> None:
        if self._patrol_active:
            self._idle_mode = "heartbeat_ready" if self._patrol_sweeps_completed >= 1 else "patrol"
            return
        if self._patrol_sweeps_completed >= 1 and not self._queued_reaction and not self._active_reaction:
            self._idle_mode = "heartbeat_ready"
            return
        self._idle_mode = "normal"

    def _refresh_detector_status(self, force: bool = False) -> None:
        statuses = self._compute_detector_status()
        with self._lock:
            if not force and statuses == self._detector_statuses:
                return
            self._detector_statuses = statuses
        self._publish_event(
            "companion.detector_status",
            {"detectors": statuses, "ts": _utcnow()},
        )

    def _compute_detector_status(self) -> dict[str, dict[str, Any]]:
        ts = _utcnow()
        camera_worker = self._robot_service.get_camera_worker()
        audio_status = self._robot_service.get_audio_device_status()

        look_status = {
            "status": "degraded" if camera_worker is not None else "unavailable",
            "detail": (
                "camera ready; live look detector still needs runtime adapter wiring"
                if camera_worker is not None
                else "camera worker unavailable"
            ),
            "updated_at": ts,
        }
        call_status = {
            "status": "degraded" if audio_status.get("configured") else "unavailable",
            "detail": (
                "audio ready; wake-phrase detector still needs runtime adapter wiring"
                if audio_status.get("configured")
                else str(audio_status.get("reason", "audio input unavailable"))
            ),
            "updated_at": ts,
        }
        pet_status = {
            "status": "unavailable",
            "detail": "Reachy pet/touch hook not exposed by the current runtime",
            "updated_at": ts,
        }
        return {
            "look_detector": look_status,
            "call_detector": call_status,
            "pet_detector": pet_status,
        }
