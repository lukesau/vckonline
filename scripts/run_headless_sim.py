#!/usr/bin/env python3
"""Headless VCKO simulation harness.

Runs games fully in-process (no HTTP server, no polling) by driving the engine
directly through `engines.headless`. Two modes:

  # Play one random-vs-random game and print the result:
  python3 scripts/run_headless_sim.py --preset base --players 2 --seed 1

  # Benchmark throughput across CPU cores:
  python3 scripts/run_headless_sim.py --benchmark --games 500 --workers 18 \
      --preset base --players 2

Requires a one-time DB load per worker process (card tables via `card_pool`).
Activate the venv first: `source ./activate_with_env.sh`.
"""

import argparse
import contextlib
import io
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from engines.headless import build_game, play_random_game, seed_everything


def _run_one(seed, preset, num_players, debug_mode, duke_select_count, quiet=True):
    # The engine prints game-log lines to stdout; at scale that spam dominates
    # wall time and floods logs, so silence it during simulation.
    sink = io.StringIO() if quiet else sys.stdout
    seed_everything(seed)
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(sink):
        game = build_game(
            preset=preset,
            num_players=num_players,
            debug_mode=debug_mode,
            duke_select_count=duke_select_count,
        )
        t1 = time.perf_counter()
        result = play_random_game(game)
    t2 = time.perf_counter()
    result["build_seconds"] = t1 - t0
    result["play_seconds"] = t2 - t1
    result["seed"] = seed
    return result


def _stall_reason(msg):
    """Compact category for a stall/error message so failures can be tallied."""
    for tok in str(msg).split():
        if tok.startswith("action="):
            return tok
    return str(msg).split(":")[0][:60] or "unknown"


def _worker(args):
    (seed, preset, num_players, debug_mode, duke_select_count) = args
    try:
        from card_pool import ensure_loaded
        ensure_loaded()
        return {"ok": True, **_run_one(seed, preset, num_players, debug_mode, duke_select_count, quiet=True)}
    except Exception as e:
        import traceback
        return {
            "ok": False,
            "seed": seed,
            "error": f"{e}",
            "reason": f"{type(e).__name__}: {_stall_reason(e)}",
            "trace": traceback.format_exc(),
        }


def _single(args):
    result = _run_one(args.seed, args.preset, args.players, args.debug,
                      args.duke_select_count, quiet=not args.verbose)
    print(f"Game over in {result['turn_number']} turns / {result['steps']} engine steps")
    print(f"  build: {result['build_seconds'] * 1000:.0f} ms   play: {result['play_seconds'] * 1000:.0f} ms")
    print("  Final scores:")
    for r in result["scores"]:
        print(f"    {r['name']:>8}: {r['victory_score']:>3} VP "
              f"(G{r['gold']} S{r['strength']} M{r['magic']})")
    print(f"  Winner: {result['winner_name']} ({result['winning_score']} VP)")


def _benchmark(args):
    tasks = [
        (args.seed + i, args.preset, args.players, args.debug, args.duke_select_count)
        for i in range(args.games)
    ]
    workers = args.workers or (os.cpu_count() or 1)
    print(f"Running {args.games} games on {workers} workers "
          f"(preset={args.preset}, players={args.players})...")

    results = []
    failures = []
    wall0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_worker, t) for t in tasks]
        for done, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r.get("ok"):
                results.append(r)
            else:
                failures.append(r)
            if done % max(1, args.games // 20) == 0 or done == args.games:
                print(f"  {done}/{args.games} complete", flush=True)
    wall = time.perf_counter() - wall0

    print()
    print(f"Completed {len(results)} games ({len(failures)} failed) in {wall:.1f}s wall")
    if results:
        gps = len(results) / wall
        turns = [r["turn_number"] for r in results]
        play_s = [r["play_seconds"] for r in results]
        build_s = [r["build_seconds"] for r in results]
        win_scores = [r["winning_score"] for r in results if r["winning_score"] is not None]
        print(f"  Throughput: {gps:.1f} games/sec  (~{gps * 3600:,.0f} games/hour on {workers} workers)")
        print(f"  Turns/game:  mean {statistics.mean(turns):.1f}  "
              f"min {min(turns)}  max {max(turns)}")
        print(f"  Build time:  mean {statistics.mean(build_s) * 1000:.0f} ms  "
              f"(in-memory deal; dominates if games are short)")
        print(f"  Play time:   mean {statistics.mean(play_s) * 1000:.0f} ms")
        if win_scores:
            print(f"  Winning VP:  mean {statistics.mean(win_scores):.1f}  "
                  f"stdev {statistics.pstdev(win_scores):.1f}  "
                  f"min {min(win_scores)}  max {max(win_scores)}")
        names = {}
        for r in results:
            names[r["winner_name"]] = names.get(r["winner_name"], 0) + 1
        print("  Wins by bot name (sanity check for turn-order bias):")
        for name, cnt in sorted(names.items(), key=lambda kv: -kv[1]):
            print(f"    {name:>8}: {cnt} ({100 * cnt / len(results):.1f}%)")
    if failures:
        print()
        rate = 100 * len(failures) / (len(results) + len(failures))
        print(f"  Stall/error rate: {rate:.1f}%  ({len(failures)}/{len(results) + len(failures)})")
        reasons = {}
        for f in failures:
            reasons[f.get("reason", "?")] = reasons.get(f.get("reason", "?"), 0) + 1
        print("  Stalls by category (fix highest-frequency enumeration gaps first):")
        for reason, cnt in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"    {cnt:>4}  {reason}")
        print()
        print("Failed seeds:", ", ".join(str(f.get("seed")) for f in failures[:20]))
        print()
        print("Sample failure:")
        print(failures[0].get("error", failures[0].get("trace")))
        if failures[0].get("trace"):
            print(failures[0]["trace"])


def main():
    parser = argparse.ArgumentParser(description="Headless VCKO simulation harness")
    parser.add_argument("--preset", default="base")
    parser.add_argument("--players", type=int, default=2)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--debug", action="store_true", help="deal with debug_mode (rigged dice/resources)")
    parser.add_argument("--duke-select-count", type=int, default=2, dest="duke_select_count")
    parser.add_argument("--benchmark", action="store_true", help="run many games and report throughput")
    parser.add_argument("--games", type=int, default=100, help="benchmark game count")
    parser.add_argument("--workers", type=int, default=0, help="benchmark worker processes (0 = all cores)")
    parser.add_argument("--verbose", action="store_true", help="single mode: don't suppress engine game-log output")
    args = parser.parse_args()

    if args.benchmark:
        _benchmark(args)
    else:
        _single(args)


if __name__ == "__main__":
    main()
