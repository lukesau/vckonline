#!/usr/bin/env python3
"""Run ControlBot vs GameLogicBot on the hosted VCKO server."""

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from bots.runner import MatchRunner


def main():
    parser = argparse.ArgumentParser(description="Run a two-bot VCKO match on vcko.lukesau.com")
    parser.add_argument("--preset", default="base", help="Lobby preset (default: base)")
    parser.add_argument("--poll-interval", type=float, default=1.5, help="Seconds between state polls")
    parser.add_argument("--no-debug", action="store_true", help="Disable debug_mode on ready")
    args = parser.parse_args()

    runner = MatchRunner(
        preset=args.preset,
        poll_interval=args.poll_interval,
        debug_mode=not args.no_debug,
    )
    game_id, _ = runner.run()
    print(f"Match complete: {game_id}")


if __name__ == "__main__":
    main()
