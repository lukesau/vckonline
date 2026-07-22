"""Smoke driver: play full random-policy games headlessly and report results.

Usage: python -m agent.play_random --games 5 --seed 1 [--verbose]
"""

import argparse
import contextlib
import io
import random
import time

from agent.headless import (
    acting_player_ids,
    advance,
    apply_move,
    legal_moves,
    new_game,
    progress_signature,
)

_SINK = io.StringIO()


def _quiet(fn, *args, **kwargs):
    """The engine print()s liberally; keep the hot loop's stdout clean and fast."""
    with contextlib.redirect_stdout(_SINK):
        result = fn(*args, **kwargs)
    _SINK.seek(0)
    _SINK.truncate(0)
    return result


def _fingerprint(game):
    return progress_signature(game)


def _prompt_debug(game):
    return (
        f"phase={game.phase!r} action_required={game.action_required!r} "
        f"pending_required_choice={game.pending_required_choice!r} "
        f"concurrent={game.concurrent_action!r}"
    )


def _pick_move(moves):
    """Random, but biased toward buying/slaying over hoarding resources."""
    builders = [m for m in moves if m.get("action_type") in ("hire_citizen", "build_domain", "slay_monster")]
    if builders and random.random() < 0.75:
        pool = builders
    else:
        pool = moves
    move = random.choice(pool)
    moves.remove(move)
    return move


def play_random_game(seed=None, max_steps=20000, verbose=False, preset="base1"):
    game = new_game(seed=seed, preset=preset)
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
            while moves:
                move = _pick_move(moves)
                try:
                    _quiet(apply_move, game, move)
                except (ValueError, KeyError, IndexError) as e:
                    if verbose:
                        print(f"  rejected {move}: {e}")
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
                raise RuntimeError(f"All moves were no-ops ({noops!r}) at {_prompt_debug(game)}")
            continue
        if not _quiet(game.advance_tick):
            raise RuntimeError(f"Stalled at step {steps} with no legal moves: {_prompt_debug(game)}")
        _quiet(advance, game)
        stuck_streak = 0
    return game, steps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--preset", default="base1")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    total_time = 0.0
    wins = {}
    for i in range(args.games):
        seed = None if args.seed is None else args.seed + i
        start = time.perf_counter()
        game, steps = play_random_game(seed=seed, verbose=args.verbose, preset=args.preset)
        elapsed = time.perf_counter() - start
        total_time += elapsed
        if game.phase != "game_over":
            print(f"game {i + 1}: seed={seed} UNFINISHED after {steps} steps (turn {game.turn_number})")
            continue
        result = game.final_result or {}
        for pid in result.get("winner_player_ids") or []:
            wins[pid] = wins.get(pid, 0) + 1
        print(
            f"game {i + 1}: seed={seed} steps={steps} turns={game.turn_number} "
            f"time={elapsed:.2f}s -> {result.get('headline', '?')}"
        )
        for row in game.final_scores or []:
            print(
                f"    #{row['rank']} {row['name']}: {row['total_vp']} VP "
                f"(base {row['base_vp']} + duke {row['duke_vp']}, tableau {row['tableau_size']})"
            )
    print(f"\n{args.games} game(s), avg {total_time / max(args.games, 1):.2f}s per game, wins by seat: {wins}")


if __name__ == "__main__":
    main()
