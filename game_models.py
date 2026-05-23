from cards import Citizen, Domain, Duke, Monster, Starter

_MONSTER_TYPE_COUNT_KEYS = {
    "Minion": "minion_count",
    "Titan": "titan_count",
    "Warden": "warden_count",
    "Boss": "boss_count",
    "Beast": "beast_count",
}


class Player:
    def __init__(self, player_id, name):
        self.player_id = player_id
        self.name = name
        self.owned_starters = []
        self.owned_citizens = []
        self.owned_domains = []
        self.owned_dukes = []
        self.owned_monsters = []
        self.gold_score = 2
        self.strength_score = 0
        self.magic_score = 1
        self.victory_score = 0
        self.is_first = False
        self.shadow_count = 0
        self.holy_count = 0
        self.soldier_count = 0
        self.worker_count = 0
        self.minion_count = 0
        self.titan_count = 0
        self.warden_count = 0
        self.boss_count = 0
        self.beast_count = 0
        self.effects = {
            "roll_phase": [],
            "harvest_phase": [],
            "action_phase": [],
        }
        self.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
        self.free_slay_actions = 0
        self.free_hire_actions = 0
        self.free_build_actions = 0

    @classmethod
    def from_dict(cls, data):
        player_id = data["player_id"]
        name = data["name"]
        player = cls(player_id, name)
        player.owned_starters = [Starter.from_dict(s) for s in data["owned_starters"]]
        player.owned_citizens = [Citizen.from_dict(c) for c in data["owned_citizens"]]
        player.owned_domains = [Domain.from_dict(d) for d in data["owned_domains"]]
        player.owned_dukes = [Duke.from_dict(d) for d in data["owned_dukes"]]
        player.owned_monsters = [Monster.from_dict(m) for m in data["owned_monsters"]]
        player.gold_score = data["gold_score"]
        player.strength_score = data["strength_score"]
        player.magic_score = data["magic_score"]
        player.victory_score = data["victory_score"]
        player.is_first = data["is_first"]
        player.effects = data["effects"]
        player.harvest_delta = data.get("harvest_delta", {"gold": 0, "strength": 0, "magic": 0, "victory": 0})
        player.free_slay_actions = int(data.get("free_slay_actions", 0) or 0)
        player.free_hire_actions = int(data.get("free_hire_actions", 0) or 0)
        player.free_build_actions = int(data.get("free_build_actions", 0) or 0)
        roles = player.calc_roles()
        player.shadow_count = roles["shadow_count"]
        player.holy_count = roles["holy_count"]
        player.soldier_count = roles["soldier_count"]
        player.worker_count = roles["worker_count"]
        player.minion_count = roles["minion_count"]
        player.titan_count = roles["titan_count"]
        player.warden_count = roles["warden_count"]
        player.boss_count = roles["boss_count"]
        player.beast_count = roles["beast_count"]
        return player

    def calc_roles(self):
        shadow_count = 0
        holy_count = 0
        soldier_count = 0
        worker_count = 0
        for citizen in self.owned_citizens:
            shadow_count = shadow_count + citizen.shadow_count
            holy_count = holy_count + citizen.holy_count
            soldier_count = soldier_count + citizen.soldier_count
            worker_count = worker_count + citizen.worker_count
        for domain in self.owned_domains:
            shadow_count = shadow_count + domain.shadow_count
            holy_count = holy_count + domain.holy_count
            soldier_count = soldier_count + domain.soldier_count
            worker_count = worker_count + domain.worker_count
        monster_counts = {key: 0 for key in _MONSTER_TYPE_COUNT_KEYS.values()}
        for monster in self.owned_monsters:
            count_key = _MONSTER_TYPE_COUNT_KEYS.get(monster.monster_type)
            if count_key:
                monster_counts[count_key] += 1
        roles_dict = {
            "shadow_count": shadow_count,
            "holy_count": holy_count,
            "soldier_count": soldier_count,
            "worker_count": worker_count,
            **monster_counts,
            "owned_domains": len(self.owned_domains),
            "owned_citizens": len(self.owned_citizens),
            "owned_monsters": len(self.owned_monsters),
        }
        return roles_dict


class LobbyMember:
    def __init__(self, player_name, player_id):
        self.name = player_name
        self.player_id = player_id
        self.is_ready = False
        self.debug_starting_resources = False
        self.last_active_time = 0


class GameMember:
    def __init__(self, player_id, player_name, game_id):
        self.name = player_name
        self.player_id = player_id
        self.game_id = game_id
