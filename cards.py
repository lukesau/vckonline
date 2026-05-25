def _coerce_int(val, default=0):
    if val is None:
        return default
    if isinstance(val, bool):
        return int(val)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


class Card:
    def __init__(self):
        self.name = ""
        self.is_visible = False
        self.is_accessible = False

    def to_dict(self):
        return {
            "name": self.name,
            "is_visible": self.is_visible,
            "is_accessible": self.is_accessible,
        }

    def toggle_visibility(self, toggle: bool = True):
        self.is_visible = toggle

    def toggle_accessibility(self, toggle: bool = True):
        self.is_accessible = toggle


class Starter(Card):
    def __init__(self, starter_id, name, roll_match1, roll_match2, gold_payout_on_turn, gold_payout_off_turn,
                 strength_payout_on_turn, strength_payout_off_turn, magic_payout_on_turn, magic_payout_off_turn,
                 has_special_payout_on_turn, has_special_payout_off_turn, special_payout_on_turn,
                 special_payout_off_turn, expansion, activation_trigger=""):
        super().__init__()
        self.starter_id = starter_id
        self.name = name
        self.roll_match1 = roll_match1
        self.roll_match2 = roll_match2
        self.gold_payout_on_turn = gold_payout_on_turn
        self.gold_payout_off_turn = gold_payout_off_turn
        self.strength_payout_on_turn = strength_payout_on_turn
        self.strength_payout_off_turn = strength_payout_off_turn
        self.magic_payout_on_turn = magic_payout_on_turn
        self.magic_payout_off_turn = magic_payout_off_turn
        self.has_special_payout_on_turn = has_special_payout_on_turn
        self.has_special_payout_off_turn = has_special_payout_off_turn
        self.special_payout_on_turn = special_payout_on_turn
        self.special_payout_off_turn = special_payout_off_turn
        self.expansion = expansion
        # Non-dice activation gate. Empty string -> use roll_match. Substrings
        # "doubles" and "no_payout" are recognized by the harvest engine.
        self.activation_trigger = activation_trigger or ""

    def to_dict(self):
        return {
            "starter_id": self.starter_id,
            "name": self.name,
            "roll_match1": self.roll_match1,
            "roll_match2": self.roll_match2,
            "gold_payout_on_turn": self.gold_payout_on_turn,
            "gold_payout_off_turn": self.gold_payout_off_turn,
            "strength_payout_on_turn": self.strength_payout_on_turn,
            "strength_payout_off_turn": self.strength_payout_off_turn,
            "magic_payout_on_turn": self.magic_payout_on_turn,
            "magic_payout_off_turn": self.magic_payout_off_turn,
            "has_special_payout_on_turn": self.has_special_payout_on_turn,
            "has_special_payout_off_turn": self.has_special_payout_off_turn,
            "special_payout_on_turn": self.special_payout_on_turn,
            "special_payout_off_turn": self.special_payout_off_turn,
            "expansion": self.expansion,
            "activation_trigger": self.activation_trigger,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(data["starter_id"], data["name"], data["roll_match1"], data["roll_match2"],
                   data["gold_payout_on_turn"], data["gold_payout_off_turn"], data["strength_payout_on_turn"],
                   data["strength_payout_off_turn"], data["magic_payout_on_turn"], data["magic_payout_off_turn"],
                   data["has_special_payout_on_turn"], data["has_special_payout_off_turn"],
                   data["special_payout_on_turn"],
                   data["special_payout_off_turn"], data["expansion"],
                   data.get("activation_trigger", ""))


class Citizen(Card):
    def __init__(self, citizen_id, name, gold_cost, roll_match1, roll_match2, shadow_count, holy_count, soldier_count,
                 worker_count, gold_payout_on_turn, gold_payout_off_turn, strength_payout_on_turn,
                 strength_payout_off_turn, magic_payout_on_turn, magic_payout_off_turn, has_special_payout_on_turn,
                 has_special_payout_off_turn, special_payout_on_turn, special_payout_off_turn, special_citizen,
                 expansion, is_flipped=False):
        super().__init__()
        self.citizen_id = citizen_id
        self.name = name
        self.gold_cost = gold_cost
        self.roll_match1 = roll_match1
        self.roll_match2 = roll_match2
        self.shadow_count = _coerce_int(shadow_count)
        self.holy_count = _coerce_int(holy_count)
        self.soldier_count = _coerce_int(soldier_count)
        self.worker_count = _coerce_int(worker_count)
        self.gold_payout_on_turn = gold_payout_on_turn
        self.gold_payout_off_turn = gold_payout_off_turn
        self.strength_payout_on_turn = strength_payout_on_turn
        self.strength_payout_off_turn = strength_payout_off_turn
        self.magic_payout_on_turn = magic_payout_on_turn
        self.magic_payout_off_turn = magic_payout_off_turn
        self.has_special_payout_on_turn = has_special_payout_on_turn
        self.has_special_payout_off_turn = has_special_payout_off_turn
        self.special_payout_on_turn = special_payout_on_turn
        self.special_payout_off_turn = special_payout_off_turn
        self.special_citizen = special_citizen
        self.expansion = expansion
        self.is_flipped = bool(is_flipped)

    def get_special_payout_on_turn(self):
        return self.special_payout_on_turn

    def to_dict(self):
        base_dict = super().to_dict()
        return {**base_dict,
                "is_flipped": bool(getattr(self, "is_flipped", False)),
                "citizen_id": self.citizen_id,
                "gold_cost": self.gold_cost,
                "roll_match1": self.roll_match1,
                "roll_match2": self.roll_match2,
                "shadow_count": self.shadow_count,
                "holy_count": self.holy_count,
                "soldier_count": self.soldier_count,
                "worker_count": self.worker_count,
                "roles": {
                    "shadow": self.shadow_count,
                    "holy": self.holy_count,
                    "soldier": self.soldier_count,
                    "worker": self.worker_count,
                },
                "gold_payout_on_turn": self.gold_payout_on_turn,
                "gold_payout_off_turn": self.gold_payout_off_turn,
                "strength_payout_on_turn": self.strength_payout_on_turn,
                "strength_payout_off_turn": self.strength_payout_off_turn,
                "magic_payout_on_turn": self.magic_payout_on_turn,
                "magic_payout_off_turn": self.magic_payout_off_turn,
                "has_special_payout_on_turn": self.has_special_payout_on_turn,
                "has_special_payout_off_turn": self.has_special_payout_off_turn,
                "special_payout_on_turn": self.special_payout_on_turn,
                "special_payout_off_turn": self.special_payout_off_turn,
                "special_citizen": self.special_citizen,
                "expansion": self.expansion}

    @classmethod
    def from_dict(cls, dict_):
        return cls(citizen_id=dict_["citizen_id"],
                   name=dict_["name"],
                   gold_cost=dict_["gold_cost"],
                   roll_match1=dict_["roll_match1"],
                   roll_match2=dict_["roll_match2"],
                   shadow_count=dict_.get("shadow_count"),
                   holy_count=dict_.get("holy_count"),
                   soldier_count=dict_.get("soldier_count"),
                   worker_count=dict_.get("worker_count"),
                   gold_payout_on_turn=dict_["gold_payout_on_turn"],
                   gold_payout_off_turn=dict_["gold_payout_off_turn"],
                   strength_payout_on_turn=dict_["strength_payout_on_turn"],
                   strength_payout_off_turn=dict_["strength_payout_off_turn"],
                   magic_payout_on_turn=dict_["magic_payout_on_turn"],
                   magic_payout_off_turn=dict_["magic_payout_off_turn"],
                   has_special_payout_on_turn=dict_["has_special_payout_on_turn"],
                   has_special_payout_off_turn=dict_["has_special_payout_off_turn"],
                   special_payout_on_turn=dict_["special_payout_on_turn"],
                   special_payout_off_turn=dict_["special_payout_off_turn"],
                   special_citizen=dict_["special_citizen"],
                   expansion=dict_["expansion"],
                   is_flipped=bool(dict_.get("is_flipped", False)))


class Domain(Card):
    def __init__(self, domain_id, name, gold_cost, shadow_count, holy_count, soldier_count, worker_count, vp_reward,
                 has_activation_effect, has_passive_effect, passive_effect, activation_effect, text, expansion,
                 acquired_turn_number=None):
        super().__init__()
        self.domain_id = domain_id
        self.name = name
        self.gold_cost = gold_cost
        self.shadow_count = _coerce_int(shadow_count)
        self.holy_count = _coerce_int(holy_count)
        self.soldier_count = _coerce_int(soldier_count)
        self.worker_count = _coerce_int(worker_count)
        self.vp_reward = vp_reward
        self.has_activation_effect = has_activation_effect
        self.has_passive_effect = has_passive_effect
        self.passive_effect = passive_effect
        self.activation_effect = activation_effect
        self.text = text
        self.expansion = expansion
        self.acquired_turn_number = acquired_turn_number

    def to_dict(self):
        return {
            **super().to_dict(),
            "domain_id": self.domain_id,
            "name": self.name,
            "gold_cost": self.gold_cost,
            "shadow_count": self.shadow_count,
            "holy_count": self.holy_count,
            "soldier_count": self.soldier_count,
            "worker_count": self.worker_count,
            "roles": {
                "shadow": self.shadow_count,
                "holy": self.holy_count,
                "soldier": self.soldier_count,
                "worker": self.worker_count,
            },
            "vp_reward": self.vp_reward,
            "has_activation_effect": self.has_activation_effect,
            "has_passive_effect": self.has_passive_effect,
            "passive_effect": self.passive_effect,
            "activation_effect": self.activation_effect,
            "text": self.text,
            "expansion": self.expansion,
            "acquired_turn_number": getattr(self, "acquired_turn_number", None),
        }

    @classmethod
    def from_dict(cls, dict_):
        return cls(
            domain_id=dict_['domain_id'],
            name=dict_['name'],
            gold_cost=dict_['gold_cost'],
            shadow_count=dict_.get('shadow_count'),
            holy_count=dict_.get('holy_count'),
            soldier_count=dict_.get('soldier_count'),
            worker_count=dict_.get('worker_count'),
            vp_reward=dict_['vp_reward'],
            has_activation_effect=dict_['has_activation_effect'],
            has_passive_effect=dict_['has_passive_effect'],
            passive_effect=dict_['passive_effect'],
            activation_effect=dict_['activation_effect'],
            text=dict_['text'],
            expansion=dict_['expansion'],
            acquired_turn_number=dict_.get('acquired_turn_number'),
        )


class Monster(Card):
    def __init__(self, monster_id, name, area, monster_type, order, strength_cost, magic_cost, vp_reward, gold_reward,
                 strength_reward, magic_reward, has_special_reward, special_reward, has_special_cost, special_cost,
                 is_extra, expansion):
        super().__init__()
        self.monster_id = monster_id
        self.name = name
        self.area = area
        self.monster_type = monster_type
        self.order = order
        self.strength_cost = strength_cost
        self.magic_cost = magic_cost
        self.vp_reward = vp_reward
        self.gold_reward = gold_reward
        self.strength_reward = strength_reward
        self.magic_reward = magic_reward
        self.has_special_reward = has_special_reward
        self.special_reward = special_reward
        self.has_special_cost = has_special_cost
        self.special_cost = special_cost
        self.is_extra = is_extra
        self.expansion = expansion

    def to_dict(self):
        card_dict = super().to_dict()
        monster_dict = {
            "monster_id": self.monster_id,
            "area": self.area,
            "monster_type": self.monster_type,
            "order": self.order,
            "strength_cost": self.strength_cost,
            "magic_cost": self.magic_cost,
            "vp_reward": self.vp_reward,
            "gold_reward": self.gold_reward,
            "strength_reward": self.strength_reward,
            "magic_reward": self.magic_reward,
            "has_special_reward": self.has_special_reward,
            "special_reward": self.special_reward,
            "has_special_cost": self.has_special_cost,
            "special_cost": self.special_cost,
            "is_extra": self.is_extra,
            "expansion": self.expansion,
        }
        return {**card_dict, **monster_dict}

    @classmethod
    def from_dict(cls, d):
        return cls(
            d['monster_id'],
            d['name'],
            d['area'],
            d['monster_type'],
            d['order'],
            d['strength_cost'],
            d['magic_cost'],
            d['vp_reward'],
            d['gold_reward'],
            d['strength_reward'],
            d['magic_reward'],
            d['has_special_reward'],
            d['special_reward'],
            d['has_special_cost'],
            d['special_cost'],
            d['is_extra'],
            d['expansion'],
        )

    def add_strength_cost(self, added_strength):
        self.strength_cost = self.strength_cost + added_strength

    def add_magic_cost(self, added_magic):
        self.magic_cost = self.magic_cost + added_magic


class Duke(Card):
    def __init__(self, duke_id, name, gold_mult, strength_mult, magic_mult, shadow_mult, holy_mult, soldier_mult,
                 worker_mult, monster_mult, citizen_mult, domain_mult, boss_mult, minion_mult, beast_mult, titan_mult,
                 expansion):
        super().__init__()
        self.duke_id = duke_id
        self.name = name
        self.gold_multiplier = gold_mult
        self.strength_multiplier = strength_mult
        self.magic_multiplier = magic_mult
        self.shadow_multiplier = shadow_mult
        self.holy_multiplier = holy_mult
        self.soldier_multiplier = soldier_mult
        self.worker_multiplier = worker_mult
        self.monster_multiplier = monster_mult
        self.citizen_multiplier = citizen_mult
        self.domain_multiplier = domain_mult
        self.boss_multiplier = boss_mult
        self.minion_multiplier = minion_mult
        self.beast_multiplier = beast_mult
        self.titan_multiplier = titan_mult
        self.expansion = expansion
        self.toggle_visibility(True)

    def to_dict(self):
        return {
            **super().to_dict(),
            "duke_id": self.duke_id,
            "gold_multiplier": self.gold_multiplier,
            "strength_multiplier": self.strength_multiplier,
            "magic_multiplier": self.magic_multiplier,
            "shadow_multiplier": self.shadow_multiplier,
            "holy_multiplier": self.holy_multiplier,
            "soldier_multiplier": self.soldier_multiplier,
            "worker_multiplier": self.worker_multiplier,
            "monster_multiplier": self.monster_multiplier,
            "citizen_multiplier": self.citizen_multiplier,
            "domain_multiplier": self.domain_multiplier,
            "boss_multiplier": self.boss_multiplier,
            "minion_multiplier": self.minion_multiplier,
            "beast_multiplier": self.beast_multiplier,
            "titan_multiplier": self.titan_multiplier,
            "expansion": self.expansion
        }

    @classmethod
    def from_dict(cls, data):
        duke_id = data["duke_id"]
        name = data["name"]
        gold_mult = data["gold_multiplier"]
        strength_mult = data["strength_multiplier"]
        magic_mult = data["magic_multiplier"]
        shadow_mult = data["shadow_multiplier"]
        holy_mult = data["holy_multiplier"]
        soldier_mult = data["soldier_multiplier"]
        worker_mult = data["worker_multiplier"]
        monster_mult = data["monster_multiplier"]
        citizen_mult = data["citizen_multiplier"]
        domain_mult = data["domain_multiplier"]
        boss_mult = data["boss_multiplier"]
        minion_mult = data["minion_multiplier"]
        beast_mult = data["beast_multiplier"]
        titan_mult = data["titan_multiplier"]
        expansion = data["expansion"]
        return cls(duke_id, name, gold_mult, strength_mult, magic_mult, shadow_mult, holy_mult, soldier_mult,
                   worker_mult, monster_mult, citizen_mult, domain_mult, boss_mult, minion_mult, beast_mult,
                   titan_mult, expansion)


class Exhausted(Card):
    def __init__(self, exhausted_id):
        super().__init__()
        self.exhausted_id = exhausted_id
        self.name = "Exhausted"
        self.toggle_visibility(True)

    def to_dict(self):
        return {
            **super().to_dict(),
            "exhausted_id": self.exhausted_id,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, d):
        return cls(d["exhausted_id"])
