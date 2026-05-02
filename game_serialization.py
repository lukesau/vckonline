from json import JSONEncoder

from cards import Citizen, Domain, Duke, Monster, Starter
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
                "effects": obj.effects,
                "harvest_delta": getattr(obj, "harvest_delta", {"gold": 0, "strength": 0, "magic": 0, "victory": 0}),
            }
        if isinstance(obj, Duke):
            return obj.to_dict()
        if isinstance(obj, Monster):
            return obj.to_dict()
        if isinstance(obj, Starter):
            return obj.to_dict()
        if isinstance(obj, Citizen):
            return obj.to_dict()
        if isinstance(obj, Domain):
            return obj.to_dict()
        if hasattr(obj, "game_id") and hasattr(obj, "player_list") and hasattr(obj, "monster_grid"):
            ca_raw = getattr(obj, "concurrent_action", None)
            ca_enc = ca_raw
            if isinstance(ca_raw, dict) and not (ca_raw.get("pending") or []):
                ca_enc = None
            return {
                "game_id": obj.game_id,
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
                "exhausted_count": obj.exhausted_count,
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
                "harvest_player_order": getattr(obj, "harvest_player_order", None),
                "harvest_player_idx": getattr(obj, "harvest_player_idx", 0),
                "harvest_consumed": getattr(obj, "harvest_consumed", {}) or {},
                "harvest_prompt_slots": obj.harvest_slots_for_api() if hasattr(obj, "harvest_slots_for_api") else [],
                "game_log": list(getattr(obj, "game_log", None) or []),
            }
        return super().default(obj)
