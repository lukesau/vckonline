from cards import Citizen, Domain, Duke, Event, Monster, Noble, Relic, Starter, Tome

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
        # Optional Relics module: a player is dealt several relics at setup and
        # keeps exactly one for the rest of the game (the rest are discarded).
        self.owned_relics = []
        self.owned_monsters = []
        # Crimson Seas tableau pieces. Goods are plain type strings (see
        # game_setup.GOODS_TYPES); Tomes are flippable Tome card objects (a
        # face-down tome is a spent-this-turn resource); Nobles are Noble cards.
        self.owned_goods = []
        self.owned_tomes = []
        self.owned_nobles = []
        self.gold_score = 2
        self.strength_score = 0
        self.magic_score = 1
        self.victory_score = 0
        # Crimson Seas expansion: "maps" are a new resource used to sail. No way
        # to spend them exists yet; for now they are only earned and displayed.
        self.map_score = 0
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
        # Named effect flags granted by "rest of the game" event passives
        # (e.g. Blessed Lands, Dark Lord Rising). Distinct from `effects` and
        # from domain-derived flags: these persist for the rest of the game
        # regardless of the granting card's board position.
        self.granted_effects = []
        self.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0, "map": 0}

    @classmethod
    def from_dict(cls, data):
        player_id = data["player_id"]
        name = data["name"]
        player = cls(player_id, name)
        player.owned_starters = [Starter.from_dict(s) for s in data["owned_starters"]]
        for starter in player.owned_starters:
            starter.toggle_visibility(True)
        player.owned_citizens = [Citizen.from_dict(c) for c in data["owned_citizens"]]
        player.owned_domains = [Domain.from_dict(d) for d in data["owned_domains"]]
        player.owned_dukes = [Duke.from_dict(d) for d in data["owned_dukes"]]
        player.owned_relics = [Relic.from_dict(r) for r in (data.get("owned_relics") or [])]
        player.owned_monsters = [
            Event.from_dict(m) if m.get("card_class") == "event" else Monster.from_dict(m)
            for m in data["owned_monsters"]
        ]
        player.owned_goods = list(data.get("owned_goods") or [])
        player.owned_tomes = [
            t if isinstance(t, Tome) else Tome.from_dict(t) if isinstance(t, dict) else Tome(t)
            for t in (data.get("owned_tomes") or [])
        ]
        player.owned_nobles = [Noble.from_dict(n) for n in (data.get("owned_nobles") or [])]
        player.gold_score = data["gold_score"]
        player.strength_score = data["strength_score"]
        player.magic_score = data["magic_score"]
        player.victory_score = data["victory_score"]
        player.map_score = data.get("map_score", 0)
        player.is_first = data["is_first"]
        player.effects = data["effects"]
        player.granted_effects = list(data.get("granted_effects") or [])
        player.harvest_delta = data.get(
            "harvest_delta", {"gold": 0, "strength": 0, "magic": 0, "victory": 0, "map": 0}
        )
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
        # Crimson Seas: rescued Nobles also carry Citizen Role icons. The
        # rulebook's scoring note is explicit that role-icon tallies "include
        # the Citizen Role icons found on your Citizens, Domains, and Nobles",
        # so Nobles feed the same role pool that Dukes and Nobles score against.
        # `owned_nobles` is empty in every non-Crimson-Seas game, so this is a
        # no-op elsewhere.
        for noble in getattr(self, "owned_nobles", []) or []:
            shadow_count = shadow_count + noble.shadow_count
            holy_count = holy_count + noble.holy_count
            soldier_count = soldier_count + noble.soldier_count
            worker_count = worker_count + noble.worker_count
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
    def __init__(self, player_name, player_id, lobby_id=None, is_bot=False):
        self.name = player_name
        self.player_id = player_id
        self.lobby_id = lobby_id
        self.is_ready = bool(is_bot)  # bots are always ready
        self.debug_mode = False
        self.is_bot = bool(is_bot)
        self.last_active_time = 0


class Lobby:
    """A gathering of LobbyMembers waiting to start a game.

    Lobbies are nameless — they are identified internally by `lobby_id`
    and surfaced to clients by their metadata (preset, member count,
    member names, min-players floor). `preset` is the `load_game_data`
    preset that will be used when the lobby starts a game. The owner
    (initially the creator) is the only member allowed to change the
    preset; if the owner leaves while other members remain, ownership
    transfers to the next member.
    """

    def __init__(
        self,
        lobby_id,
        owner_id,
        preset="current",
        min_players=2,
        expansion_only=False,
        duke_select_count=2,
        random_no_optional_modules=False,
    ):
        self.lobby_id = lobby_id
        self.owner_id = owner_id
        self.preset = preset
        # Owner-controlled floor on lobby size before the game can auto-start.
        # Defaults to 2 (the historical behavior). Engine cap is 5 (5-player
        # decks add is_extra monsters and a 6th citizen copy).
        self.min_players = int(min_players or 2)
        # When True (base/flamesandfrost/shadowvale only), domains and dukes
        # are drawn from the preset expansion set; expansion presets also mix
        # in base dukes because the expansion alone has too few.
        self.expansion_only = bool(expansion_only)
        # Random preset only: when True, Agents and Relics are omitted instead
        # of the default 50/50 roll at game start.
        self.random_no_optional_modules = bool(random_no_optional_modules)
        # How many dukes each player is dealt before the choose-one prompt.
        self.duke_select_count = int(duke_select_count or 2)
        self.members = []
        self.created_at = 0


class GameMember:
    def __init__(self, player_id, player_name, game_id):
        self.name = player_name
        self.player_id = player_id
        self.game_id = game_id
