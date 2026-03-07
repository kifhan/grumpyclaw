# Companion App Reactive Behavior Plan

## Summary

Build a companion-behavior subsystem for the existing grumpyadmin stack so the robot can react automatically to social cues and stay active while idle.

The v1 behaviors are:

- `person_looked_at_robot`
- `person_called_robot`
- `robot_head_petted`
- `idle_heartbeat`
- `idle_patrol_find_person`

Core decisions:

- Detection is automatic and runs on the robot/backend side, not in the browser.
- The companion app is the configuration, status, and simulation surface.
- Reaction selection is AI-assisted at runtime, but the output is constrained to `play_emotion` or `dance`.
- Reactions do not interrupt active conversation or active motion. They queue and run next.
- Patrol mode is the lowest-priority idle behavior and exists to find a person before idle heartbeat expressions fire.

## Implementation Changes

### 1. Backend companion behavior service

Add a new API-owned companion behavior service that is started with the existing runtime and is responsible for:

- detector lifecycle
- companion config storage and validation
- trigger cooldowns and deduplication
- reaction selection
- patrol scheduling
- queueing and priority handling
- event history and SSE publication

Anchor it around the existing robot/runtime orchestration in:

- `api/backend/assistant/manager.py`
- `api/backend/robot_service.py`

This service should own the canonical state for:

- `enabled`
- detector availability
- current idle state
- current patrol state
- queued reaction state
- latest trigger and latest executed reaction

### 2. Trigger detection

Extend the robot runtime in `src/grumpyreachy/app.py` with detector adapters and event emission.

Required detectors:

- `LookDetector`
  - Uses robot camera input.
  - Emits `person_looked_at_robot` only after a stable dwell window.
  - Uses cooldown to suppress repeat triggers from the same sustained gaze.

- `CallDetector`
  - Uses robot microphone input.
  - Detects configurable wake phrases.
  - Emits `person_called_robot`.

- `PetDetector`
  - Reads a Reachy-side pet/touch signal from the head or mic-array path.
  - Emits `robot_head_petted`.
  - If the SDK hook is unavailable at runtime, report degraded or unavailable detector status without disabling the rest of the subsystem.

Required detector defaults:

- `look_dwell_ms = 1200`
- `look_cooldown_seconds = 8`
- `call_cooldown_seconds = 5`
- `pet_cooldown_seconds = 4`
- default wake phrases: `grumpy`, `grumpyclaw`, `reachy`

### 3. Idle state and patrol mode

Add a dedicated idle-state controller separate from the existing admin heartbeat scheduler.

Idle phases:

1. Normal idle
2. Patrol searching
3. Idle heartbeat eligible

Patrol mode rules:

- Start patrol when the robot has been idle and no person has been detected for `20` seconds by default.
- Patrol is the lowest-priority behavior in the system.
- Patrol uses the existing head movement path in `src/grumpyreachy/moves.py` and `src/grumpyreachy/tools/move_head.py`.
- Default scan pattern is:
  - `front`
  - `left`
  - `right`
  - `up`
  - `front`
- Default dwell per scan step is `1.0` second.
- Patrol stops immediately when:
  - a person is detected
  - conversation starts
  - any social reaction is queued
  - any manual robot action starts
  - the subsystem is disabled

Patrol-to-reaction handoff:

- If patrol finds a person, emit the same `person_looked_at_robot` trigger path used by normal look detection.
- Patrol itself never chooses a dance or emotion directly.

Idle heartbeat rules:

- Idle heartbeat uses a separate timer with default interval `90` seconds.
- Idle heartbeat only becomes eligible after at least one patrol sweep completed without finding a person.
- If an idle heartbeat reaction runs, patrol pauses and resumes afterward only if the robot is still idle and no person is present.

### 4. Reaction selection

Add a constrained reaction resolver using the existing text-model stack.

Resolver input:

- trigger type
- recent trigger history
- current idle or patrol state
- live motion catalog from the robot runtime
- optional detector confidence metadata

Resolver output must be strict JSON:

```json
{
  "action": "play_emotion",
  "name": "curious",
  "duration_seconds": 4.0
}
```

Allowed actions:

- `play_emotion`
- `dance`

Selection policy:

- Prefer `play_emotion` for `person_looked_at_robot`, `person_called_robot`, and `robot_head_petted`.
- Allow `dance` for `idle_heartbeat`.
- Allow `dance` for social triggers only when the model strongly favors a high-energy reaction and the queue is otherwise empty.
- Validate the returned `name` against the live motion catalog before queueing.

Fallback defaults:

- `person_looked_at_robot` -> `play_emotion("curious")`
- `person_called_robot` -> `play_emotion("happy")`
- `robot_head_petted` -> `play_emotion("happy")`
- `idle_heartbeat` -> `play_emotion("neutral")`

If the selected motion name is unavailable, map to the closest installed catalog name; if none match, use the current hardcoded safe defaults already present in the runtime.

### 5. Queueing and priority

Use the existing queue-based robot action path. Do not add a separate motor executor.

Priority order:

1. `robot_head_petted`
2. `person_called_robot`
3. `person_looked_at_robot`
4. `idle_heartbeat`
5. `idle_patrol_find_person`

Queueing policy:

- Never interrupt active conversation or active robot motion.
- Higher-priority triggers can replace lower-priority queued idle items that have not started yet.
- Keep at most one queued idle heartbeat reaction.
- Keep at most one active patrol job.
- Drop repeated low-priority idle events during a cooldown window.

### 6. Companion app UI

Add a new companion page to the existing React app.

The page must support:

- enable or disable subsystem
- show detector availability and degraded status
- edit wake phrases
- edit per-trigger cooldowns
- edit patrol timing and scan pattern
- edit allowed reaction types per trigger
- show current idle state, patrol state, queue state, latest trigger, and latest executed reaction
- show recent event history
- simulate each trigger for QA and demos

Simulation buttons are test-only and must emit the same internal event path as live detectors.

## Public APIs and Interfaces

Add new REST endpoints:

- `GET /api/v1/companion/config`
- `PUT /api/v1/companion/config`
- `GET /api/v1/companion/status`
- `GET /api/v1/companion/events`
- `POST /api/v1/companion/events/simulate`

Add SSE and log event types:

- `companion.trigger_detected`
- `companion.reaction_selected`
- `companion.reaction_queued`
- `companion.reaction_executed`
- `companion.detector_status`
- `companion.patrol_started`
- `companion.patrol_step`
- `companion.person_found`
- `companion.patrol_stopped`

Add typed enums or equivalent Pydantic models for:

- `CompanionTrigger = looked_at | called | petted | idle_heartbeat`
- `CompanionReactionAction = play_emotion | dance`
- `DetectorStatus = available | degraded | unavailable`
- `IdleMode = normal | patrol | heartbeat_ready`

Companion config shape:

- `enabled: bool`
- `idle_interval_seconds: int`
- `wake_phrases: list[str]`
- `queue_policy: "queue_next"`
- `patrol_enabled: bool`
- `patrol_start_after_seconds: int`
- `patrol_scan_pattern: list[str]`
- `patrol_step_duration_seconds: float`
- `triggers.looked_at.enabled: bool`
- `triggers.looked_at.cooldown_seconds: int`
- `triggers.looked_at.allowed_reaction_types: list[str]`
- `triggers.called.enabled: bool`
- `triggers.called.cooldown_seconds: int`
- `triggers.called.allowed_reaction_types: list[str]`
- `triggers.petted.enabled: bool`
- `triggers.petted.cooldown_seconds: int`
- `triggers.petted.allowed_reaction_types: list[str]`
- `triggers.idle_heartbeat.enabled: bool`
- `triggers.idle_heartbeat.cooldown_seconds: int`
- `triggers.idle_heartbeat.allowed_reaction_types: list[str]`

## Testing and Acceptance

Unit tests:

- gaze dwell and cooldown logic
- wake phrase matching and cooldown logic
- pet detector adapter status handling
- patrol step sequencing
- patrol stop conditions
- idle heartbeat eligibility after an unsuccessful patrol sweep
- AI reaction JSON parsing
- motion catalog validation and fallback selection
- trigger priority replacement of queued idle work

Integration tests:

- gaze detected while idle -> reaction selected and queued
- wake phrase detected during active motion -> reaction queued and played next
- pet detected while idle heartbeat is queued -> pet reaction replaces the queued idle action
- patrol starts after idle timeout with no detected person
- patrol stops as soon as a person is found
- patrol does not run during active conversation
- idle heartbeat does not fire before one unsuccessful patrol sweep
- patrol resumes after a heartbeat reaction when the robot is still alone
- unavailable pet detector surfaces degraded status while look and call detection still function
- simulated trigger path and live trigger path produce the same downstream event sequence

Acceptance criteria:

- Companion page shows live detector state and recent event history.
- Robot automatically reacts to look, call, and pet events when detectors are available.
- Robot enters patrol mode while idle and alone, then stops patrol immediately when a person is found.
- Idle heartbeat produces dance or emotion only after patrol has already tried to find a person.
- No companion-triggered behavior interrupts an active conversation turn or active robot motion.

## Assumptions and Defaults

- The companion app is a new page inside the existing `web/` app, not a separate mobile app.
- Detection runs on robot-connected hardware and backend services, not on browser devices.
- Head-pet detection is expected to come from Reachy head or mic-array hardware; the software must tolerate missing SDK support and surface degraded status.
- The existing `dance` and `play_emotion` actions remain the only v1 motion outputs for this feature.
- The existing admin heartbeat scheduler remains unchanged and separate from the new companion idle timer.
- The implementation should reuse existing robot movement and action queues rather than adding a parallel control pipeline.
