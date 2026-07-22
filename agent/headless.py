"""Build and drive Game objects entirely in-process: no server, no HTTP, no MariaDB."""

import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent import fake_db


class LobbyMember:
    """Duck-typed stand-in for GameMember — load_game_data reads .player_id and .name."""

    def __init__(self, player_id, name):
        self.player_id = player_id
        self.name = name


def new_game(preset="base1", num_players=2, seed=None, game_id="headless"):
    """Deal a fresh game via the real load_game_data, backed by the seed-file fake DB."""
    fake_db.install()
    if seed is not None:
        random.seed(seed)
    from game import Game
    from game_setup import load_game_data

    members = [LobbyMember(f"p{i + 1}", f"Player {i + 1}") for i in range(num_players)]
    state = load_game_data(game_id, preset, members)
    return Game(state)


def advance(game):
    """Run the engine forward until it blocks on a decision or the game ends.

    Same loop the server uses; advance_tick() is self-guarding (returns False
    while a prompt, concurrent gate, roll finalization, or player action is due).
    """
    while game.phase != "game_over" and game.advance_tick():
        pass


def wire_state(game):
    """Serialize to the client wire format that bots/legal_moves.py enumerates against."""
    from game import GameObjectEncoder

    return json.loads(json.dumps(game, cls=GameObjectEncoder))


def clone_game(game):
    """Independent copy via the engine's supported save/load round trip."""
    from game_serialization import (
        deserialize_save_dict_to_game,
        serialize_game_to_save_dict,
    )

    return deserialize_save_dict_to_game(json.loads(json.dumps(serialize_game_to_save_dict(game))))


def acting_player_ids(game):
    """Player ids that may currently owe the game a decision, in priority order."""
    ca = getattr(game, "concurrent_action", None) or {}
    if ca.get("pending"):
        return list(ca["pending"])
    req = getattr(game, "action_required", None) or {}
    if req.get("id"):
        return [req["id"]]
    return [p.player_id for p in game.player_list]


def apply_move(game, move):
    """Apply one POST-ready move dict (from bots/legal_moves.enumerate_actions),
    mirroring server.py's dispatch — same methods, same argument order."""
    pid = move["player_id"]

    if move.get("_route") == "apply_event_slay_cost":
        game.apply_event_slay_cost(
            pid, monster_id=move.get("monster_id"), event_id=move.get("event_id")
        )
        advance(game)
        return

    action_type = move["action_type"]
    pay = move.get("payment") or {}
    gp, sp, mp = pay.get("gold", 0), pay.get("strength", 0), pay.get("magic", 0)

    if action_type == "submit_concurrent_action":
        game.submit_concurrent_action(pid, move["response"], kind=move.get("kind"))
    elif action_type == "act_on_required_action":
        game.act_on_required_action(pid, move["action"])
    elif action_type == "finalize_roll":
        game.finalize_roll(pid, die_one=move.get("die_one"), die_two=move.get("die_two"))
    elif action_type == "harvest_card":
        game.harvest_card(pid, move["harvest_slot_key"])
    elif action_type in ("hire_citizen", "build_domain", "slay_monster", "take_resource"):
        game.consume_player_action(pid, action_type=action_type)
        try:
            if action_type == "hire_citizen":
                game.hire_citizen(pid, move["citizen_id"], gp, mp, sp)
            elif action_type == "build_domain":
                game.build_domain(pid, move["domain_id"], gp, mp, sp)
            elif action_type == "slay_monster":
                game.slay_monster(
                    pid, move.get("monster_id"), sp, mp, gp, event_id=move.get("event_id")
                )
            else:
                game.take_resource(pid, move["resource"])
        except Exception:
            # The server consumes before applying too; on a rejected move we
            # hand the action back so simulation can try a different one.
            game.actions_remaining += 1
            raise
        game.finish_turn_if_no_actions_remaining()
    else:
        raise ValueError(f"Unsupported action_type {action_type!r}")

    advance(game)
