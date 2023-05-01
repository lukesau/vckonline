import json
from json import JSONEncoder, JSONDecoder
import mysql.connector
import random
from typing import List, Dict
from constants import *
import shortuuid
import uuid


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
        self.is_first = False
        self.shadow_count = 0
        self.holy_count = 0
        self.soldier_count = 0
        self.worker_count = 0

    @classmethod
    def from_dict(cls, data):
        player_id = data['player_id']
        name = data['name']
        player = cls(player_id, name)
        player.owned_starters = [Starter.from_dict(s) for s in data['owned_starters']]
        player.owned_citizens = [Citizen.from_dict(c) for c in data['owned_citizens']]
        player.owned_domains = [Domain.from_dict(d) for d in data['owned_domains']]
        player.owned_dukes = [Duke.from_dict(d) for d in data['owned_dukes']]
        player.owned_monsters = [Monster.from_dict(m) for m in data['owned_monsters']]
        player.gold_score = data['gold_score']
        player.strength_score = data['strength_score']
        player.magic_score = data['magic_score']
        player.is_first = data['is_first']
        player.shadow_count = data['shadow_count']
        player.holy_count = data['holy_count']
        player.soldier_count = data['soldier_count']
        player.worker_count = data['worker_count']
        return player

    def calc_roles(self):
        for citizen in self.owned_citizens:
            self.shadow_count = self.shadow_count + citizen.shadow_count
            self.holy_count = self.holy_count + citizen.holy_count
            self.soldier_count = self.soldier_count + citizen.soldier_count
            self.worker_count = self.worker_count + citizen.worker_count
        for domain in self.owned_domains:
            self.shadow_count = self.shadow_count + domain.shadow_count
            self.holy_count = self.holy_count + domain.holy_count
            self.soldier_count = self.soldier_count + domain.soldier_count
            self.worker_count = self.worker_count + domain.worker_count


class Starter(Card):
    def __init__(self, starter_id, name, roll_match1, roll_match2, gold_payout_on_turn, gold_payout_off_turn,
                 strength_payout_on_turn, strength_payout_off_turn, magic_payout_on_turn, magic_payout_off_turn,
                 has_special_payout_on_turn, has_special_payout_off_turn, special_payout_on_turn,
                 special_payout_off_turn, expansion):
        super().__init__()
        self.starter_id = starter_id
        self.name = name
        self.rollMatch1 = roll_match1
        self.rollMatch2 = roll_match2
        self.goldPayoutOnTurn = gold_payout_on_turn
        self.goldPayoutOffTurn = gold_payout_off_turn
        self.strengthPayoutOnTurn = strength_payout_on_turn
        self.strengthPayoutOffTurn = strength_payout_off_turn
        self.magicPayoutOnTurn = magic_payout_on_turn
        self.magicPayoutOffTurn = magic_payout_off_turn
        self.hasSpecialPayoutOnTurn = has_special_payout_on_turn
        self.hasSpecialPayoutOffTurn = has_special_payout_off_turn
        self.specialPayoutOnTurn = special_payout_on_turn
        self.specialPayoutOffTurn = special_payout_off_turn
        self.expansion = expansion

    def to_dict(self):
        return {
            "starter_id": self.starter_id,
            "name": self.name,
            "roll_match1": self.rollMatch1,
            "roll_match2": self.rollMatch2,
            "gold_payout_on_turn": self.goldPayoutOnTurn,
            "gold_payout_off_turn": self.goldPayoutOffTurn,
            "strength_payout_on_turn": self.strengthPayoutOnTurn,
            "strength_payout_off_turn": self.strengthPayoutOffTurn,
            "magic_payout_on_turn": self.magicPayoutOnTurn,
            "magic_payout_off_turn": self.magicPayoutOffTurn,
            "has_special_payout_on_turn": self.hasSpecialPayoutOnTurn,
            "has_special_payout_off_turn": self.hasSpecialPayoutOffTurn,
            "special_payout_on_turn": self.specialPayoutOnTurn,
            "special_payout_off_turn": self.specialPayoutOffTurn,
            "expansion": self.expansion
        }

    @classmethod
    def from_dict(cls, data):
        return cls(data["starter_id"], data["name"], data["roll_match1"], data["roll_match2"],
                   data["gold_payout_on_turn"], data["gold_payout_off_turn"], data["strength_payout_on_turn"],
                   data["strength_payout_off_turn"], data["magic_payout_on_turn"], data["magic_payout_off_turn"],
                   data["has_special_payout_on_turn"], data["has_special_payout_off_turn"],
                   data["special_payout_on_turn"],
                   data["special_payout_off_turn"], data["expansion"])


class Citizen(Card):
    def __init__(self, citizen_id, name, gold_cost, roll_match1, roll_match2, shadow_count, holy_count, soldier_count,
                 worker_count, gold_payout_on_turn, gold_payout_off_turn, strength_payout_on_turn,
                 strength_payout_off_turn, magic_payout_on_turn, magic_payout_off_turn, has_special_payout_on_turn,
                 has_special_payout_off_turn, special_payout_on_turn, special_payout_off_turn, special_citizen,
                 expansion):
        super().__init__()
        self.citizen_id = citizen_id
        self.name = name
        self.gold_cost = gold_cost
        self.roll_match1 = roll_match1
        self.roll_match2 = roll_match2
        self.shadow_count = shadow_count
        self.holy_count = holy_count
        self.soldier_count = soldier_count
        self.worker_count = worker_count
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

    def to_dict(self):
        base_dict = super().to_dict()
        return {**base_dict,
                "citizen_id": self.citizen_id,
                "gold_cost": self.gold_cost,
                "roll_match1": self.roll_match1,
                "roll_match2": self.roll_match2,
                "shadow_count": self.shadow_count,
                "holy_count": self.holy_count,
                "soldier_count": self.soldier_count,
                "worker_count": self.worker_count,
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
                   shadow_count=dict_["shadow_count"],
                   holy_count=dict_["holy_count"],
                   soldier_count=dict_["soldier_count"],
                   worker_count=dict_["worker_count"],
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
                   expansion=dict_["expansion"])


class Domain(Card):
    def __init__(self, domain_id, name, gold_cost, shadow_count, holy_count, soldier_count, worker_count, vp_reward,
                 has_activation_effect, has_passive_effect, passive_effect, activation_effect, text, expansion):
        super().__init__()
        self.domain_id = domain_id
        self.name = name
        self.gold_cost = gold_cost
        self.shadow_count = shadow_count
        self.holy_count = holy_count
        self.soldier_count = soldier_count
        self.worker_count = worker_count
        self.vp_reward = vp_reward
        self.has_activation_effect = has_activation_effect
        self.has_passive_effect = has_passive_effect
        self.passive_effect = passive_effect
        self.activation_effect = activation_effect
        self.text = text
        self.expansion = expansion

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
            "vp_reward": self.vp_reward,
            "has_activation_effect": self.has_activation_effect,
            "has_passive_effect": self.has_passive_effect,
            "passive_effect": self.passive_effect,
            "activation_effect": self.activation_effect,
            "text": self.text,
            "expansion": self.expansion
        }

    @classmethod
    def from_dict(cls, dict_):
        return cls(
            domain_id=dict_['domain_id'],
            name=dict_['name'],
            gold_cost=dict_['gold_cost'],
            shadow_count=dict_['shadow_count'],
            holy_count=dict_['holy_count'],
            soldier_count=dict_['soldier_count'],
            worker_count=dict_['worker_count'],
            vp_reward=dict_['vp_reward'],
            has_activation_effect=dict_['has_activation_effect'],
            has_passive_effect=dict_['has_passive_effect'],
            passive_effect=dict_['passive_effect'],
            activation_effect=dict_['activation_effect'],
            text=dict_['text'],
            expansion=dict_['expansion']
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


class Game:
    def __init__(self, game_state):
        self.game_id = game_state['game_id']
        self.player_list = game_state['player_list']
        self.monster_grid = game_state['monster_grid']
        self.citizen_grid = game_state['citizen_grid']
        self.domain_grid = game_state['domain_grid']
        self.die_one = game_state['die_one']
        self.die_two = game_state['die_two']
        self.die_sum = game_state['die_sum']
        self.exhausted_count = game_state['exhausted_count']

    def roll_phase(self):
        self.die_one = random.randint(1, 6)
        self.die_two = random.randint(1, 6)
        self.die_sum = self.die_one + self.die_two
        print(f"{self.die_one} | {self.die_two} | {self.die_sum}")
        for citizen in self.player_list[0].owned_citizens:
            if (citizen.roll_match1 == self.die_one) or (citizen.roll_match1 == self.die_two) or (
                    citizen.roll_match1 == self.die_sum) or (citizen.roll_match2 == self.die_sum):
                print(f"{citizen.name} Payout")
                self.player_list[0].gold_score = self.player_list[0].gold_score + citizen.gold_payout_on_turn
                self.player_list[0].strength_score = self.player_list[
                                                         0].strength_score + citizen.strength_payout_on_turn
                self.player_list[0].magic_score = self.player_list[0].magic_score + citizen.magic_payout_on_turn
        list_iterator = iter(self.player_list)
        next(list_iterator)
        for player in list_iterator:
            for citizen in player.owned_citizens:
                if (citizen.roll_match1 == self.die_one) or (citizen.roll_match1 == self.die_two) or (
                        citizen.roll_match1 == self.die_sum) or (citizen.roll_match2 == self.die_sum):
                    print(f"{citizen.name} Payout")
                    player.gold_score = player.gold_score + citizen.gold_payout_off_turn
                    player.strength_score = player.strength_score + citizen.strength_payout_off_turn
                    player.magic_score = player.magic_score + citizen.magic_payout_off_turn

    def play_turn(self):
        self.roll_phase()

    def end_check(self):
        if self.exhausted_count <= (len(self.player_list) * 2):
            return False


class GameObjectEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Player):
            return {
                'player_id': obj.player_id,
                'name': obj.name,
                'owned_starters': [starter.starter_id for starter in obj.owned_starters],
                'owned_citizens': [citizen.citizen_id for citizen in obj.owned_citizens],
                'owned_domains': [domain.domain_id for domain in obj.owned_domains],
                'owned_dukes': [duke.duke_id for duke in obj.owned_dukes],
                'owned_monsters': [monster.monster_id for monster in obj.owned_monsters],
                'gold_score': obj.gold_score,
                'strength_score': obj.strength_score,
                'magic_score': obj.magic_score,
                'is_first': obj.is_first,
                'shadow_count': obj.shadow_count,
                'holy_count': obj.holy_count,
                'soldier_count': obj.soldier_count,
                'worker_count': obj.worker_count
            }
        elif isinstance(obj, Duke):
            return obj.to_dict()
        elif isinstance(obj, Monster):
            return obj.to_dict()
        elif isinstance(obj, Starter):
            return obj.to_dict()
        elif isinstance(obj, Citizen):
            return obj.to_dict()
        elif isinstance(obj, Domain):
            return obj.to_dict()
        elif isinstance(obj, Game):
            return {
                "game_id": obj.game_id,
                "player_list": obj.player_list,
                "monster_grid": obj.monster_grid,
                "citizen_grid": obj.citizen_grid,
                "domain_grid": obj.domain_grid,
                "die_one": obj.die_one,
                "die_two": obj.die_two,
                "die_sum": obj.die_sum,
                "exhausted_count": obj.exhausted_count
            }
        else:
            return super().default(obj)


def send_data(conn, data):
    header = f"{len(data):<{Constants.header_size}}"
    conn.send(header.encode(Constants.encoding))
    offset = 0
    while offset < len(data):
        chunk = data[offset:offset + Constants.buffer_size]
        conn.send(chunk)
        offset += Constants.buffer_size


def receive_data(conn):
    # Read the header to determine the message length
    header = b""
    while len(header) < Constants.header_size:
        chunk = conn.recv(Constants.header_size - len(header))
        if not chunk:
            raise ConnectionError("Connection closed by server")
        header += chunk
    msg_length = int(header.decode(Constants.encoding).strip())

    # Read the message in chunks until the entire message is received
    data = b""
    while len(data) < msg_length:
        chunk_size = min(Constants.buffer_size, msg_length - len(data))
        chunk = conn.recv(chunk_size)
        if not chunk:
            raise ConnectionError("Connection closed by server")
        data += chunk

    return data
