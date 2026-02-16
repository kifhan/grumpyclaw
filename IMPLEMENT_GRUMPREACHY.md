# IMPLEMENTATION PLAN: `grumpyreachy`

## 1. Goal
Build a new app, `grumpyreachy`, to control Reachy Mini Lite and integrate it with `grumpyclaw` so the robot can:
1. keep memory + heartbeat context by observing environment,
2. provide feedback when `grumpyclaw` executes actions,
3. run direct conversation where `grumpyclaw` is exposed as an agent tool.

This plan uses `reachy_mini` as the blueprint for app lifecycle, connection model, and tool-driven robot actions.

## 2. Blueprint from `reachy_mini` (what to copy)

Use these existing patterns as-is:

- Client/server split:
  - Daemon handles robot IO and safety.
  - App/client handles high-level logic.
  - Reference: `reachy_mini/docs/source/SDK/core-concept.md`

- Auto connection and context-managed robot session:
  - `with ReachyMini() as mini:`
  - Localhost-first + network fallback behavior.
  - Reference: `reachy_mini/src/reachy_mini/reachy_mini.py`

- App wrapper lifecycle:
  - Start/stop event, graceful shutdown, optional web UI.
  - Reference: `reachy_mini/src/reachy_mini/apps/app.py`

- Single-app runtime management:
  - Run-state model (`STARTING/RUNNING/ERROR/...`) and monitored subprocess logs.
  - Reference: `reachy_mini/src/reachy_mini/apps/manager.py`

- LLM-to-tool-to-queue control pattern:
  - LLM calls tools, tool enqueues motion/task, control loop executes.
  - Reference: `reachy_mini/skills/ai-integration.md`

## 3. Target architecture for `grumpyreachy`

## 3.1 High-level components
- `grumpyreachy.app`:
  - Reachy app entrypoint and lifecycle.
  - Owns threads/tasks for perception, heartbeat bridge, and conversation.

- `grumpyreachy.robot_controller`:
  - Thin wrapper over `ReachyMini`.
  - Safe robot primitives (`look_at`, `nod`, `antenna_feedback`, `speak`).

- `grumpyreachy.observer`:
  - Environment observation pipeline (camera/audio summaries, optional pose state).
  - Produces compact `ObservationEvent` objects.

- `grumpyreachy.memory_bridge`:
  - Writes observation summaries into `grumpyclaw.memory` DB/index.
  - Retrieves relevant context for conversation + heartbeat.

- `grumpyreachy.heartbeat_bridge`:
  - Extends `grumpyclaw` heartbeat input with robot/environment context.
  - Converts heartbeat outputs into robot signals (voice/antenna/head gestures).

- `grumpyreachy.tool_adapter`:
  - Exposes `grumpyclaw` actions as callable tools from conversation flow.
  - Handles execution status events for robot feedback.

- `grumpyreachy.conversation`:
  - Session manager for direct user conversation.
  - Routes LLM tool calls to:
    - robot tools,
    - `grumpyclaw` tools,
    - memory retrieval tools.

## 3.2 Data flow
1. Sensors/UI input -> `observer`
2. `observer` summary -> `memory_bridge` (store/index)
3. Conversation asks question -> retrieve context from `grumpyclaw.memory`
4. LLM decides tool call:
   - robot actuation tool, or
   - `grumpyclaw` tool via `tool_adapter`
5. Tool execution events -> `feedback_manager` actions (voice + antennas + logs)
6. `heartbeat_bridge` runs periodic context check and proactive notification

## 4. Requirement mapping

## 4.1 Memory + heartbeat (observe environment)
- Implement observation loop every N seconds (start with 10 minutes).
- Summarize scene/audio into short text events.
- Store events in existing `grumpyclaw` SQLite/FTS/vector pipeline.
- Heartbeat prompt includes:
  - latest observations,
  - pending tasks,
  - recent user conversation intents.
- Heartbeat outputs:
  - `HEARTBEAT_OK`, or
  - proactive message + optional robot signal.

Acceptance:
- New observations are queryable in memory search.
- Heartbeat uses those observations and returns deterministic status shape.

## 4.2 Feedback when `grumpyclaw` executed
- Emit execution lifecycle events:
  - `tool_started`, `tool_progress`, `tool_succeeded`, `tool_failed`.
- Map each lifecycle to robot feedback:
  - start: attention gesture (small antenna move),
  - success: confirm gesture + short phrase,
  - failure: error gesture + concise reason.
- Log structured feedback records for audit.

Acceptance:
- Every `grumpyclaw` tool call triggers start + terminal feedback event.
- Failures are visible in logs and surfaced to user on robot channel.

## 4.3 Direct conversation + use `grumpyclaw` as agent tool
- Build conversation loop similar to Reachy tool pattern:
  - LLM never drives motors directly.
  - LLM calls tools; tools dispatch to queue/executors.
- Register `grumpyclaw` tool namespace into conversation runtime.
- Add minimum tool set:
  - `grumpyclaw.ask`,
  - `grumpyclaw.run_skill`,
  - `grumpyclaw.search_memory`,
  - `robot.look_at_user`,
  - `robot.express_status`.

Acceptance:
- During a live session, user can ask Reachy to run `grumpyclaw` tasks.
- Tool result is spoken/displayed and persisted in memory.

## 5. Implementation phases

## Phase 0: Scaffolding
- Create package: `src/grumpyreachy/`
- Add scripts:
  - `grumpyreachy-run`
  - `grumpyreachy-heartbeat`
  - `grumpyreachy-chat`
- Add config block in `.env.example`:
  - `GRUMPYREACHY_OBSERVE_INTERVAL`
  - `GRUMPYREACHY_FEEDBACK_ENABLED`
  - `GRUMPYREACHY_REACHY_MODE` (`lite` default)

## Phase 1: Robot + app lifecycle
- Implement app class with stop event and clean shutdown.
- Integrate `ReachyMini()` connection and basic health check.
- Add control queue worker (single consumer for motion/tool actions).

## Phase 2: Observation -> memory -> heartbeat
- Build observer loop and event schema.
- Write events into `grumpyclaw.memory`.
- Extend heartbeat script/context with observation digest.

## Phase 3: Tool bridge + feedback
- Wrap `grumpyclaw` functions as tool handlers.
- Add feedback event bus and robot feedback mappings.
- Ensure errors propagate with compact user-readable messages.

## Phase 4: Conversation integration
- Add session state, history, memory retrieval augmentation.
- Register robot + grumpyclaw tools in one tool registry.
- Add interrupt-safe execution (tool timeout + cancellation).

## Phase 5: Validation hardening
- Unit tests for tool adapter, feedback mapping, heartbeat context packer.
- Integration smoke test with mocked ReachyMini backend.
- Manual runbook for Reachy Mini Lite USB workflow.

## 6. Testing strategy

- Unit:
  - observation event serialization,
  - memory indexing/retrieval hooks,
  - tool execution lifecycle transitions.

- Integration:
  - start app -> run one `grumpyclaw` tool -> verify robot feedback.
  - heartbeat run -> confirm observation context included.
  - conversation call that invokes both robot and `grumpyclaw` tools.

- Safety/regression:
  - ensure no direct motor calls from LLM layer,
  - queue backpressure limits,
  - graceful stop restores neutral pose.

## 7. Risks and controls

- Latency spikes from LLM/tool calls:
  - Mitigation: queue-based execution + async timeouts.

- Noisy observation flooding memory:
  - Mitigation: deduplicate near-identical observations, throttle writes.

- Robot motion conflicts:
  - Mitigation: single motion executor, priority rules (stop > safety > gesture).

- Conversation/tool deadlocks:
  - Mitigation: strict tool timeout and cancellation tokens.

## 8. Definition of done (MVP)

MVP is done when all are true:
1. `grumpyreachy` connects to Reachy Mini Lite and runs stable app loop.
2. Observation events are stored in `grumpyclaw` memory and used by heartbeat.
3. `grumpyclaw` tool execution triggers robot feedback for success/failure.
4. Live conversation can invoke at least one `grumpyclaw` tool and return result.
5. Basic test suite and runbook exist for repeatable local execution.
