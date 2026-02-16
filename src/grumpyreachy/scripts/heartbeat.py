"""Bridge command for robot-aware heartbeat."""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from grumpyreachy.heartbeat_bridge import HeartbeatBridge, heartbeat_result_to_json


def main() -> int:
    load_dotenv()
    bridge = HeartbeatBridge()
    result = bridge.evaluate()
    print(heartbeat_result_to_json(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
