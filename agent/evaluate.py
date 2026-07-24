"""Head-to-head policy evaluation harness.

Usage:
  python -m agent.evaluate --p1 greedy --p2 random --games 50 --seed 1
  python -m agent.evaluate --p1 mcts --p2 greedy --games 10 --seed 1 --iterations 60

Seat assignment: policy "--p1" plays pid p1, "--p2" plays pid p2. The engine
shuffles turn order per seed, and --swap-seats alternates assignments per game,
so first-player advantage washes out across an even number of games.
"""

import argparse
import contextlib
import io
import random
import time

from agent.headless import acting_player_ids, advance, apply_move, legal_moves, new_game
from agent.play_random import _fingerprint, _prompt_debug

_SINK = io.StringIO()


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(_SINK):
        result = fn(*args, **kwargs)
    _SINK.seek(0)
    _SINK.truncate(0)
    return result


def play_policy_game(policies, seed=None, max_steps=20000):
    """policies: {player_id: policy}. Returns (game, steps)."""
    game = new_game(seed=seed)
    _quiet(advance, game)
    steps = 0
    stuck_streak = 0
    while game.phase != "game_over":
        steps += 1
        if steps > max_steps:
            return game, steps
        before = _fingerprint(game)
        moved = False
        noops = []
        for pid in acting_player_ids(game):
            moves = legal_moves(game, pid)
            policy = policies[pid]
            while moves:
                move = policy.choose(game, None, pid, moves)
                if move is None:
                    break
                moves.remove(move)
                try:
                    _quiet(apply_move, game, move)
                except (ValueError, KeyError, IndexError):
                    # IndexError: known engine crash (Undead Samurai 6th area,
                    # raised pre-mutation) — safe to treat as a rejected move.
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
                raise RuntimeError(f"all moves no-ops ({noops!r}) at {_prompt_debug(game)}")
            continue
        if not _quiet(game.advance_tick):
            raise RuntimeError(f"stalled: {_prompt_debug(game)}")
        _quiet(advance, game)
        stuck_streak = 0
    return game, steps


def make_policy(name, args, role="p1"):
    """Build the policy for a side. `role` is "p1"/"p2" per the CLI arguments
    (NOT the seat — seats swap per game); the --iterations2/--workers2
    overrides follow the p2 role so same-name matchups (self-play A/B) work."""
    from agent.policies import GreedyPolicy, RandomPolicy

    iterations = args.iterations
    workers = args.workers
    parallel_mode = getattr(args, "parallel_mode", "root") or "root"
    value_path = getattr(args, "value_path", None)
    turn_priors = (getattr(args, "turn_priors", "off") or "off") == "on"
    if role == "p2":
        if getattr(args, "iterations2", None) is not None:
            iterations = args.iterations2
        if getattr(args, "workers2", None) is not None:
            workers = args.workers2
        if getattr(args, "parallel_mode2", None) is not None:
            parallel_mode = args.parallel_mode2
        if getattr(args, "value_path2", None) is not None:
            value_path = args.value_path2
        if getattr(args, "turn_priors2", None) is not None:
            turn_priors = args.turn_priors2 == "on"

    if name == "random":
        return RandomPolicy()
    if name == "greedy":
        return GreedyPolicy()
    if name == "mcts":
        from agent.mcts import MCTSPolicy

        return MCTSPolicy(iterations=iterations, workers=workers,
                          parallel_mode=parallel_mode, turn_priors=turn_priors)
    if name == "mcts-nn":
        from agent.mcts import MCTSPolicy
        from agent.value_net import DEFAULT_MODEL_PATH

        policy = MCTSPolicy(iterations=iterations, workers=workers,
                            parallel_mode=parallel_mode, turn_priors=turn_priors,
                            value_path=value_path or DEFAULT_MODEL_PATH)
        policy.name = "mcts-nn"
        return policy
    raise ValueError(f"unknown policy {name!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--p1", default="greedy")
    parser.add_argument("--p2", default="random")
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=60, help="MCTS iterations per decision")
    parser.add_argument("--iterations2", type=int, default=None,
                        help="override iterations for --p2 (equal-time comparisons)")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="MCTS root-parallel worker processes (1 = single-process)",
    )
    parser.add_argument("--workers2", type=int, default=None,
                        help="override workers for --p2 (config A/B comparisons)")
    parser.add_argument("--parallel-mode", default="root", choices=("root", "halving"),
                        help="how workers spend the budget (see MCTSPolicy)")
    parser.add_argument("--parallel-mode2", default=None, choices=("root", "halving"),
                        help="override parallel mode for --p2")
    parser.add_argument("--value-path", default=None,
                        help="value-net .npz for mcts-nn (default: DEFAULT_MODEL_PATH)")
    parser.add_argument("--value-path2", default=None,
                        help="override value net for --p2 (model A/B comparisons)")
    parser.add_argument("--turn-priors", default="off", choices=("on", "off"),
                        help="root priors from best same-turn action PAIRS (see MCTSPolicy)")
    parser.add_argument("--turn-priors2", default=None, choices=("on", "off"),
                        help="override turn-priors for --p2")
    parser.add_argument("--swap-seats", action="store_true", default=True)
    args = parser.parse_args()

    label1 = args.p1
    label2 = args.p2 if args.p2 != args.p1 else f"{args.p2}#2"
    sides = ((args.p1, "p1", label1), (args.p2, "p2", label2))

    wins = {label1: 0, label2: 0}
    ties = 0
    vp_sum = {label1: 0, label2: 0}
    unfinished = 0
    start = time.perf_counter()
    for i in range(args.games):
        seed = args.seed + i
        order = sides if (not args.swap_seats or i % 2 == 0) else sides[::-1]
        policies = {
            "p1": make_policy(order[0][0], args, role=order[0][1]),
            "p2": make_policy(order[1][0], args, role=order[1][1]),
        }
        name_by_pid = {"p1": order[0][2], "p2": order[1][2]}
        try:
            game, steps = play_policy_game(policies, seed=seed)
        finally:
            for pol in policies.values():
                close = getattr(pol, "close", None)
                if callable(close):
                    close()
        if game.phase != "game_over":
            unfinished += 1
            print(f"game {i + 1}: seed={seed} UNFINISHED ({steps} steps)")
            continue
        result = game.final_result or {}
        winners = set(result.get("winner_player_ids") or [])
        for row in game.final_scores or []:
            vp_sum[name_by_pid[row["player_id"]]] += int(row["total_vp"])
        if len(winners) == 1:
            winner_name = name_by_pid[next(iter(winners))]
            wins[winner_name] += 1
        else:
            ties += 1
        by_name = {
            name_by_pid[r["player_id"]]: r["total_vp"] for r in game.final_scores or []
        }
        print(
            f"game {i + 1}: seed={seed} turns={game.turn_number} "
            + " vs ".join(f"{n}={v}" for n, v in by_name.items())
            + f" -> {result.get('headline', '?')} [{name_by_pid[next(iter(winners))] if len(winners) == 1 else 'tie'}]"
        )
    elapsed = time.perf_counter() - start
    finished = args.games - unfinished
    print(f"\n=== {label1} vs {label2}: {args.games} games in {elapsed:.0f}s ===")
    for name in (label1, label2):
        if finished:
            print(
                f"  {name:8} wins={wins[name]:3} ({100 * wins[name] / finished:.0f}%) "
                f"avg VP={vp_sum[name] / finished:.1f}"
            )
    if ties:
        print(f"  ties={ties}")
    if unfinished:
        print(f"  unfinished={unfinished}")


if __name__ == "__main__":
    main()
