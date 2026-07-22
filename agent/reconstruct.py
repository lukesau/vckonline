"""Rebuild a playable Game object from a server wire-state snapshot.

A remote bot only receives GameObjectEncoder wire dicts (further redacted per
viewer by server._serialize_game_for_player), but our policies need a real Game
to clone and search. The wire dict is already ~90% of the save format that
game_serialization.deserialize_save_dict_to_game accepts; this module fills the
gaps, sampling what is genuinely hidden:

  - opponent dukes arrive as stubs (duke_id 0) -> sampled from the public
    all_dukes catalog minus the viewer's own (MCTS re-samples per iteration
    anyway via its determinization)
  - the exhausted/event deck arrives as a size -> filled with plain Exhausted
    tokens (upcoming-event modeling in simulations is a known simplification)
  - monster_stack_areas (engine-only) -> derived from the monster cards
    themselves, plus the Undead Samurai virtual area when its pool is armed
  - engine-only pending-harvest machinery is absent -> engine defaults apply,
    which is safe at the decision points a remote bot acts on

No engine files are modified; everything routes through the engine's own
rehydration helpers.
"""

import json
import random


def _viewer_duke_ids(state, viewer_player_id):
    for p in state.get("player_list") or []:
        if p.get("player_id") == viewer_player_id:
            return {
                d.get("duke_id") for d in (p.get("owned_dukes") or []) if d.get("duke_id")
            }
    return set()


def _fill_opponent_dukes(state, viewer_player_id):
    catalog = [d for d in (state.get("all_dukes") or []) if d.get("duke_id")]
    known = _viewer_duke_ids(state, viewer_player_id)
    pool = [d for d in catalog if d.get("duke_id") not in known]
    random.shuffle(pool)
    for p in state.get("player_list") or []:
        if p.get("player_id") == viewer_player_id:
            continue
        dukes = p.get("owned_dukes") or []
        needs = [d for d in dukes if not d.get("duke_id")]
        if not needs:
            continue
        replacement = []
        for _ in dukes:
            if pool:
                replacement.append(dict(pool.pop()))
        p["owned_dukes"] = replacement


def _derive_monster_stack_areas(state):
    areas = []
    for i, stack in enumerate(state.get("monster_grid") or []):
        area = None
        for card in stack or []:
            if isinstance(card, dict) and card.get("area"):
                area = card["area"]
                break
        areas.append(area or f"__unknown_area_{i}")
    if state.get("undead_samurai_pool") and "Undead Samurai" not in areas:
        areas.append("Undead Samurai")
    return areas


def _fill_exhausted_stack(state):
    size = int(state.get("exhausted_stack_size") or 0)
    return [
        {"name": "Exhausted", "exhausted_id": i, "is_visible": False, "is_accessible": False}
        for i in range(size)
    ]


def game_from_wire(wire_state, viewer_player_id):
    """Wire snapshot (as received by this viewer) -> fresh Game object."""
    from game_serialization import deserialize_save_dict_to_game

    state = json.loads(json.dumps(wire_state))  # deep copy, ensure plain JSON types
    _fill_opponent_dukes(state, viewer_player_id)
    state["save_format_version"] = 1
    state["monster_stack_areas"] = _derive_monster_stack_areas(state)
    state["exhausted_stack"] = _fill_exhausted_stack(state)
    state["include_agents"] = bool(state.get("agents_enabled"))
    state["include_relics"] = bool(state.get("relics_enabled"))
    state["_pending_reroll_twilight_used"] = bool(state.get("pending_reroll_twilight_used"))
    state["_pending_reroll_blood_moon_used"] = bool(state.get("pending_reroll_blood_moon_used"))
    for key in ("goods_supply", "tome_supply", "noble_supply", "agents_deck"):
        state.setdefault(key, [])
    # Server-only decorations that the engine must not choke on
    for key in ("hurry_up_seconds_remaining", "hurry_up_total_seconds", "my_rejoin_code"):
        state.pop(key, None)
    for p in state.get("player_list") or []:
        p.pop("duke_vp_table", None)
        p.pop("duke_vp_projection", None)
    return deserialize_save_dict_to_game(state)


def simulate_server_wire(game, viewer_player_id):
    """Local stand-in for GET /state: encode `game` and apply the same viewer
    redactions server._serialize_game_for_player performs (duke stubs, hidden
    deck as size only). Used to test reconstruction without a server."""
    from game import GameObjectEncoder

    state = json.loads(json.dumps(game, cls=GameObjectEncoder))
    for p in state.get("player_list") or []:
        if p.get("player_id") != viewer_player_id:
            p["owned_dukes"] = [
                {"duke_id": 0, "name": "", "is_visible": False, "is_accessible": False}
                for _ in (p.get("owned_dukes") or [])
            ]
    return state
