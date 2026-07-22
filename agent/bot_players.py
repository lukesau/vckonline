"""Server-side bot players for lobby games.

The server (server.py) lets lobby creators add bots at three difficulty
levels; this module owns the level registry, per-game policy instances, and
the synchronous "let every pending bot act" step the server's async driver
calls. All game mutation happens on the caller's thread (the server drives it
from the event loop); only MCTS analysis is offloaded by the server to an
executor using a cloned game.
"""

import contextlib
import io

from agent.headless import acting_player_ids, apply_move, legal_moves
from agent.play_random import _fingerprint

BOT_LEVELS = {
    "easy": "Easy Bot",
    "medium": "Medium Bot",
    "hard": "Hard Bot",
}

# Hard-bot search budget: enough to beat greedy ~90% while keeping decisions
# around a second on modest server hardware.
HARD_BOT_ITERATIONS = 100

_SINK = io.StringIO()


def make_policy(level):
    from agent.policies import GreedyPolicy, RandomPolicy

    if level == "easy":
        return RandomPolicy()
    if level == "medium":
        return GreedyPolicy()
    if level == "hard":
        from agent.mcts import MCTSPolicy
        from agent.value_net import DEFAULT_MODEL_PATH

        return MCTSPolicy(iterations=HARD_BOT_ITERATIONS, value_path=DEFAULT_MODEL_PATH)
    raise ValueError(f"unknown bot level {level!r}")


def pending_bot_decision(game, bot_levels):
    """(player_id, level, moves) for the first bot owing a decision, else None."""
    if getattr(game, "phase", None) == "game_over":
        return None
    for pid in acting_player_ids(game):
        level = bot_levels.get(pid)
        if level is None:
            continue
        moves = legal_moves(game, pid)
        if moves:
            return pid, level, moves
    return None


def apply_bot_decision(game, pid, moves, decision):
    """Apply the decision's chosen move (falling back through ranked candidates,
    then remaining legal moves). Returns True if the game state progressed."""
    ranked = []
    if decision:
        chosen = decision.get("chosen")
        if chosen is not None:
            ranked.append(chosen)
        for c in decision.get("candidates") or []:
            if c.get("move") is not None and c["move"] is not chosen:
                ranked.append(c["move"])
    seen = {id(m) for m in ranked}
    ranked.extend(m for m in moves if id(m) not in seen)

    before = _fingerprint(game)
    for move in ranked:
        try:
            with contextlib.redirect_stdout(_SINK):
                apply_move(game, move)
        except (ValueError, KeyError, IndexError):
            continue
        if _fingerprint(game) != before:
            _SINK.seek(0)
            _SINK.truncate(0)
            return True
    _SINK.seek(0)
    _SINK.truncate(0)
    return False


def choose_sync(policy, game, pid, moves):
    """Synchronous decision (fast policies; also used inside the executor for
    MCTS against a cloned game). Returns the decision dict (or a minimal one)."""
    analyze = getattr(policy, "analyze", None)
    with contextlib.redirect_stdout(_SINK):
        if callable(analyze):
            decision = analyze(game, pid, moves)
        else:
            decision = {"chosen": policy.choose(game, None, pid, moves), "candidates": []}
    _SINK.seek(0)
    _SINK.truncate(0)
    return decision
