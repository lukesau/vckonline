"""Prove an engine optimization did not change selfplay output.

The optimizations being pursued (dropping redundant JSON round trips in
clone_game / serialize_game_to_save_dict) are meant to be pure speedups. This
harness is what makes that claim checkable rather than hopeful.

It works because games are deterministic: vcko_ray.task seeds the global RNG
per game, so a given seed produces a bit-identical game. Run `capture` before
the change and `compare` after; any difference in any record is a regression.

    # BEFORE touching the engine
    python -m tools.equivalence capture --out baseline.jsonl.gz --games 6

    # AFTER the change, same seeds
    python -m tools.equivalence compare --baseline baseline.jsonl.gz

Deliberately runs in-process and single-threaded rather than through Ray:
this is about output equivalence, not throughput, and removing the scheduler
removes a source of nondeterminism.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import random
import sys
import time
import pathlib
from pathlib import Path

# Seeds live in their own range so nothing here can collide with a real
# cohort (see campaigns.toml) or land in a production shard.
BASE_SEED = 950000

# Deliberately low. The point is to exercise every serialization path, not to
# measure search quality - and 2000-iteration games take ~50min each, which
# makes a before/after loop useless. Raise only if a regression is suspected
# in code that is depth-dependent.
DEFAULT_ITERATIONS = 60


def run_games(vcko_root: Path, games: int, iterations: int,
              players: int, policy: str) -> list[dict]:
    # cwd must be the checkout: the value/policy nets load from relative paths
    # (agent/models/value_v5.npz). Ray gets this via runtime_env working_dir;
    # here we do it explicitly so the harness runs under the same contract as
    # production rather than a subtly different one.
    sys.path.insert(0, str(vcko_root))
    os.chdir(vcko_root)
    from agent.selfplay import build_records, play_selfplay_game

    out = []
    for i in range(games):
        seed = BASE_SEED + i
        random.seed(seed)          # matches vcko_ray.task._play
        t0 = time.perf_counter()
        result = play_selfplay_game(
            seed, policy_name=policy, iterations=iterations,
            collect_states=True, record_visits=True,
            preset="base", num_players=players, turn_priors=True,
        )
        dt = time.perf_counter() - t0
        if result is None:
            out.append({"seed": seed, "skipped": True, "secs": dt})
            print(f"  seed {seed}: skipped ({dt:.1f}s)", flush=True)
            continue
        samples, game = result
        # Uses the same build_records() as production rather than an
        # independent copy. That is safe because the oracle here is the
        # captured baseline FILE, not this code: if build_records changes
        # shape, the new output stops matching the frozen baseline and the
        # comparison fails. A private copy would only add a fourth thing to
        # drift.
        records = build_records(samples, game)
        out.append({"seed": seed, "skipped": False, "secs": dt,
                    "n": len(records), "records": records})
        print(f"  seed {seed}: {len(records)} records ({dt:.1f}s)", flush=True)
    return out


def digest(records: list[dict]) -> str:
    """Stable hash of a game's records.

    sort_keys because dict ordering is not part of the output contract - two
    engines that emit the same data in a different key order are equivalent,
    and flagging that would be noise.
    """
    h = hashlib.sha256()
    for r in records:
        h.update(json.dumps(r, sort_keys=True, separators=(",", ":")).encode())
    return h.hexdigest()


def cmd_capture(a) -> int:
    res = run_games(Path(a.vcko_root).expanduser(), a.games, a.iterations,
                    a.players, a.policy)
    total = sum(r["secs"] for r in res)
    with gzip.open(a.out, "wt") as f:
        for r in res:
            f.write(json.dumps({
                "seed": r["seed"], "skipped": r["skipped"], "secs": r["secs"],
                "n": r.get("n", 0),
                "digest": digest(r["records"]) if not r["skipped"] else None,
                "records": r.get("records", []),
            }) + "\n")
    print(f"\nwrote {a.out}: {len(res)} games, {total:.1f}s total")
    return 0


def cmd_compare(a) -> int:
    base = {}
    with gzip.open(a.baseline, "rt") as f:
        for line in f:
            e = json.loads(line)
            base[e["seed"]] = e
    if not base:
        print("ERROR: empty baseline", file=sys.stderr)
        return 1

    res = run_games(Path(a.vcko_root).expanduser(), len(base), a.iterations,
                    a.players, a.policy)
    base_secs = sum(e["secs"] for e in base.values())
    new_secs = sum(r["secs"] for r in res)

    bad = 0
    for r in res:
        b = base.get(r["seed"])
        if b is None:
            print(f"  seed {r['seed']}: NOT IN BASELINE"); bad += 1; continue
        if r["skipped"] != b["skipped"]:
            print(f"  seed {r['seed']}: skipped {b['skipped']} -> {r['skipped']}")
            bad += 1; continue
        if r["skipped"]:
            continue
        if r["n"] != b["n"]:
            print(f"  seed {r['seed']}: RECORD COUNT {b['n']} -> {r['n']}")
            bad += 1; continue
        d = digest(r["records"])
        if d != b["digest"]:
            bad += 1
            print(f"  seed {r['seed']}: DIGEST MISMATCH")
            for i, (x, y) in enumerate(zip(b["records"], r["records"])):
                if json.dumps(x, sort_keys=True) != json.dumps(y, sort_keys=True):
                    print(f"     first differing record: index {i}")
                    bx, by = set(x), set(y)
                    if bx - by: print(f"     keys lost:  {sorted(bx - by)[:8]}")
                    if by - bx: print(f"     keys added: {sorted(by - bx)[:8]}")
                    for k in sorted(bx & by):
                        if x[k] != y[k]:
                            print(f"     field {k!r} differs")
                            print(f"        was: {str(x[k])[:160]}")
                            print(f"        now: {str(y[k])[:160]}")
                            break
                    break
        else:
            print(f"  seed {r['seed']}: identical ({r['n']} records)")

    print(f"\nspeed: {base_secs:.1f}s -> {new_secs:.1f}s "
          f"({base_secs / new_secs:.2f}x)" if new_secs else "")
    if bad:
        print(f"FAIL: {bad}/{len(res)} games differ - output is NOT compatible")
        return 1
    print(f"PASS: {len(res)}/{len(res)} games bit-identical")
    return 0


def main() -> int:
    # Shared options go on a parent parser so they are accepted AFTER the
    # subcommand, which is the order everyone types.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--vcko-root", default=str(pathlib.Path(__file__).resolve().parent.parent),
                        help="engine checkout to test (default: this repo)")
    common.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    common.add_argument("--players", type=int, default=2)
    common.add_argument("--policy", default="mcts-nn")

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", parents=[common])
    c.add_argument("--out", default="baseline.jsonl.gz")
    c.add_argument("--games", type=int, default=6); c.set_defaults(fn=cmd_capture)
    k = sub.add_parser("compare", parents=[common])
    k.add_argument("--baseline", default="baseline.jsonl.gz")
    k.set_defaults(fn=cmd_compare)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
