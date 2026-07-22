"""Generate self-play training data.

v2: games can be played by the search agent itself (--policy mcts-nn) and the
raw sampled STATES are stored (gzip jsonl of engine save-dicts + outcomes), so
feature engineering iterates by re-extraction (agent/extract_features.py)
without replaying games. Early-game moves are sampled proportional to MCTS
visit counts (AlphaZero-style temperature) for position diversity; later moves
are argmax.

Usage:
  python -m agent.selfplay --games 250 --seed 10000 --policy mcts-nn \
      --iterations 50 --store-states agent/data/sp2_chunk0.jsonl.gz

Legacy fast mode (feature vectors straight to npz, epsilon-greedy):
  python -m agent.selfplay --games 3000 --seed 1 --policy greedy \
      --out agent/data/selfplay_v1.npz
"""

import argparse
import contextlib
import gzip
import io
import json
import random
import time
from pathlib import Path

from agent.headless import acting_player_ids, advance, apply_move, legal_moves, new_game
from agent.play_random import _fingerprint
from agent.policies import GreedyPolicy, RandomPolicy

_SINK = io.StringIO()


def _make_policy(name, iterations):
    if name == "greedy":
        return GreedyPolicy()
    if name == "mcts-nn":
        from agent.mcts import MCTSPolicy
        from agent.value_net import DEFAULT_MODEL_PATH

        policy = MCTSPolicy(iterations=iterations, value_path=DEFAULT_MODEL_PATH)
        policy.name = "mcts-nn"
        return policy
    if name == "mcts":
        from agent.mcts import MCTSPolicy

        return MCTSPolicy(iterations=iterations)
    raise ValueError(f"unknown policy {name!r}")


def _pick(policy, game, pid, moves, temperature_turns):
    """Policy move choice; MCTS samples proportional to root visits early on."""
    analyze = getattr(policy, "analyze", None)
    if callable(analyze) and int(game.turn_number or 0) <= temperature_turns:
        decision = analyze(game, pid, moves)
        candidates = decision.get("candidates") or []
        total = sum(c["visits"] for c in candidates)
        if total > 0:
            pick = random.uniform(0, total)
            acc = 0.0
            for c in candidates:
                acc += c["visits"]
                if pick <= acc:
                    return c["move"]
        return decision.get("chosen") or (moves[0] if moves else None)
    return policy.choose(game, None, pid, moves)


def play_selfplay_game(seed, policy_name="greedy", iterations=50, epsilon=0.15,
                       sample_every=2, temperature_turns=10, max_steps=20000,
                       collect_states=False):
    """Play one self-play game. Returns (samples, game) or None on failure.

    samples: list of (payload, viewer_pid) where payload is a feature vector
    (collect_states=False) or a serialized save-dict (collect_states=True).
    """
    from agent.features import extract

    policy = _make_policy(policy_name, iterations)
    rando = RandomPolicy()
    use_epsilon = epsilon if policy_name == "greedy" else 0.0
    game = new_game(seed=seed)
    with contextlib.redirect_stdout(_SINK):
        advance(game)
    samples = []
    steps = 0
    stuck_streak = 0
    while game.phase != "game_over":
        steps += 1
        if steps > max_steps:
            return None
        if steps % sample_every == 0 and game.phase == "action":
            if collect_states:
                from game_serialization import serialize_game_to_save_dict

                with contextlib.redirect_stdout(_SINK):
                    samples.append((serialize_game_to_save_dict(game), None))
            else:
                for p in game.player_list:
                    samples.append((extract(game, p.player_id), p.player_id))
        before = _fingerprint(game)
        moved = False
        noops = []
        for pid in acting_player_ids(game):
            moves = legal_moves(game, pid)
            while moves:
                if use_epsilon and random.random() < use_epsilon:
                    move = rando.choose(game, None, pid, moves)
                else:
                    with contextlib.redirect_stdout(_SINK):
                        move = _pick(policy, game, pid, moves, temperature_turns)
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
    close = getattr(policy, "close", None)
    if callable(close):
        close()
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
    parser.add_argument("--games", type=int, default=250)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--policy", default="greedy", choices=("greedy", "mcts", "mcts-nn"))
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--epsilon", type=float, default=0.15)
    parser.add_argument("--sample-every", type=int, default=2)
    parser.add_argument("--temperature-turns", type=int, default=10)
    parser.add_argument("--out", default=None, help="npz of extracted features (legacy fast mode)")
    parser.add_argument("--store-states", default=None,
                        help="gzip jsonl of raw save-dict states + outcomes (re-extractable)")
    args = parser.parse_args()
    if not args.out and not args.store_states:
        parser.error("need --out and/or --store-states")

    collect_states = bool(args.store_states)
    writer = None
    if collect_states:
        Path(args.store_states).parent.mkdir(parents=True, exist_ok=True)
        writer = gzip.open(args.store_states, "wt", encoding="utf-8")

    xs, ys = [], []
    n_states = 0
    skipped = 0
    start = time.perf_counter()
    for i in range(args.games):
        result = play_selfplay_game(
            args.seed + i, policy_name=args.policy, iterations=args.iterations,
            epsilon=args.epsilon, sample_every=args.sample_every,
            temperature_turns=args.temperature_turns, collect_states=collect_states,
        )
        if result is None:
            skipped += 1
            continue
        samples, game = result
        outcomes = {p.player_id: outcome_for(game, p.player_id) for p in game.player_list}
        if collect_states:
            for save_dict, _ in samples:
                writer.write(json.dumps({"state": save_dict, "outcomes": outcomes}) + "\n")
                n_states += 1
        else:
            for features, viewer in samples:
                xs.append(features)
                ys.append(outcomes[viewer])
        if (i + 1) % 25 == 0:
            elapsed = time.perf_counter() - start
            count = n_states if collect_states else len(xs)
            print(f"  {i + 1}/{args.games} games, {count} samples, {elapsed:.0f}s", flush=True)
    if writer is not None:
        writer.close()
        print(f"wrote {args.store_states}: {n_states} states from "
              f"{args.games - skipped} games ({skipped} skipped)")
    if args.out:
        import numpy as np

        from agent.features import FEATURE_VERSION

        x = np.stack(xs)
        y = np.asarray(ys, dtype=np.float32)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out, x=x, y=y, feature_version=FEATURE_VERSION)
        print(f"wrote {out}: {len(x)} positions")


if __name__ == "__main__":
    main()
