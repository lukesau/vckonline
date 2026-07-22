#!/usr/bin/env python3
"""Find and dump headless sim stall states (parallel benchmark helper)."""

import contextlib
import io
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from concurrent.futures import ProcessPoolExecutor, as_completed

from agent.headless import (
    StalledGameError,
    build_game,
    describe_stall,
    legal_moves,
    play_random_game,
    seed_everything,
    serialize_state,
)


def _run(seed):
    seed_everything(seed)
    with contextlib.redirect_stdout(io.StringIO()):
        game = build_game(preset="base", num_players=2, seed=seed)
        try:
            play_random_game(game)
            return {"seed": seed, "ok": True}
        except StalledGameError as e:
            state = serialize_state(game)
            return {
                "seed": seed,
                "ok": False,
                "error": str(e),
                "stall": describe_stall(game, state=state),
                "n_moves": {
                    p.get("player_id"): len(legal_moves(game, p.get("player_id"), state=state))
                    for p in (state.get("player_list") or [])
                },
            }
        except Exception as e:
            import traceback
            return {"seed": seed, "ok": False, "error": f"{e}", "trace": traceback.format_exc()}


def main():
    seeds = list(range(1, int(sys.argv[1]) + 1)) if len(sys.argv) > 1 else list(range(1, 51))
    workers = min(os.cpu_count() or 1, len(seeds))
    print(f"Probing {len(seeds)} seeds on {workers} workers...")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run, s) for s in seeds]
        for fut in as_completed(futures):
            r = fut.result()
            if r.get("ok"):
                continue
            print(f"\n=== stall seed={r['seed']} ===")
            print(r.get("error"))
            if r.get("stall"):
                print(r["stall"])
            if r.get("trace"):
                print(r["trace"])


if __name__ == "__main__":
    main()
