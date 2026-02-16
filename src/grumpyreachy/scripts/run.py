"""Run grumpyreachy main app loop."""

from __future__ import annotations

import logging
import sys

from dotenv import load_dotenv

from grumpyreachy.app import GrumpyReachyApp


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = GrumpyReachyApp()
    return app.run_forever()


if __name__ == "__main__":
    sys.exit(main())
