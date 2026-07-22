#!/usr/bin/env python3
"""Print a dice RNG distribution report for manual audits.

Uses the same roll primitive as production ``roll_phase`` (two ``randint(1, 6)``
calls). Example:

    python3 scripts/analyze_dice_rng.py --rolls 500000 --seed 0
"""

import argparse
import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from dice_rng import format_distribution_report


def main():
    parser = argparse.ArgumentParser(description="Audit fair-d6 dice RNG distributions")
    parser.add_argument(
        "--rolls",
        type=int,
        default=120_000,
        help="Number of two-dice rolls to simulate (default: 120000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="RNG seed for reproducible reports (default: 0)",
    )
    args = parser.parse_args()
    print(format_distribution_report(n_rolls=args.rolls, seed=args.seed))


if __name__ == "__main__":
    main()
