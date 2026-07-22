"""Validation pass: play many seeded games while asserting engine/driver invariants.

Usage: python -m agent.validate --games 200 --seed 1 [--parity-every 1]

Checks per step:
  - legal_moves via serialize_state matches wire_state enumeration path
    (--parity-every controls sampling)
  - no player resource ever goes negative; actions_remaining stays sane
  - phase is always a known value
Checks per game:
  - the game terminates within the step cap
  - final_scores/final_result are present and internally consistent
  - mid-game serialize -> deserialize -> serialize round trip is stable
"""

import argparse
import contextlib
import io
import json
import random
import time

from engines.available_actions import annotate_effective_costs, enumerate_actions

from agent.headless import (
    acting_player_ids,
    advance,
    apply_move,
    legal_moves,
    new_game,
    serialize_state,
    wire_state,
)
from agent.play_random import _fingerprint, _pick_move, _prompt_debug

KNOWN_PHASES = {
    "setup", "roll", "roll_pending", "harvest", "action",
    "action_end_pending", "game_over",
}

_SINK = io.StringIO()


class ValidationError(AssertionError):
    pass


def _check_resources(game):
    for p in game.player_list:
        for attr in ("gold_score", "strength_score", "magic_score", "victory_score"):
            value = int(getattr(p, attr, 0) or 0)
            if value < 0:
                raise ValidationError(f"{p.player_id}.{attr} = {value} (negative)")
    ar = int(game.actions_remaining or 0)
    if ar < 0 or ar > 10:
        raise ValidationError(f"actions_remaining = {ar}")
    if game.phase not in KNOWN_PHASES:
        raise ValidationError(f"unknown phase {game.phase!r}")


def _check_move_parity(game, state):
    wire = wire_state(game)
    for p in game.player_list:
        pid = p.player_id
        slow_moves = legal_moves(game, pid, state=state)
        annotate_effective_costs(game, wire, pid)
        wire_moves = enumerate_actions(wire, pid)
        if slow_moves != wire_moves:
            raise ValidationError(
                f"move parity mismatch for {pid}:\n  slow={slow_moves!r}\n  wire={wire_moves!r}"
            )


def _check_roundtrip(game):
    from game_serialization import (
        deserialize_save_dict_to_game,
        serialize_game_to_save_dict,
    )

    save1 = serialize_game_to_save_dict(game)
    clone = deserialize_save_dict_to_game(json.loads(json.dumps(save1)))
    save2 = serialize_game_to_save_dict(clone)
    if json.dumps(save1, sort_keys=True) != json.dumps(save2, sort_keys=True):
        d1, d2 = json.dumps(save1, sort_keys=True), json.dumps(save2, sort_keys=True)
        for i, (a, b) in enumerate(zip(d1, d2)):
            if a != b:
                raise ValidationError(
                    f"serialize round trip diverges at char {i}: "
                    f"...{d1[i-60:i+60]}... vs ...{d2[i-60:i+60]}..."
                )
        raise ValidationError("serialize round trip: length mismatch")


def _check_final(game):
    scores = game.final_scores
    result = game.final_result
    if not scores or not result:
        raise ValidationError("game_over without final_scores/final_result")
    ranked = sorted(
        scores,
        key=lambda r: (-int(r["total_vp"]), -int(r["tableau_size"])),
    )
    for expect_rank, row in enumerate(ranked, start=1):
        actual = next(r for r in scores if r["player_id"] == row["player_id"])
        if int(actual["rank"]) != expect_rank and not actual.get("tied_on_vp"):
            raise ValidationError(
                f"rank inconsistency: {actual['name']} rank={actual['rank']} expected={expect_rank}"
            )
    winners = set(result.get("winner_player_ids") or [])
    if result.get("kind") in ("win", "tiebreak") and not winners:
        raise ValidationError(f"{result.get('kind')} result with no winners")


def validate_game(seed, max_steps=20000, parity_every=1):
    game = new_game(seed=seed)
    with contextlib.redirect_stdout(_SINK):
        advance(game)
    _SINK.seek(0), _SINK.truncate(0)
    roundtrip_step = random.randrange(20, 120)
    steps = 0
    stuck_streak = 0
    while game.phase != "game_over":
        steps += 1
        if steps > max_steps:
            raise ValidationError(f"did not terminate in {max_steps} steps: {_prompt_debug(game)}")
        state = serialize_state(game)
        if parity_every and steps % parity_every == 0:
            _check_move_parity(game, state)
        if steps == roundtrip_step:
            _check_roundtrip(game)
        before = _fingerprint(game)
        moved = False
        noops = []
        for pid in acting_player_ids(game):
            moves = legal_moves(game, pid, state=state)
            while moves:
                move = _pick_move(moves)
                try:
                    with contextlib.redirect_stdout(_SINK):
                        apply_move(game, move)
                except (ValueError, KeyError, IndexError):
                    continue
                finally:
                    _SINK.seek(0), _SINK.truncate(0)
                if _fingerprint(game) == before:
                    noops.append(move)
                    continue
                moved = True
                break
            if moved:
                break
        _check_resources(game)
        if moved:
            stuck_streak = 0
            continue
        if noops:
            stuck_streak += 1
            if stuck_streak >= 5:
                raise ValidationError(f"all moves no-ops ({noops!r}) at {_prompt_debug(game)}")
            continue
        with contextlib.redirect_stdout(_SINK):
            if not game.advance_tick():
                raise ValidationError(f"stalled: {_prompt_debug(game)}")
            advance(game)
        _SINK.seek(0), _SINK.truncate(0)
        stuck_streak = 0
    _check_final(game)
    return steps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--parity-every",
        type=int,
        default=1,
        help="check serialize/wire move parity every N steps (0 = off)",
    )
    args = parser.parse_args()

    start = time.perf_counter()
    failures = 0
    for i in range(args.games):
        seed = args.seed + i
        try:
            validate_game(seed, parity_every=args.parity_every)
        except ValidationError as e:
            failures += 1
            print(f"seed {seed}: FAIL {e}")
        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{args.games} games validated")
    elapsed = time.perf_counter() - start
    print(
        f"\n{args.games} games validated in {elapsed:.1f}s "
        f"({failures} failure(s))" + (" — ALL PASS" if failures == 0 else "")
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
