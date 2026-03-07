# grumpyClaw + grumpyreachy

Centralized stack with one primary entrypoint: `grumpyadmin-api`.

- Text assistant: OpenAI Responses API (`gpt-5-mini` by default)
- Robot realtime conversation: OpenAI Realtime WebSocket (`gpt-realtime` by default)
- Heartbeat: in-process scheduler managed by API runtime
- Web UI: React app using unified `/api/v1/assistant/*` endpoints

## 1. Install

1. Install `uv`
2. From repo root: `uv sync`
3. Copy `.env.example` to `.env`

## 2. Configure `.env`

Required:
- `OPENAI_API_KEY=...`

Recommended defaults:
- `OPENAI_TEXT_MODEL=gpt-5-mini`
- `OPENAI_REALTIME_MODEL=gpt-realtime`
- `HEARTBEAT_INTERVAL_SECONDS=1800`

Optional:
- `OPENAI_BASE_URL=...`
- `OPENAI_CA_BUNDLE=/path/to/ca-bundle.pem` (optional TLS CA bundle for custom trust chains)
- `GRUMPYCLAW_DB_PATH=...`
- `GRUMPYCLAW_EMBEDDING_CACHE_DIR=data/fastembed_cache` (persistent FastEmbed model cache; avoids OS temp-dir eviction issues)
- `GRUMPYCLAW_SKILLS_DIR=...`
- `GRUMPYREACHY_REALTIME_INPUT_GAIN=1.0`
- `GRUMPYREACHY_REALTIME_OUTPUT_GAIN=1.8` (increase if speech is quiet)
- `GRUMPYREACHY_REALTIME_MIC_SUPPRESSION_SECONDS=0.35` (mute mic briefly while robot speaker audio is playing to reduce acoustic feedback; set `0` to disable)
- `GRUMPYREACHY_REALTIME_TALK_OVERLAP_MODE=strict_anti_loop` (`strict_anti_loop`, `balanced`, `barge_in`; default is strict anti-loop for loopback stability)
- `GRUMPYREACHY_REALTIME_POST_PLAYBACK_HOLD_SECONDS=0.9` (strict anti-loop tail hold after assistant playback)
- `GRUMPYREACHY_REALTIME_VOICE_EFFECT_MODE=chipmunk` (`chipmunk` for pitch-up robot voice, `none` to disable)
- `GRUMPYREACHY_REALTIME_AEC_ENABLED=true` (enable built-in reference-based echo suppression)
- `GRUMPYREACHY_REALTIME_AEC_DELAY_MS=120` (initial far-end delay compensation; tune per hardware)
- `GRUMPYREACHY_REALTIME_AEC_STRENGTH=0.75` and `GRUMPYREACHY_REALTIME_AEC_CORR_THRESHOLD=0.12` (AEC aggressiveness/tolerance)
- `GRUMPYADMIN_REALTIME_IMAGE_CACHE_DIR=data/realtime_image_cache` (temporary camera image cache path for realtime image context)
- `GRUMPYADMIN_REALTIME_IMAGE_CACHE_TTL_SECONDS=604800` (camera cache retention, default 7 days)
- `GRUMPYREACHY_PREFERRED_INPUT_DEVICE=macbook,built-in,default,reachy mini audio,reachy mini,pollen robotics,microphone,mic,respeaker,seeed-4mic,4mic,voicecard,ac108` (default mic preference; first substring match wins)
- `GRUMPYREACHY_PREFERRED_OUTPUT_DEVICE=macbook,built-in,default,reachy mini audio,reachy mini,pollen robotics,speakers,speaker,respeaker,seeed-4mic,4mic,voicecard,ac108` (default speaker preference; first substring match wins)
- `GRUMPYREACHY_*` robot/camera/profile settings

Compatibility fallback (deprecated):
- `LLM_MODEL` -> used if `OPENAI_TEXT_MODEL` is missing
- `MODEL_NAME` -> used if `OPENAI_REALTIME_MODEL` is missing

## 3. Run API (primary entrypoint)

- `uv run grumpyadmin-api`
- API base: `http://localhost:8001/api/v1`

Robot runtime is in-process and auto-starts by default (`GRUMPYADMIN_AUTOSTART_ROBOT=true`).

## 4. Run Web UI

1. `cd web`
2. `npm install`
3. `npm run dev`
4. Open `http://localhost:5173`

## 5. Main API surface

Assistant:
- `POST /api/v1/assistant/sessions`
- `GET /api/v1/assistant/sessions`
- `GET /api/v1/assistant/sessions/{session_id}/messages`
- `POST /api/v1/assistant/sessions/{session_id}/messages`
- `GET /api/v1/assistant/sessions/{session_id}/stream`
- `POST /api/v1/assistant/realtime/start`
- `POST /api/v1/assistant/realtime/stop`
- `GET /api/v1/assistant/realtime/status`
- `GET /api/v1/assistant/realtime/stream`

Runtime:
- `GET /api/v1/runtime/status`
- `POST /api/v1/runtime/heartbeat/start`
- `POST /api/v1/runtime/heartbeat/stop`
- `POST /api/v1/runtime/heartbeat/run-now`

## 6. Notes

- Auth is dev-only (disabled).
- First embedding call may download model files.
- Realtime runs server-side; browser conversation page shows transcript/history/status.
- Realtime tools now include `capture_camera_context`, `save_memory`, `search_memory`, and `robot_action` (with expressive actions).
- Camera image payloads are used for model context but raw `image_data_url` is stripped from persisted realtime events.
- Use systemd for boot startup via `uv run grumpyadmin-api`.
