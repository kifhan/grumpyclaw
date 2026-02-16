# grumpyClaw + grumpyreachy

This repo contains two connected apps:
- `grumpyclaw`: personal AI agent (memory, retrieval, chat, Slack, heartbeat).
- `grumpyreachy`: Reachy Mini app runtime that observes environment, writes to memory, and bridges robot feedback + heartbeat context.

Implementation plans:
- `IMPLEMENT_GRUMPYCLAW.md`
- `IMPLEMENT_GRUMPREACHY.md`

## 1. Install

1. Install `uv` if not already installed.
2. From repo root, install dependencies:
   - `uv sync`
3. Create env file:
   - Copy `.env.example` to `.env`

## 2. Configure `.env`

At minimum, set one LLM provider:
- `OPENCODE_API_KEY=...`
- or `OPENAI_API_KEY=...`

Optional LLM overrides:
- `LLM_BASE_URL=...`
- `LLM_MODEL=...`

Core defaults:
- `GRUMPYCLAW_DB_PATH` default is `data/grumpyclaw.db`
- `GRUMPYCLAW_SKILLS_DIR` default scans `skills/` and `.cursor/skills/`

`grumpyreachy` settings:
- `GRUMPYREACHY_OBSERVE_INTERVAL=600`
- `GRUMPYREACHY_FEEDBACK_ENABLED=true`
- `GRUMPYREACHY_REACHY_MODE=lite`
- optional: `GRUMPYREACHY_CAMERA_ANALYZER_ENABLED=true|false`
- optional: `GRUMPYREACHY_AUDIO_ANALYZER_ENABLED=true|false`

## 3. Setup grumpyclaw

### Google Docs sync (optional)

1. Create OAuth credentials in Google Cloud Console (Desktop app).
2. Enable Google Docs API + Google Drive API.
3. Save credentials JSON (example: `config/google_credentials.json`).
4. Set `GOOGLE_CREDENTIALS_PATH` in `.env`.
5. Optional: set `GOOGLE_DOCS_FOLDER_ID`.
6. Run:
   - `uv run sync-google-docs`

### Run grumpyclaw

- Heartbeat:
  - `uv run heartbeat`
- Terminal chat:
  - `uv run chat`
- Slack bot (Socket Mode):
  - set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`
  - run `uv run slack-bot`

## 4. Setup grumpyreachy

### Reachy Mini dependency

`grumpyreachy` will try to use Reachy Mini in this order:
1. Installed Python package `reachy_mini`
2. Local source fallback at `reachy_mini/src` (already present in this repo)
3. No-robot mode (app still runs, motion calls are safely skipped)

### Run grumpyreachy

- Main app loop:
  - `uv run grumpyreachy-run`
- Robot heartbeat bridge (deterministic JSON output):
  - `uv run grumpyreachy-heartbeat`
- Interactive chat/commands:
  - `uv run grumpyreachy-chat`

`grumpyreachy-chat` commands:
- `/nod`
- `/look <x> <y> <z> [duration]`
- `/antenna <attention|success|error|neutral>`
- `/say <text>`
- `/gc-search <query>`
- `/gc-skill <skill_id>`

Plain text input runs `grumpyclaw.ask`.

## 5. grumpyadmin (FastAPI + React)

`grumpyadmin` is a dev-mode web admin app for chat + management.

Warning:
- Auth is disabled in v1 (dev-only). Do not expose to public networks.

Backend API:
- Install/refresh deps:
  - `uv sync`
- Run API server:
  - `uv run grumpyadmin-api`
- API base:
  - `http://localhost:8000/api/v1`

Frontend web app:
- `cd web`
- `npm install`
- `npm run dev`
- Open:
  - `http://localhost:5173`

Main pages:
- `/chat` unified `grumpyclaw` and `grumpyreachy` chat (SSE streaming)
- `/runtime` start/stop/restart runtime scripts
- `/robot` robot action controls (rate-limited with confirm checks)
- `/memory`, `/skills`, `/heartbeat`, `/logs`

`/api/v1/logs` supports structured filters:
- `source=runtime|robot`
- `level=DEBUG|INFO|WARNING|ERROR`
- `process_name=...`
- `event_type=...`
- `q=...` (substring search in payload/reason)

## 6. End-to-end quick check

1. Start app:
   - `uv run grumpyreachy-run`
2. In another terminal, run:
   - `uv run grumpyreachy-heartbeat`
3. Confirm returned JSON includes:
   - `status`
   - `message`
   - `context.latest_observations`

## 7. Notes

- First embedding call may download model files for FastEmbed.
- If embedding init logs ONNX GPU discovery warnings on Linux headless devices, set `GRUMPYCLAW_EMBEDDING_PROVIDERS=CPUExecutionProvider`.
- If first embedding call fails with `Connection error`, ensure outbound network access to Hugging Face model download endpoints (or pre-warm the model cache).
- On Windows, Hugging Face cache may warn about symlink support; this is non-fatal.
- Stop long-running processes with `Ctrl+C`.

## 8. Run on boot (systemd)

Assumes project at `/home/darter/grumpyclaw` and user `darter`. Install unit files into `/etc/systemd/system/`, then enable and start.

### grumpyreachy-run.service

```ini
[Unit]
Description=grumpyreachy main app (observe + memory)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/darter/grumpyclaw
EnvironmentFile=/home/darter/grumpyclaw/.env
ExecStart=/home/darter/.local/bin/uv run grumpyreachy-run
Restart=on-failure
RestartSec=10
User=darter

[Install]
WantedBy=multi-user.target
```

### grumpyclaw-slack-bot.service (optional)

```ini
[Unit]
Description=grumpyclaw Slack bot (Socket Mode)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/darter/grumpyclaw
EnvironmentFile=/home/darter/grumpyclaw/.env
ExecStart=/home/darter/.local/bin/uv run slack-bot
Restart=on-failure
RestartSec=10
User=darter

[Install]
WantedBy=multi-user.target
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable grumpyreachy-run.service grumpyclaw-slack-bot.service
sudo systemctl start grumpyreachy-run grumpyclaw-slack-bot
```

Status and logs:

```bash
sudo systemctl status grumpyreachy-run
sudo journalctl -u grumpyreachy-run.service -f
```

`uv` is assumed at `/home/darter/.local/bin/uv`; adjust `ExecStart` if your path differs.

## 9. Cron (periodic heartbeat)

Heartbeat commands are one-shot; use cron (or a systemd timer) to run them on a schedule, e.g. every 15 minutes:

```cron
*/15 * * * * cd /home/darter/grumpyclaw && /home/darter/.local/bin/uv run heartbeat
*/15 * * * * cd /home/darter/grumpyclaw && /home/darter/.local/bin/uv run grumpyreachy-heartbeat
```
