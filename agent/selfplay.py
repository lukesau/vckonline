"""Generate self-play training data: (state features, final outcome) pairs.

Usage:
  python -m agent.selfplay --games 3000 --seed 1 --out agent/data/selfplay_v1.npz

Games are played by ε-greedy self-play (fast: ~20-50ms per game), which is the
standard bootstrap: the first value net learns "who wins from here under
competent fast play", and later pipeline iterations can regenerate data with
the search agent for sharper targets. Positions are sampled at decision points
from BOTH players' perspectives; labels are the final result for that viewer
(1 win / 0.5 tie / 0 loss).
"""

import argparse
import contextlib
import io
import random
import time
from pathlib import Path

import numpy as np

from agent.fast_state import fast_state
from agent.features import FEATURE_VERSION, N_FEATURES, extract
from agent.headless import acting_player_ids, advance, apply_move, new_game
from agent.moves import enumerate_moves
from agent.play_random import _fingerprint
from agent.policies import GreedyPolicy, RandomPolicy

_SINK = io.StringIO()


def play_selfplay_game(seed, epsilon=0.15, sample_every=2, max_steps=20000):
    """Play one ε-greedy self-play game; return (features_list, viewers, game)."""
    greedy = GreedyPolicy()
    rando = RandomPolicy()
    game = new_game(seed=seed)
    with contextlib.redirect_stdout(_SINK):
        advance(game)
    samples = []   # (feature_vector, viewer_pid)
    steps = 0
    stuck_streak = 0
    while game.phase != "game_over":
        steps += 1
        if steps > max_steps:
            return None
        if steps % sample_every == 0 and game.phase == "action":
            for p in game.player_list:
                samples.append((extract(game, p.player_id), p.player_id))
        view = fast_state(game)
        before = _fingerprint(game)
        moved = False
        noops = []
        for pid in acting_player_ids(game):
            moves = enumerate_moves(view, pid)
            while moves:
                policy = rando if random.random() < epsilon else greedy
                move = policy.choose(game, view, pid, moves)
                if move is None:
                    break
                moves.remove(move)
                try:
                    with contextlib.redirect_stdout(_SINK):
                        apply_move(game, move)
                except (ValueError, KeyError, IndexError):
                    continue
                if _fingerprint(game) == before:
                    noops.append(move)
                    continue
                moved = True
                break
            if moved:
                break
        if moved:
            stuck_streak = 0
            continue
        if noops:
            stuck_streak += 1
            if stuck_streak >= 5:
                return None
            continue
        with contextlib.redirect_stdout(_SINK):
            if not game.advance_tick():
                return None
            advance(game)
        stuck_streak = 0
    _SINK.seek(0)
    _SINK.truncate(0)
    return samples, game


def outcome_for(game, viewer_pid):
    winners = set((game.final_result or {}).get("winner_player_ids") or [])
    if not winners:
        return 0.5
    if viewer_pid in winners:
        return 1.0 if len(winners) == 1 else 0.5
    return 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--epsilon", type=float, default=0.15)
    parser.add_argument("--sample-every", type=int, default=2)
    parser.add_argument("--out", default="agent/data/selfplay_v1.npz")
    args = parser.parse_args()

    xs, ys = [], []
    skipped = 0
    start = time.perf_counter()
    for i in range(args.games):
        result = play_selfplay_game(args.seed + i, epsilon=args.epsilon,
                                    sample_every=args.sample_every)
        if result is None:
            skipped += 1
            continue
        samples, game = result
        for features, viewer in samples:
            xs.append(features)
            ys.append(outcome_for(game, viewer))
        if (i + 1) % 500 == 0:
            elapsed = time.perf_counter() - start
            print(f"  {i + 1}/{args.games} games, {len(xs)} positions, {elapsed:.0f}s")
    x = np.stack(xs)
    y = np.asarray(ys, dtype=np.float32)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, x=x, y=y, feature_version=FEATURE_VERSION)
    elapsed = time.perf_counter() - start
    print(
        f"\nwrote {out}: {len(x)} positions x {x.shape[1]} features "
        f"(expected {N_FEATURES}) from {args.games - skipped} games "
        f"({skipped} skipped) in {elapsed:.0f}s; mean outcome {y.mean():.3f}"
    )


if __name__ == "__main__":
    main()
