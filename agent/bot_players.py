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
import os

from agent.headless import acting_player_ids, apply_move, legal_moves
from agent.play_random import _fingerprint

BOT_LEVELS = {
    "easy": "Easy Bot",
    "medium": "Medium Bot",
    "hard": "Hard Bot",
}


def env_int(name, default):
    """Deploy-tunable integer knob (invalid/unset values fall back silently)."""
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


def env_flag(name, default):
    """Deploy-tunable boolean knob (accepts 1/0, true/false, on/off, yes/no)."""
    raw = (os.environ.get(name) or "").strip().lower()
    if raw in ("1", "true", "on", "yes"):
        return True
    if raw in ("0", "false", "off", "no"):
        return False
    return default


# Hard-bot search budget: one deep tree. Head-to-head A/Bs (20 games each)
# showed 1000x1 beats 400x1 14-6, while every parallel split tried lost or
# tied at equal-or-larger budgets (800x8 lost 6-14 to 800x1; 4000x8 root and
# sequential-halving both lost 8-12 to 1000x1) — merged independent trees
# trade away the depth that actually pays. ~8.5s/decision, play-tested as
# acceptable pacing. Iterations are SPLIT across `workers` when workers > 1
# (see MCTSPolicy.parallel_mode); all three knobs are deploy-tunable.
HARD_BOT_ITERATIONS = env_int("VCKO_HARD_BOT_ITERATIONS", 1000)
HARD_BOT_WORKERS = env_int("VCKO_HARD_BOT_WORKERS", 1)
HARD_BOT_MODE = (os.environ.get("VCKO_HARD_BOT_MODE") or "root").strip().lower()
# Turn-aware root priors (see MCTSPolicy.turn_priors). A/B'd flat for play
# strength at 100 iters (21-18-1 over 40 games); ON for the bot at the
# user's request to judge combo play by feel — flip via the env var (or
# revert this default) if it doesn't hold up at the table.
HARD_BOT_TURN_PRIORS = env_flag("VCKO_HARD_BOT_TURN_PRIORS", True)

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

        return MCTSPolicy(
            iterations=HARD_BOT_ITERATIONS,
            workers=HARD_BOT_WORKERS,
            parallel_mode=HARD_BOT_MODE,
            turn_priors=HARD_BOT_TURN_PRIORS,
            value_path=DEFAULT_MODEL_PATH,
        )
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
