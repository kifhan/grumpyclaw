# grumpyClaw

Personal AI agent with:
- SQLite + FastEmbed memory
- Hybrid retrieval (vector + FTS5 BM25)
- Google Docs sync
- Heartbeat runner
- Slack (Socket Mode) and terminal chat

See [IMPLEMENT.md](IMPLEMENT.md) for architecture and Raspberry Pi notes.

## Setup

1. `uv sync`
2. Copy `.env.example` to `.env`
3. Set at least one LLM key:
   - `OPENCODE_API_KEY` (optional `LLM_BASE_URL`, `LLM_MODEL`)
   - or `OPENAI_API_KEY` (optional `LLM_BASE_URL`, `LLM_MODEL`)

For Slack, also set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`.

## Defaults

- SQLite DB path (if `GRUMPYCLAW_DB_PATH` is unset): `data/grumpyclaw.db`
- Skills directories (if `GRUMPYCLAW_SKILLS_DIR` is unset):
  - `skills/`
  - `.cursor/skills/`

## Google Docs Sync

1. Create OAuth credentials (Desktop app) in [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Enable **Google Docs API** and **Google Drive API**
3. Save credentials JSON (example: `config/google_credentials.json`)
4. Set `GOOGLE_CREDENTIALS_PATH`
5. Optional: set `GOOGLE_DOCS_FOLDER_ID` to restrict sync to one Drive folder
6. Run `uv run sync-google-docs`

On first run, complete browser OAuth; token is stored as `google_token.json` next to credentials.

## Heartbeat

Runs Google Docs sync (when configured) and asks the LLM to output either:
- `HEARTBEAT_OK`
- or one short proactive notification

Run once:
- `uv run heartbeat`

Cron every 30 minutes:
- `*/30 * * * * cd ~/grumpyClaw && uv run heartbeat`

Heartbeat context now reflects actual sync state:
- synced (with indexed chunk count)
- failed (with error)
- skipped (missing `GOOGLE_CREDENTIALS_PATH`)

## Terminal Chat

Start REPL:
- `uv run chat`

Commands:
- `/quit` (or `/exit`, `/q`) to exit
- `/clear` to reset conversation history

## Slack Bot (Socket Mode)

Uses the same LLM + memory/skills pipeline and runs until stopped.

1. Set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`
2. In Slack app config, enable Socket Mode and subscribe to needed events
3. Run `uv run slack-bot`

Stop with `Ctrl+C`.

## Skills

Add `SKILL.md` files under `skills/` or `.cursor/skills/` (or override with `GRUMPYCLAW_SKILLS_DIR`).
Skill content is appended to system prompts for terminal chat and Slack bot.
