"""Interactive shell for Phase-1 grumpyreachy runtime checks."""

from __future__ import annotations

import logging
import shlex
import sys
import threading
from typing import Iterable

from dotenv import load_dotenv

from grumpyreachy.actions import ControlAction
from grumpyreachy.app import GrumpyReachyApp
from grumpyreachy.tool_adapter import GrumpyClawToolAdapter


def _help_lines() -> Iterable[str]:
    return (
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
    )


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = GrumpyReachyApp()
    t = threading.Thread(target=app.run_forever, name="grumpyreachy-app", daemon=True)
    t.start()
    adapter = GrumpyClawToolAdapter(feedback=app.feedback_manager)

    print("grumpyreachy chat. /help for commands.")
    for line in _help_lines():
        print(line)

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
                app.enqueue(ControlAction(name="nod"))
                continue
            if raw.startswith("/look "):
                parts = shlex.split(raw)
                if len(parts) not in {4, 5}:
                    print("Usage: /look <x> <y> <z> [duration]")
                    continue
                payload = {
                    "x": float(parts[1]),
                    "y": float(parts[2]),
                    "z": float(parts[3]),
                }
                if len(parts) == 5:
                    payload["duration"] = float(parts[4])
                app.enqueue(ControlAction(name="look_at", payload=payload))
                continue
            if raw.startswith("/antenna "):
                parts = shlex.split(raw)
                state = parts[1] if len(parts) >= 2 else "attention"
                app.enqueue(ControlAction(name="antenna_feedback", payload={"state": state}))
                continue
            if raw.startswith("/say "):
                text = raw[len("/say ") :].strip()
                if text:
                    app.enqueue(ControlAction(name="speak", payload={"text": text}))
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
    finally:
        app.stop()
        t.join(timeout=3.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
