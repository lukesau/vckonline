#!/usr/bin/env python3
"""Host ControlBot and play against it from the web browser."""

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from bots.host import ControlBotHost


def main():
    parser = argparse.ArgumentParser(
        description="Host ControlBot on vcko.lukesau.com; join the lobby from the web UI",
    )
    parser.add_argument("--preset", default="base", help="Lobby preset (default: base)")
    parser.add_argument("--poll-interval", type=float, default=1.5, help="Seconds between lobby polls")
    parser.add_argument("--debug", action="store_true", help="Enable debug_mode on ready (100/100/100 resources)")
    args = parser.parse_args()

    host = ControlBotHost(
        preset=args.preset,
        poll_interval=args.poll_interval,
        debug_mode=args.debug,
    )
    game_id, _ = host.run()
    print(f"Match complete: {game_id}")


if __name__ == "__main__":
    main()
