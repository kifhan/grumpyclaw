
## run reachy-mini-daemon for reachy-mini lite robot
cd ~/grumpyclaw
. .venv/bin/activate
reachy-mini-daemon

## run backend
cd ~/grumpyclaw
. .venv/bin/activate
uv run grumpyadmin-api

## run frontend
cd /home/darter/grumpyclaw/web
pnpm dev

## verify selected audio devices (API)
curl -s http://localhost:8001/api/v1/devices/audio/status | jq

## run mic/speaker smoke tests (API)
curl -s -X POST http://localhost:8001/api/v1/devices/audio/test-mic | jq
curl -s -X POST http://localhost:8001/api/v1/devices/audio/test-speaker | jq
