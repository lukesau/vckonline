"""Smoke driver: play full random-policy games headlessly and report results.

Usage: python -m agent.play_random --games 5 --seed 1 [--verbose]
"""

import argparse
import contextlib
import io
import random
import time

from agent.headless import acting_player_ids, advance, apply_move, new_game, wire_state
from agent.moves import enumerate_moves

_SINK = io.StringIO()


def _quiet(fn, *args, **kwargs):
    """The engine print()s liberally; keep the hot loop's stdout clean and fast."""
    with contextlib.redirect_stdout(_SINK):
        result = fn(*args, **kwargs)
    _SINK.seek(0)
    _SINK.truncate(0)
    return result


def _fingerprint(game):
    ca = getattr(game, "concurrent_action", None) or {}
    data = ca.get("data") or {}
    prompts = data.get("prompts") or {}
    return (
        game.phase,
        game.turn_number,
        game.actions_remaining,
        int(getattr(game, "tick_id", 0) or 0),
        len(game.game_log or []),
        repr(game.action_required),
        repr(game.pending_required_choice),
        ca.get("kind"),
        data.get("phase"),
        tuple(ca.get("pending") or ()),
        tuple(sorted(ca.get("completed") or ())),
        len(ca.get("responses") or {}),
        tuple(
            (pid, tuple(p.get("id") for p in (v or []) if isinstance(p, dict)))
            for pid, v in sorted(prompts.items())
        ),
    )


def _prompt_debug(game):
    return (
        f"phase={game.phase!r} action_required={game.action_required!r} "
        f"pending_required_choice={game.pending_required_choice!r} "
        f"concurrent={game.concurrent_action!r}"
    )


def _pick_move(moves):
    """Random, but biased toward buying/slaying over hoarding resources.

    Pure-uniform play hoards resources and can leave the end-game conditions
    (stack exhaustion) unreached for hundreds of turns; preferring the moves
    that deplete stacks keeps playouts finite and is a more realistic baseline.
    """
    builders = [m for m in moves if m.get("action_type") in ("hire_citizen", "build_domain", "slay_monster")]
    if builders and random.random() < 0.75:
        pool = builders
    else:
        pool = moves
    move = random.choice(pool)
    moves.remove(move)
    return move


def play_random_game(seed=None, max_steps=20000, verbose=False):
    game = new_game(seed=seed)
    _quiet(advance, game)
    steps = 0
    stuck_streak = 0
    while game.phase != "game_over":
        steps += 1
        if steps > max_steps:
            return game, steps  # unfinished; caller reports phase != game_over
        state = wire_state(game)
        before = _fingerprint(game)
        moved = False
        noops = []
        for pid in acting_player_ids(game):
            moves = enumerate_moves(state, pid)
            while moves:
                move = _pick_move(moves)
                try:
                    _quiet(apply_move, game, move)
                except (ValueError, KeyError, IndexError) as e:
                    if verbose:
                        print(f"  rejected {move}: {e}")
                    continue
                if _fingerprint(game) == before:
                    # Either the engine silently ignored a malformed response,
                    # or our snapshot went stale mid-step; retry from fresh.
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
            continue  # re-snapshot and retry
        if not _quiet(game.advance_tick):
            raise RuntimeError(f"Stalled at step {steps} with no legal moves: {_prompt_debug(game)}")
        _quiet(advance, game)
        stuck_streak = 0
    return game, steps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    total_time = 0.0
    wins = {}
    for i in range(args.games):
        seed = None if args.seed is None else args.seed + i
        start = time.perf_counter()
        game, steps = play_random_game(seed=seed, verbose=args.verbose)
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
