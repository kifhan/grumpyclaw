# Realtime Function-Calling Upgrade (Camera Context, Expressive Actions, Personal Memory)

## Summary
1. Align the server-side realtime tool loop with current OpenAI Realtime guidance for image input plus function-call output sequencing.
2. Add `capture_camera_context` and `save_memory` tools in the API realtime path.
3. Keep `robot_action` as the single robot control tool and extend its action enum for expressive motions.
4. Add temporary camera image file caching with auto-expiry (7-day TTL), while preventing raw image payload persistence in DB/SSE.
5. Add dedicated realtime instructions so model behavior is consistent for camera grounding, memory save/load, and expressive gestures.
6. Ship with focused unit/API tests and no database migration.

## Public Interfaces And Type Changes
1. Update tool definitions in [tools.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/tools.py): add `capture_camera_context` (no required args), add `save_memory` (required `memory` string), and extend `robot_action.action` enum with `play_emotion`, `stop_emotion`, `dance`, `stop_dance`.
2. Update robot action models in [models.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/models.py): extend `RobotActionName` with the four expressive actions, and add optional `name` plus `duration` fields for expressive action parameters.
3. Update realtime service constructor and session setup in [realtime_service.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/realtime_service.py): add `instructions: str` input and include it in `session.update`.
4. Add API config fields in [config.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/config.py): `GRUMPYADMIN_REALTIME_IMAGE_CACHE_DIR` (default `data/realtime_image_cache`) and `GRUMPYADMIN_REALTIME_IMAGE_CACHE_TTL_SECONDS` (default `604800`).
5. Keep HTTP endpoints unchanged in [assistant.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/routers/assistant.py) and [robot.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/routers/robot.py).

## Implementation Plan
1. Add a transient image cache module [image_cache.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/image_cache.py) implementing `store_jpeg`, `purge_expired`, and data-URL conversion; use UUID filenames, create cache dir on demand, purge expired files on each store call and once at realtime start.
2. Extend `ToolDispatcher` in [tools.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/tools.py) to support dependency injection for retriever/indexer/image-cache so tests can stub heavy dependencies.
3. Implement `_capture_camera_context` in [tools.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/tools.py); read JPEG bytes from the running robot app camera worker, cache the file, return internal `image_data_url` plus metadata (`cache_file`, `byte_size`, `mime_type`, `created_at`, `expires_at`), and return structured errors for unavailable camera/frame/cache failure.
4. Implement `_save_memory` in [tools.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/tools.py); normalize memory text, compute deterministic SHA-256-based `memory_id`, index with `source_type="personal_memory"`, detect dedupe via existing `source_id`, and block sensitive content using explicit regex checks (secret keywords, `sk-...` style keys, PEM private-key headers).
5. Extend `_robot_action` payload handling in [tools.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/tools.py) to pass through expressive fields (`name`, `duration`) while preserving existing behavior for current actions.
6. Add robot service helpers in [robot_service.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/robot_service.py) to expose camera worker and movement manager safely, and extend `_to_control_action` mapping for `play_emotion`, `stop_emotion`, `dance`, `stop_dance`.
7. Extend action execution in [app.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/src/grumpyreachy/app.py) so expressive control actions route to `MovementManager` methods `queue_emotion`, `clear_emotion_queue`, `queue_dance`, and `clear_dance_queue`.
8. Update tool dispatch flow in [realtime_service.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/realtime_service.py): execute tool, sanitize output copy, if `image_data_url` exists create a user `message` item with `input_image`, remove raw image field from emitted/stored payload, send `function_call_output`, then call `response.create` exactly once.
9. Add robust failure behavior in [realtime_service.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/realtime_service.py): if image injection fails, still send `function_call_output` with an `image_injection_error` field and continue to `response.create` so the conversation loop never stalls.
10. Add a realtime-specific instruction builder in [manager.py](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/api/backend/assistant/manager.py), pass it into realtime service, and enforce these rules: use camera tool for visual grounding, use expressive robot actions contextually, call `save_memory` for stable personal facts, and call `search_memory` for follow-up recall.
11. Update docs and env templates in [README.md](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/README.md) and [.env.example](/Users/darter/Workplace/grumpydarter_project/grumpyclaw/.env.example) with new tool behavior, image-cache retention settings, and memory-save policy.

## Test Cases And Scenarios
1. Verify tool definitions include `capture_camera_context`, `save_memory`, and the extended `robot_action` enum.
2. Verify camera capture success path returns metadata plus internal `image_data_url` and writes a cache file.
3. Verify camera capture failure paths for missing app, missing camera worker, empty frame, and cache write exception.
4. Verify cache expiry cleanup removes only expired files and preserves fresh files.
5. Verify memory save returns deterministic `memory_id`, `stored=true`, and `deduped=false` on first write.
6. Verify repeated normalized memory returns same `memory_id` and `deduped=true`.
7. Verify sensitive memory strings are blocked and indexer is not called.
8. Verify realtime dispatch call order with image is `input_image` item, then `function_call_output`, then one `response.create`.
9. Verify realtime dispatch sanitizes raw image fields from `assistant.tool` events and DB-persisted realtime events.
10. Verify realtime dispatch without image still does `function_call_output` plus one `response.create`.
11. Verify expressive action mapping in robot service produces correct `ControlAction` names and payload defaults.
12. Verify `/api/v1/robot/actions` accepts new expressive enum values at request-validation layer.

## Rollout And Validation
1. Run focused tests for realtime/robot/tool changes first, then run full `api/tests` suite.
2. Perform a manual realtime smoke run: trigger camera tool, confirm timeline shows metadata-only output and no base64 blob.
3. Perform manual expressive-action smoke run: trigger emotion/dance actions and verify movement manager queue behavior.
4. Monitor runtime logs for payload size and confirm no raw image data appears in `assistant.tool` event storage.

## Assumptions And Defaults
1. “A week” retention is implemented as exactly `604800` seconds.
2. Temporary image persistence is file-cache only; raw image data is not stored in `app_realtime_events` or SSE payloads.
3. Cleanup strategy is opportunistic on capture and realtime start; no new background cleanup thread.
4. Personal memory save remains model-driven via `save_memory`; backend does not auto-extract user facts independently.
5. Existing DB schema is sufficient; no migration is required.
6. Existing endpoints remain unchanged.

## Protocol References
1. https://platform.openai.com/docs/guides/realtime-conversations#image-inputs
2. https://platform.openai.com/docs/guides/realtime-conversations#function-calling
3. https://platform.openai.com/docs/guides/realtime-conversations#provide-the-results-of-a-function-call-to-the-model
4. https://platform.openai.com/docs/guides/realtime#function-call-output
