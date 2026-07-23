"""Hint generation: "what would the Hard bot do here?" for the in-game button.

compute_hint runs a determinized MCTS analysis of the player's current
decision on a CLONE of the game (callers pass the clone; the server offloads
this to an executor) and formats the result as short human-readable text via
move_summary.move_label, e.g. "Slay Goblin (5s)" or "Hire Cleric (3g)".
"""

import contextlib
import io

from agent.bot_players import env_int, pending_bot_decision  # noqa: F401  (re-export convenience)
from agent.headless import acting_player_ids, legal_moves
from agent.move_summary import move_label

# Latency-sensitive: the player is waiting on the response.
HINT_ITERATIONS = env_int("VCKO_HINT_ITERATIONS", 200)
HINT_WORKERS = env_int("VCKO_HINT_WORKERS", 1)

_SINK = io.StringIO()


def _hint_policy():
    from agent.mcts import MCTSPolicy
    from agent.value_net import DEFAULT_MODEL_PATH

    return MCTSPolicy(
        iterations=HINT_ITERATIONS, workers=HINT_WORKERS, value_path=DEFAULT_MODEL_PATH
    )


def pretty_label(move, game=None):
    label = move_label(move, game)
    return label[:1].upper() + label[1:] if label else label


def player_pending_moves(game, player_id):
    """Legal moves if `player_id` currently owes the game a decision, else None."""
    if getattr(game, "phase", None) == "game_over":
        return None
    if player_id not in acting_player_ids(game):
        return None
    moves = legal_moves(game, player_id)
    return moves or None


def compute_hint(game, player_id):
    """Analyze `game` (a clone — this mutates nothing but takes seconds) and
    return a JSON-ready hint dict, or None if the player owes no decision."""
    moves = player_pending_moves(game, player_id)
    if moves is None:
        return None
    if len(moves) == 1:
        return {
            "hint": pretty_label(moves[0], game),
            "only_move": True,
            "candidates": [],
        }
    policy = _hint_policy()
    try:
        with contextlib.redirect_stdout(_SINK):
            decision = policy.analyze(game, player_id, moves)
    finally:
        close = getattr(policy, "close", None)
        if callable(close):
            close()
        _SINK.seek(0)
        _SINK.truncate(0)
    chosen = decision.get("chosen") or moves[0]
    candidates = []
    for entry in (decision.get("candidates") or [])[:3]:
        candidates.append({
            "label": pretty_label(entry["move"], game),
            "visit_pct": round(float(entry.get("visit_pct") or 0.0), 1),
        })
    return {
        "hint": pretty_label(chosen, game),
        "only_move": False,
        "iterations": HINT_ITERATIONS,
        "candidates": candidates,
    }
