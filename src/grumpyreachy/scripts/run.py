"""Run grumpyreachy main app loop.

Standalone entry point. Cannot run alongside grumpyadmin-api: the API owns the
robot connection. If the API is running on port 8001, this script will exit.
"""

from __future__ import annotations

import logging
import socket
import sys

from dotenv import load_dotenv

from grumpyreachy.app import GrumpyReachyApp

GRUMPYADMIN_PORT = 8001


def _api_port_in_use() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(("127.0.0.1", GRUMPYADMIN_PORT))
            return True
    except (OSError, socket.error):
        return False


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if _api_port_in_use():
        logging.getLogger("grumpyreachy.run").error(
            "grumpyadmin-api appears to be running on port %s. "
            "Only one process can own the robot; run the API alone or stop it first.",
            GRUMPYADMIN_PORT,
        )
        return 1
    app = GrumpyReachyApp()
    return app.run_forever()


if __name__ == "__main__":
    sys.exit(main())
