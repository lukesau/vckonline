import json
from json import JSONEncoder

from cards import Citizen, Domain, Duke, Event, Exhausted, Monster, Starter
from game_models import GameMember, LobbyMember, Player


class SummaryEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Player):
            return {
                "player_id": obj.player_id,
                "name": obj.name,
                "owned_citizens": len(obj.owned_citizens),
                "owned_domains": len(obj.owned_domains),
                "owned_monsters": len(obj.owned_monsters),
                "gold_score": obj.gold_score,
                "strength_score": obj.strength_score,
                "magic_score": obj.magic_score,
                "victory_score": obj.victory_score,
                "is_first": obj.is_first,
            }
        if isinstance(obj, LobbyMember):
            return {
                "player_name": obj.name,
                "player_id": obj.player_id,
                "is_ready": obj.is_ready,
            }
        if isinstance(obj, GameMember):
            return {
                "player_name": obj.name,
                "player_id": obj.player_id,
            }
        if hasattr(obj, "game_id") and hasattr(obj, "player_list"):
            return {
                "game_id": obj.game_id,
                "player_list": obj.player_list,
            }
        return super().default(obj)


class GameObjectEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Player):
            roles = obj.calc_roles()
            return {
                "player_id": obj.player_id,
                "name": obj.name,
                "owned_starters": [starter.to_dict() for starter in obj.owned_starters],
                "owned_citizens": [citizen.to_dict() for citizen in obj.owned_citizens],
                "owned_domains": [domain.to_dict() for domain in obj.owned_domains],
                "owned_dukes": [duke.to_dict() for duke in obj.owned_dukes],
                "owned_monsters": [monster.to_dict() for monster in obj.owned_monsters],
                "gold_score": obj.gold_score,
                "strength_score": obj.strength_score,
                "magic_score": obj.magic_score,
                "victory_score": obj.victory_score,
                "is_first": obj.is_first,
                "shadow_count": roles["shadow_count"],
                "holy_count": roles["holy_count"],
                "soldier_count": roles["soldier_count"],
                "worker_count": roles["worker_count"],
                "minion_count": roles["minion_count"],
                "titan_count": roles["titan_count"],
                "warden_count": roles["warden_count"],
                "boss_count": roles["boss_count"],
                "beast_count": roles["beast_count"],
                "effects": obj.effects,
                "granted_effects": list(getattr(obj, "granted_effects", None) or []),
                "harvest_delta": getattr(obj, "harvest_delta", {"gold": 0, "strength": 0, "magic": 0, "victory": 0}),
            }
        if isinstance(obj, Duke):
            return obj.to_dict()
        if isinstance(obj, Event):
            return obj.to_dict()
        if isinstance(obj, Monster):
            return obj.to_dict()
        if isinstance(obj, Starter):
            return obj.to_dict()
        if isinstance(obj, Citizen):
            return obj.to_dict()
        if isinstance(obj, Domain):
            return obj.to_dict()
        if isinstance(obj, Exhausted):
            return obj.to_dict()
        if hasattr(obj, "game_id") and hasattr(obj, "player_list") and hasattr(obj, "monster_grid"):
            ca_raw = getattr(obj, "concurrent_action", None)
            ca_enc = ca_raw
            if isinstance(ca_raw, dict) and not (ca_raw.get("pending") or []):
                ca_enc = None
            shutdown = getattr(obj, "shutdown", None)
            return {
                "game_id": obj.game_id,
                "debug_mode": bool(getattr(obj, "debug_mode", False)),
                "player_list": obj.player_list,
                "monster_grid": obj.monster_grid,
                "citizen_grid": obj.citizen_grid,
                "domain_grid": obj.domain_grid,
                "die_one": obj.die_one,
                "die_two": obj.die_two,
                "die_sum": obj.die_sum,
                "rolled_die_one": getattr(obj, "rolled_die_one", obj.die_one),
                "rolled_die_two": getattr(obj, "rolled_die_two", obj.die_two),
                "rolled_die_sum": getattr(obj, "rolled_die_sum", obj.die_sum),
                "pending_roll": getattr(obj, "pending_roll", None),
                "roll_events": list(getattr(obj, "roll_events", None) or []),
                "exhausted_count": obj.exhausted_count,
                "exhausted_stack_size": len(getattr(obj, "exhausted_stack", None) or []),
                "banish_pile": list(getattr(obj, "banish_pile", None) or []),
                "banish_pile_size": len(getattr(obj, "banish_pile", None) or []),
                "end_game_triggered": getattr(obj, "end_game_triggered", False),
                "final_scores": getattr(obj, "final_scores", None),
                "final_result": getattr(obj, "final_result", None),
                "effects": obj.effects,
                "action_required": obj.action_required,
                "pending_required_choice": getattr(obj, "pending_required_choice", None),
                "pending_action_end_queue": getattr(obj, "pending_action_end_queue", None) or [],
                "concurrent_action": ca_enc,
                "tick_id": getattr(obj, "tick_id", 0),
                "turn_number": getattr(obj, "turn_number", 1),
                "turn_index": getattr(obj, "turn_index", 0),
                "phase": getattr(obj, "phase", "roll"),
                "actions_remaining": getattr(obj, "actions_remaining", 0),
                "active_player_id": obj.current_player_id() if hasattr(obj, "current_player_id") else None,
                "resting_player_id": obj.resting_player_id() if hasattr(obj, "resting_player_id") else None,
                "harvest_player_order": getattr(obj, "harvest_player_order", None),
                "harvest_player_idx": getattr(obj, "harvest_player_idx", 0),
                "harvest_consumed": getattr(obj, "harvest_consumed", {}) or {},
                "pending_harvest_slays": list(getattr(obj, "pending_harvest_slays", None) or []),
                "harvest_prompt_slots": obj.harvest_slots_for_api() if hasattr(obj, "harvest_slots_for_api") else [],
                "game_log": list(getattr(obj, "game_log", None) or []),
                "shutdown": shutdown,
                "pending_event_slay_cost": getattr(obj, "pending_event_slay_cost", None),
                "pending_event_activations": list(getattr(obj, "pending_event_activations", None) or []),
                "pending_event_sequence": getattr(obj, "pending_event_sequence", None),
                "undead_samurai_pool": list(getattr(obj, "undead_samurai_pool", None) or []),
                "undead_samurai_placed": bool(getattr(obj, "undead_samurai_placed", False)),
                "pending_reroll_twilight_used": bool(getattr(obj, "_pending_reroll_twilight_used", False)),
                "pending_reroll_blood_moon_used": bool(getattr(obj, "_pending_reroll_blood_moon_used", False)),
            }
        return super().default(obj)


# ─── Round-trippable save/load ──────────────────────────────────────────────
#
# `GameObjectEncoder` is intentionally slim — it's the wire format clients see.
# For save/load (and eventually DB persistence) we need every engine field a
# rehydrated `Game(...)` would touch. Strategy:
#
# 1. Run the live game through `GameObjectEncoder` + `json.loads` to get a
#    JSON-friendly dict with the bulk of the state already covered (cards
#    flattened via their `to_dict` methods).
# 2. Augment with the handful of fields the encoder omits (or aliases).
# 3. On load, walk the dict and rehydrate dict-blobs back into card objects
#    where the engine expects card objects (grids, banish_pile, exhausted_stack,
#    each player's owned_*).
#
# This lives alongside the encoder rather than in `game.py` so we don't wedge
# the engine module with persistence concerns.

# Card classes whose dicts must be re-objectified at load time. We dispatch
# by the unique `*_id` field each Card subclass exposes.
def _rehydrate_card_from_dict(d):
    if d is None:
        return None
    if not isinstance(d, dict):
        return d
    if d.get("card_class") == "event" or "event_id" in d:
        return Event.from_dict(d)
    if "starter_id" in d:
        return Starter.from_dict(d)
    if "citizen_id" in d:
        return Citizen.from_dict(d)
    if "domain_id" in d:
        return Domain.from_dict(d)
    if "duke_id" in d:
        return Duke.from_dict(d)
    if "monster_id" in d:
        return Monster.from_dict(d)
    if "exhausted_id" in d or d.get("name") == "Exhausted":
        return Exhausted.from_dict(d)
    raise ValueError(f"Cannot identify card type for dict with keys: {sorted(d.keys())}")


def _rehydrate_card_grid(grid):
    if not isinstance(grid, list):
        return grid
    return [
        [_rehydrate_card_from_dict(c) for c in (stack or [])]
        for stack in grid
    ]


def serialize_game_to_save_dict(game):
    """Produce a JSON-serializable dict that fully captures `game` for round-trip.

    Output is a superset of `GameObjectEncoder`'s wire dict — additional keys
    cover engine fields that the encoder omits (or only emits a summary for).
    Dukes are NOT redacted: a save must carry full state.
    """
    base = json.loads(json.dumps(game, cls=GameObjectEncoder))

    base["save_format_version"] = 1

    base["monster_stack_areas"] = list(getattr(game, "monster_stack_areas", []) or [])
    base["exhausted_stack"] = [c.to_dict() for c in (getattr(game, "exhausted_stack", []) or [])]
    base["pending_payout_continuation"] = getattr(game, "pending_payout_continuation", None)
    base["pending_harvest_choices"] = list(getattr(game, "pending_harvest_choices", []) or [])
    base["harvest_processed"] = bool(getattr(game, "harvest_processed", False))
    base["_harvest_steal_phase_done"] = bool(getattr(game, "_harvest_steal_phase_done", False))

    # The encoder names these without the leading underscore. `Game.__init__`
    # reads the underscored keys via `game_state.get('_pending_reroll_*_used')`.
    base["_pending_reroll_twilight_used"] = bool(getattr(game, "_pending_reroll_twilight_used", False))
    base["_pending_reroll_blood_moon_used"] = bool(getattr(game, "_pending_reroll_blood_moon_used", False))

    return base


def deserialize_save_dict_to_game(data):
    """Rehydrate a `serialize_game_to_save_dict(...)` blob into a fresh `Game`.

    Imported lazily to avoid a circular import (`game.py` imports this module).
    """
    from game import Game

    state = dict(data)

    rehydrated_players = []
    for player_dict in state.get("player_list", []) or []:
        if isinstance(player_dict, Player):
            rehydrated_players.append(player_dict)
        elif isinstance(player_dict, dict):
            rehydrated_players.append(Player.from_dict(player_dict))
        else:
            raise ValueError(f"Unsupported player entry in save: {type(player_dict)!r}")
    state["player_list"] = rehydrated_players

    state["monster_grid"] = _rehydrate_card_grid(state.get("monster_grid"))
    state["citizen_grid"] = _rehydrate_card_grid(state.get("citizen_grid"))
    state["domain_grid"] = _rehydrate_card_grid(state.get("domain_grid"))

    state["banish_pile"] = [
        _rehydrate_card_from_dict(c) for c in (state.get("banish_pile") or [])
    ]
    state["exhausted_stack"] = [
        _rehydrate_card_from_dict(c) for c in (state.get("exhausted_stack") or [])
    ]
    state["undead_samurai_pool"] = [
        _rehydrate_card_from_dict(c) for c in (state.get("undead_samurai_pool") or [])
    ]

    return Game(state)
