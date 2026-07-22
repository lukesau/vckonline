"""Move-quality grading: compare a player's move to the Hard bot's analysis.

Categories (win-probability sacrificed vs the bot's best move, from MCTS root
Q-values, both from the acting player's perspective):

  perfect  — exactly the move the bot would have played
  great    — sacrifices <= 2%
  fine     — sacrifices 2-8%
  blunder  — sacrifices  > 8%
  unrated  — the move fell outside the analyzed candidate set (prior-pruned),
             so no honest Q comparison exists

Only decisions with >= 2 legal moves are graded (forced moves teach nothing).
Analysis runs on a clone in an executor AFTER the action is applied, so the
player never waits on it; feedback arrives with the next state push.
"""

import contextlib
import io

from agent.move_summary import move_label

GREAT_THRESHOLD = 0.02
FINE_THRESHOLD = 0.08
ANALYSIS_ITERATIONS = 300

CATEGORIES = ("perfect", "great", "fine", "blunder", "unrated")

_SINK = io.StringIO()


def analysis_policy():
    from agent.mcts import MCTSPolicy
    from agent.value_net import DEFAULT_MODEL_PATH

    return MCTSPolicy(iterations=ANALYSIS_ITERATIONS, value_path=DEFAULT_MODEL_PATH)


def normalize_move(move):
    """Canonical comparable form of a move dict: drop private/None fields,
    reduce payments to their integer amounts, ignore `kind` (the response
    string already carries the prompt id)."""
    out = {}
    for key, value in (move or {}).items():
        if key.startswith("_") or value is None or key == "kind":
            continue
        if key == "payment":
            pay = value if isinstance(value, dict) else value.__dict__
            out["payment"] = {
                r: int(pay.get(r) or 0) for r in ("gold", "strength", "magic")
            }
        elif key == "slot_indices":
            out[key] = sorted(int(i) for i in value)
        else:
            out[key] = value
    return out


def moves_equivalent(a, b):
    return normalize_move(a) == normalize_move(b)


def classify(delta):
    if delta <= GREAT_THRESHOLD:
        return "great"
    if delta <= FINE_THRESHOLD:
        return "fine"
    return "blunder"


def grade_move(decision, submitted_move, game=None):
    """Grade `submitted_move` against an MCTSPolicy.analyze() decision taken at
    the same (pre-move) state. Returns a feedback dict."""
    bot_move = decision.get("chosen")
    candidates = decision.get("candidates") or []
    bot_label = move_label(bot_move, game) if bot_move is not None else "?"
    your_label = move_label(submitted_move, game)

    if bot_move is not None and moves_equivalent(submitted_move, bot_move):
        return {
            "category": "perfect",
            "delta_pct": 0.0,
            "your_label": your_label,
            "bot_label": bot_label,
        }

    bot_q = chosen_q = None
    for entry in candidates:
        if bot_q is None and bot_move is not None and moves_equivalent(entry["move"], bot_move):
            bot_q = float(entry.get("q") or 0.0)
        if chosen_q is None and moves_equivalent(entry["move"], submitted_move):
            chosen_q = float(entry.get("q") or 0.0)

    if bot_q is None or chosen_q is None:
        return {
            "category": "unrated",
            "delta_pct": None,
            "your_label": your_label,
            "bot_label": bot_label,
        }

    delta = max(0.0, bot_q - chosen_q)
    return {
        "category": classify(delta),
        "delta_pct": round(delta * 100.0, 1),
        "your_label": your_label,
        "bot_label": bot_label,
    }


def analyze_and_grade(game, player_id, submitted_move):
    """Full grading pass against `game` (a pre-move CLONE; takes seconds).
    Returns the feedback dict, or None when the decision isn't gradable."""
    from agent.hints import player_pending_moves

    moves = player_pending_moves(game, player_id)
    if moves is None or len(moves) < 2:
        return None
    policy = analysis_policy()
    try:
        with contextlib.redirect_stdout(_SINK):
            decision = policy.analyze(game, player_id, moves)
    finally:
        close = getattr(policy, "close", None)
        if callable(close):
            close()
        _SINK.seek(0)
        _SINK.truncate(0)
    return grade_move(decision, submitted_move, game)


def empty_tally():
    return {c: 0 for c in CATEGORIES}
