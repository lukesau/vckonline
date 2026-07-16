"""Headless, in-process game driver for large-scale simulation.

This is the fast path that bypasses the HTTP server, the lobby flow, and any
polling: it builds a `Game` directly, serializes it to the canonical wire dict,
enumerates legal moves via `engines.available_actions`, and applies the exact
same move dicts back onto the live `Game` object.

`apply_move` is a framework-agnostic re-implementation of the essential parts of
`server.perform_game_action` (action consumption, the engine call, end-of-turn
finish, and phase pumping) with plain exceptions instead of `HTTPException`. It
handles exactly the action types `enumerate_actions` can emit for the base game.

Randomness: the engine uses the process-global `random` module (dice in
`roll_phase`, deck shuffles in `game_setup`). Seed once per process/game via
`seed_everything(...)` and run one game at a time per process for reproducible
results. Parallelism should be across processes (see `scripts/run_headless_sim.py`),
never threads sharing the global RNG.
"""

import json
import random

from game import Game
from game_models import GameMember
from game_serialization import GameObjectEncoder

_AUTO_PHASES = ("roll", "harvest")
_MAX_PUMP = 10000


def seed_everything(seed):
    """Seed the process-global RNG the engine draws from."""
    random.seed(seed)


def serialize_state(game):
    """Full (non-redacted) wire dict, the shape `enumerate_actions` expects."""
    return json.loads(json.dumps(game, cls=GameObjectEncoder))


def _pump_auto_phases(game):
    """Advance through automatic roll/harvest ticks until a decision is needed.

    Mirrors the server's GET /state and finalize_roll pumping: it never
    over-advances past the action phase.
    """
    steps = 0
    while getattr(game, "phase", None) in _AUTO_PHASES:
        if not game.advance_tick():
            break
        if getattr(game, "phase", None) == "action":
            break
        steps += 1
        if steps > _MAX_PUMP:
            raise RuntimeError("Auto-phase pump exceeded max iterations (stuck engine?)")


def build_game(preset="base", num_players=2, player_names=None,
               debug_mode=False, duke_select_count=2, game_id=None):
    """Deal a fresh game and pump it to the first real decision point.

    Requires DB connectivity (card data comes from MariaDB via
    `game_setup.load_game_data`). Returns a live `Game`.
    """
    from game_setup import load_game_data

    if game_id is None:
        import uuid
        game_id = str(uuid.uuid4())

    if player_names is None:
        player_names = [f"Bot{i + 1}" for i in range(num_players)]
    if len(player_names) != num_players:
        raise ValueError("player_names length must match num_players")

    import uuid
    gamers = [GameMember(str(uuid.uuid4()), name, game_id) for name in player_names]

    game_state = load_game_data(
        game_id,
        preset,
        gamers,
        debug_mode=debug_mode,
        duke_select_count=duke_select_count,
    )
    game = Game(game_state)
    _pump_auto_phases(game)
    return game


def legal_moves(game, player_id, state=None):
    """Legal moves for `player_id` from the current (or supplied) state dict.

    Stamps the acting player's engine-computed effective costs onto the state
    first so emitted payments always match what the engine will charge.
    """
    from engines.available_actions import annotate_effective_costs, enumerate_actions

    if state is None:
        state = serialize_state(game)
    annotate_effective_costs(game, state, player_id)
    return enumerate_actions(state, player_id)


def players_to_act(game, state=None):
    """Player ids that currently have at least one legal move.

    In a normal turn this is a single active player; during a concurrent gate
    (e.g. simultaneous duke selection) it can be several.
    """
    if state is None:
        state = serialize_state(game)
    result = []
    for p in state.get("player_list") or []:
        pid = p.get("player_id")
        if pid and legal_moves(game, pid, state=state):
            result.append(pid)
    return result


def is_game_over(game):
    return (getattr(game, "phase", None) or "").strip() == "game_over"


def _payment(move):
    pay = move.get("payment") or {}
    return int(pay.get("gold") or 0), int(pay.get("strength") or 0), int(pay.get("magic") or 0)


def _rollback_consumed_action(game):
    """Undo a consume_player_action when the underlying engine call failed.

    Mirrors server.perform_game_action's rollback so a rejected move never
    leaves a phantom-consumed action behind (which would corrupt retries).
    """
    lifecycle = getattr(game, "lifecycle", None)
    rollback = getattr(lifecycle, "rollback_last_consumed_action", None)
    if callable(rollback):
        rollback()
        return
    game.actions_remaining = int(getattr(game, "actions_remaining", 0)) + 1
    game.tick_id = int(getattr(game, "tick_id", 0)) - 1


def apply_move(game, move):
    """Apply one enumerated move dict to `game` in place.

    Raises ValueError on an illegal move. After a successful move the engine is
    pumped through any automatic roll/harvest phases so the game is left at the
    next decision point.
    """
    action_type = move.get("action_type")
    route = move.get("_route")
    player_id = move.get("player_id")

    if route == "apply_event_slay_cost":
        game.apply_event_slay_cost(
            player_id,
            monster_id=move.get("monster_id"),
            event_id=move.get("event_id"),
        )
        _pump_auto_phases(game)
        return game

    if action_type == "take_resource":
        if not game.consume_player_action(player_id, action_type="take_resource"):
            raise ValueError("Not your turn (or no actions remaining)")
        try:
            game.take_resource(player_id, str(move["resource"]).strip().lower())
        except Exception:
            _rollback_consumed_action(game)
            raise
        game.finish_turn_if_no_actions_remaining()

    elif action_type == "hire_citizen":
        if not game.consume_player_action(player_id, action_type="hire_citizen"):
            raise ValueError("Not your turn (or no actions remaining)")
        g, s, m = _payment(move)
        try:
            game.hire_citizen(player_id, move["citizen_id"], g, m, s)
        except Exception:
            _rollback_consumed_action(game)
            raise
        if not game.resolve_bonus_recruit_if_consumed():
            game.finish_turn_if_no_actions_remaining()

    elif action_type == "build_domain":
        if not game.consume_player_action(player_id, action_type="build_domain"):
            raise ValueError("Not your turn (or no actions remaining)")
        g, s, m = _payment(move)
        try:
            game.build_domain(player_id, move["domain_id"], g, m, s)
        except Exception:
            _rollback_consumed_action(game)
            raise
        game.finish_turn_if_no_actions_remaining()

    elif action_type == "slay_monster":
        if not game.consume_player_action(player_id, action_type="slay_monster"):
            raise ValueError("Not your turn (or no actions remaining)")
        g, s, m = _payment(move)
        try:
            game.slay_monster(
                player_id,
                move.get("monster_id"),
                s, m, g,
                event_id=move.get("event_id"),
            )
        except Exception:
            _rollback_consumed_action(game)
            raise
        game.finish_turn_if_no_actions_remaining()

    elif action_type == "act_on_required_action":
        game.act_on_required_action(player_id, move["action"])
        game.advance_tick()

    elif action_type == "submit_concurrent_action":
        game.submit_concurrent_action(player_id, move["response"], kind=move.get("kind"))

    elif action_type == "finalize_roll":
        game.finalize_roll(player_id, die_one=move.get("die_one"), die_two=move.get("die_two"))

    elif action_type == "harvest_card":
        game.harvest_card(player_id, str(move["harvest_slot_key"]).strip())

    else:
        raise ValueError(f"headless apply_move cannot handle action_type={action_type!r}")

    _pump_auto_phases(game)
    return game


class StalledGameError(RuntimeError):
    """Raised when no legal move (and no forced tick) makes the game progress.

    Carries the offending prompt so batch runs can log which enumeration gap
    stalled instead of hanging forever.
    """


def progress_signature(game):
    """Cheap fingerprint of "did anything meaningful change" (no serialization).

    Used to detect moves the engine accepts but that don't advance the game
    (e.g. a prompt whose required action-string grammar the enumerator got
    wrong), which would otherwise livelock an unattended run.
    """
    ar = getattr(game, "action_required", None) or {}
    prc = getattr(game, "pending_required_choice", None) or {}
    ca = getattr(game, "concurrent_action", None) or {}
    scores = tuple(
        (
            int(getattr(p, "gold_score", 0) or 0),
            int(getattr(p, "strength_score", 0) or 0),
            int(getattr(p, "magic_score", 0) or 0),
            int(getattr(p, "victory_score", 0) or 0),
            len(getattr(p, "owned_citizens", []) or []),
            len(getattr(p, "owned_domains", []) or []),
            len(getattr(p, "owned_monsters", []) or []),
        )
        for p in getattr(game, "player_list", []) or []
    )
    return (
        int(getattr(game, "tick_id", 0) or 0),
        getattr(game, "phase", None),
        int(getattr(game, "turn_number", 0) or 0),
        ar.get("action"), ar.get("id"),
        prc.get("kind"), prc.get("stage"),
        tuple(ca.get("pending") or ()),
        scores,
    )


def final_scores(game):
    """List of {player_id, name, victory_score, gold, strength, magic} sorted best-first."""
    rows = []
    for p in getattr(game, "player_list", []) or []:
        rows.append({
            "player_id": getattr(p, "player_id", None),
            "name": getattr(p, "name", "?"),
            "victory_score": int(getattr(p, "victory_score", 0) or 0),
            "gold": int(getattr(p, "gold_score", 0) or 0),
            "strength": int(getattr(p, "strength_score", 0) or 0),
            "magic": int(getattr(p, "magic_score", 0) or 0),
        })
    rows.sort(key=lambda r: (-r["victory_score"], -(r["gold"] + r["strength"] + r["magic"])))
    return rows


def _try_move_with_progress(game, move):
    """Apply `move`; return True only if it advanced the game.

    A move that raises ValueError, or that the engine accepts but which leaves
    the progress signature unchanged (an ineffective no-op), returns False so
    the caller can try a different move instead of livelocking.
    """
    sig_before = progress_signature(game)
    try:
        apply_move(game, move)
    except ValueError:
        return False
    return progress_signature(game) != sig_before or is_game_over(game)


def play_random_game(game, rng=None, max_steps=200000):
    """Drive `game` to completion picking a uniform-random legal move each step.

    Returns a result dict with final scores, winner, and step/turn counts.
    Raises `StalledGameError` if a decision point offers no move that advances
    the game (an enumeration gap), rather than hanging.
    """
    rng = rng or random
    steps = 0
    while not is_game_over(game):
        if steps >= max_steps:
            raise StalledGameError(f"exceeded {max_steps} steps (non-terminating?)")
        state = serialize_state(game)
        actors = players_to_act(game, state=state)
        if not actors:
            # No one can act but the game is not over -> try to nudge the engine.
            if not game.advance_tick():
                raise StalledGameError("no legal moves and engine will not advance")
            continue
        actor = actors[0]
        moves = legal_moves(game, actor, state=state)

        pool = list(moves)
        rng.shuffle(pool)
        advanced = False
        for cand in pool:
            if _try_move_with_progress(game, cand):
                advanced = True
                break
        if not advanced:
            # Every offered move was rejected or a no-op. Try to force the engine
            # forward once; if that also does nothing, this is a real gap.
            if game.advance_tick() and progress_signature(game):
                steps += 1
                continue
            ar = getattr(game, "action_required", None) or {}
            prc = getattr(game, "pending_required_choice", None) or {}
            raise StalledGameError(
                f"stalled at phase={getattr(game, 'phase', None)} "
                f"turn={getattr(game, 'turn_number', None)} "
                f"action={ar.get('action')!r} prc_kind={prc.get('kind')!r} "
                f"actor={actor} n_moves={len(moves)}"
            )
        steps += 1

    scores = final_scores(game)
    winner = scores[0] if scores else None
    return {
        "steps": steps,
        "turn_number": int(getattr(game, "turn_number", 0) or 0),
        "scores": scores,
        "winner_player_id": winner["player_id"] if winner else None,
        "winner_name": winner["name"] if winner else None,
        "winning_score": winner["victory_score"] if winner else None,
    }
