#!/usr/bin/env python3
"""Find and dump headless sim stall states (parallel benchmark helper)."""

import io
import contextlib
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from concurrent.futures import ProcessPoolExecutor, as_completed

from engines.headless import (
    build_game,
    play_random_game,
    seed_everything,
    serialize_state,
    legal_moves,
    describe_stall,
    StalledGameError,
)


def _run(seed):
    seed_everything(seed)
    with contextlib.redirect_stdout(io.StringIO()):
        game = build_game(preset="base", num_players=2)
        try:
            play_random_game(game)
            return {"ok": True, "seed": seed}
        except StalledGameError as e:
            state = serialize_state(game)
            return {"ok": False, "seed": seed, "error": str(e), "detail": describe_stall(game, state)}


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--games", type=int, default=500)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args()

    tasks = [args.seed + i for i in range(args.games)]
    failures = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_run, s): s for s in tasks}
        for fut in as_completed(futs):
            r = fut.result()
            if not r.get("ok"):
                failures.append(r)

    print(f"failures: {len(failures)}/{len(tasks)}")
    for f in failures[:10]:
        print()
        print("seed", f["seed"])
        print("error", f["error"])
        for line in (f.get("detail") or "").splitlines():
            print(" ", line)


if __name__ == "__main__":
    main()
