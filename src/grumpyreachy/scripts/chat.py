"""Interactive shell for grumpyreachy: robot commands via API, grumpyclaw locally.

Requires grumpyadmin-api running (e.g. http://localhost:8001). Robot actions
are sent to the API; /gc-search, /gc-skill and plain text use grumpyclaw locally.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv

from grumpyreachy.feedback import FeedbackManager
from grumpyreachy.robot_controller import RobotController
from grumpyreachy.tool_adapter import GrumpyClawToolAdapter

DEFAULT_API_BASE = "http://localhost:8001"
ROBOT_ACTIONS_PATH = "/api/v1/robot/actions"


def _help_lines() -> list[str]:
    return [
        "Commands:",
        "  /help",
        "  /quit",
        "  /nod",
        "  /look <x> <y> <z> [duration]",
        "  /antenna <attention|success|error|neutral>",
        "  /say <text>",
        "  /gc-search <query>",
        "  /gc-skill <skill_id>",
        "Anything else is sent to grumpyclaw.ask.",
    ]


def _api_base() -> str:
    return os.environ.get("GRUMPYADMIN_API_URL", "").strip() or DEFAULT_API_BASE


def _robot_action(base_url: str, payload: dict) -> dict:
    url = f"{base_url.rstrip('/')}{ROBOT_ACTIONS_PATH}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"accepted": False, "reason": str(e)}
    except json.JSONDecodeError as e:
        return {"accepted": False, "reason": f"Invalid response: {e}"}


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    base = _api_base()

    # GrumpyClaw adapter (no robot): use dummy controller and disabled feedback
    no_robot = RobotController(mini=None)
    feedback = FeedbackManager(controller=no_robot, enabled=False)
    adapter = GrumpyClawToolAdapter(feedback=feedback)

    print("grumpyreachy chat (API mode). /help for commands.")
    for line in _help_lines():
        print(line)
    print(f"Robot actions → {base}")

    try:
        while True:
            try:
                raw = input("You: ").strip()
            except EOFError:
                break
            if not raw:
                continue
            if raw in {"/quit", "/exit", "/q"}:
                break
            if raw == "/help":
                for line in _help_lines():
                    print(line)
                continue
            if raw == "/nod":
                r = _robot_action(base, {"action": "nod"})
                if not r.get("accepted"):
                    print(f"Robot: {r.get('reason', 'failed')}")
                continue
            if raw.startswith("/look "):
                parts = shlex.split(raw)
                if len(parts) not in {4, 5}:
                    print("Usage: /look <x> <y> <z> [duration]")
                    continue
                payload = {
                    "action": "look_at",
                    "x": float(parts[1]),
                    "y": float(parts[2]),
                    "z": float(parts[3]),
                    "confirm": True,
                }
                if len(parts) == 5:
                    payload["duration"] = float(parts[4])
                r = _robot_action(base, payload)
                if not r.get("accepted"):
                    print(f"Robot: {r.get('reason', 'failed')}")
                continue
            if raw.startswith("/antenna "):
                parts = shlex.split(raw)
                state = parts[1] if len(parts) >= 2 else "attention"
                r = _robot_action(base, {"action": "antenna_feedback", "state": state})
                if not r.get("accepted"):
                    print(f"Robot: {r.get('reason', 'failed')}")
                continue
            if raw.startswith("/say "):
                text = raw[len("/say ") :].strip()
                if text:
                    payload = {"action": "speak", "text": text}
                    if len(text) >= 80:
                        payload["confirm"] = True
                    r = _robot_action(base, payload)
                    if not r.get("accepted"):
                        print(f"Robot: {r.get('reason', 'failed')}")
                continue
            if raw.startswith("/gc-search "):
                query = raw[len("/gc-search ") :].strip()
                if not query:
                    print("Usage: /gc-search <query>")
                    continue
                out = adapter.search_memory(query=query, top_k=5)
                if not out["ok"]:
                    print(f"Error: {out['error']}")
                    continue
                hits = out["result"]
                if not hits:
                    print("No memory hits.")
                    continue
                for i, hit in enumerate(hits, start=1):
                    print(f"{i}. [{hit['title']}] {hit['content'][:140]}")
                continue
            if raw.startswith("/gc-skill "):
                skill_id = raw[len("/gc-skill ") :].strip()
                if not skill_id:
                    print("Usage: /gc-skill <skill_id>")
                    continue
                out = adapter.run_skill(skill_id=skill_id)
                if not out["ok"]:
                    print(f"Error: {out['error']}")
                    continue
                result = out["result"]
                preview = result["content"][:220].replace("\n", " ")
                print(f"Skill loaded: {result['skill_id']} :: {preview}...")
                continue

            out = adapter.ask(prompt=raw)
            if not out["ok"]:
                print(f"LLM error: {out['error']}", file=sys.stderr)
                continue
            reply = str(out["result"])
            print(f"Assistant: {reply}")
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
