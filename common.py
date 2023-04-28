import json
from json import JSONEncoder

import mysql.connector
import random
from typing import List, Dict
import shortuuid
import uuid


class Card:
    def __init__(self):
        self.name = ""
        self.is_visible = False
        self.is_accessible = False

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


class Game:
    def __init__(self, game_id, player_list_from_lobby, preset="shuffled", number_of_dukes=2):
        self.game_id = game_id
        self.player_count = len(player_list_from_lobby)
        self.preset = preset
        self.number_of_dukes = number_of_dukes
        self.player_list = []
        self.citizen_grid: List[List[Citizen]] = [[] for _ in range(10)]
        self.domain_grid: List[List[Domain]] = [[] for _ in range(5)]
        self.monster_grid: List[List[Monster]] = [[] for _ in range(5)]
        self.duke_stack = []
        self.domain_stack = []
        self.citizen_stack = []
        self.monster_stack = []
        self.starter_stack = []
        self.graveyard = []
        self.die_one = 0
        self.die_two = 0
        self.die_sum = 0
        self.exhausted_count = 0

        my_connect = mysql.connector.connect(user='vckonline', password='vckonline', host='localhost',
                                             database='vckonline')
        my_cursor = my_connect.cursor(dictionary=True)

        # load game data
        my_cursor.execute("SELECT * FROM dukes")
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_duke = Duke(row['id_dukes'], row['name'], row['gold_mult'], row['strength_mult'], row['magic_mult'],
                           row['shadow_mult'], row['holy_mult'], row['soldier_mult'], row['worker_mult'],
                           row['monster_mult'], row['citizen_mult'], row['domain_mult'], row['boss_mult'],
                           row['minion_mult'], row['beast_mult'], row['titan_mult'], row['expansion'])
            self.duke_stack.append(my_duke)
        random.shuffle(self.duke_stack)
        my_cursor.execute("SELECT * FROM domains")
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_domain = Domain(row['id_domains'], row['name'], row['gold_cost'], row['shadow_count'], row['holy_count'],
                               row['soldier_count'], row['worker_count'], row['vp_reward'],
                               row['has_activation_effect'], row['has_passive_effect'], row['passive_effect'],
                               row['activation_effect'], row['text'], row['expansion'])
            self.domain_stack.append(my_domain)
        random.shuffle(self.domain_stack)

        my_cursor.execute("SELECT * FROM citizens")
        my_result = my_cursor.fetchall()
        for row in my_result:
            for i in range(6):
                my_citizen = Citizen(row['id_citizens'], row['name'], row['gold_cost'], row['roll_match1'],
                                     row['roll_match2'], row['shadow_count'], row['holy_count'], row['soldier_count'],
                                     row['worker_count'], row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                     row['strength_payout_on_turn'], row['strength_payout_off_turn'],
                                     row['magic_payout_on_turn'], row['magic_payout_off_turn'],
                                     row['has_special_payout_on_turn'], row['has_special_payout_off_turn'],
                                     row['special_payout_on_turn'], row['special_payout_off_turn'],
                                     row['special_citizen'],
                                     row['expansion'])
                self.citizen_stack.append(my_citizen)

        my_cursor.execute("SELECT * FROM starters")
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_starter = Starter(row['id_starters'], row['name'], row['roll_match1'], row['roll_match2'],
                                 row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                 row['strength_payout_on_turn'], row['strength_payout_off_turn'],
                                 row['magic_payout_on_turn'], row['magic_payout_off_turn'],
                                 row['has_special_payout_on_turn'], row['has_special_payout_off_turn'],
                                 row['special_payout_on_turn'], row['special_payout_off_turn'], row['expansion'])
            self.starter_stack.append(my_starter)

        my_cursor.execute("SELECT * FROM monsters")
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_monster = Monster(row['id_monsters'], row['name'], row['area'], row['monster_type'],
                                 row['monster_order'], row['strength_cost'], row['magic_cost'], row['vp_reward'],
                                 row['gold_reward'], row['strength_reward'], row['magic_reward'],
                                 row['has_special_reward'], row['special_reward'], row['has_special_cost'],
                                 row['special_cost'], row['is_extra'], row['expansion'])
            self.monster_stack.append(my_monster)
        my_connect.close()
        # end load game data
        # remove extra cards
        if self.player_count != 5:
            extra_monsters = []
            remaining_monsters = []
            for monster in self.monster_stack:
                if monster.is_extra == 1:
                    extra_monsters.append(monster)
                else:
                    remaining_monsters.append(monster)
            self.monster_stack = remaining_monsters
            self.graveyard.extend(extra_monsters)
        match self.preset:
            case "base1":
                base1_monsters = []
                other_expansion_monsters = []
                for monster in self.monster_stack:
                    if monster.expansion == "base1":
                        base1_monsters.append(monster)
                    else:
                        other_expansion_monsters.append(monster)
                self.monster_stack = base1_monsters
                self.graveyard.extend(other_expansion_monsters)
                base1_citizens = []
                other_expansion_citizens = []
                for citizen in self.citizen_stack:
                    if citizen.expansion == "base1":
                        base1_citizens.append(citizen)
                    else:
                        other_expansion_citizens.append(citizen)
                self.citizen_stack = base1_citizens
                self.graveyard.extend(other_expansion_citizens)
            case "base2":
                base1_monsters = []
                base2_monsters = []
                other_expansion_monsters = []
                for monster in self.monster_stack:
                    if monster.expansion == "base1":
                        base1_monsters.append(monster)
                    elif monster.expansion == "base2":
                        base2_monsters.append(monster)
                    else:
                        other_expansion_monsters.append(monster)
                # add 2 random monster areas from base1 to fill out base2 monsters
                grouped_monsters = {}
                for base1_monster in base1_monsters:
                    area = base1_monster.area
                    if area in grouped_monsters:
                        grouped_monsters[area].append(base1_monster)
                    else:
                        grouped_monsters[area] = [base1_monster]
                areas = list(grouped_monsters.keys())
                chosen_areas = random.sample(areas, 2)
                not_chosen_monsters = [monster for area, monsters in grouped_monsters.items() if
                                       area not in chosen_areas for monster in monsters]
                self.graveyard.extend(not_chosen_monsters)
                for i, area in enumerate(chosen_areas):
                    monsters = grouped_monsters[area]
                    base2_monsters.extend(monsters)
                self.monster_stack = base2_monsters
                self.graveyard.extend(other_expansion_monsters)
                base2_citizens = []
                other_expansion_citizens = []
                for citizen in self.citizen_stack:
                    if citizen.expansion == "base2":
                        base2_citizens.append(citizen)
                    else:
                        other_expansion_citizens.append(citizen)
                # add peasant and knight from base1
                for citizen in other_expansion_citizens:
                    if citizen.name == "Peasant" and citizen.expansion == "base1":
                        base2_citizens.append(citizen)
                    elif citizen.name == "Knight" and citizen.expansion == "base1":
                        base2_citizens.append(citizen)
                self.citizen_stack = base2_citizens
                # put the rest of the cards in the graveyard
                grouped_citizens = {}
                for citizen in other_expansion_citizens:
                    expansion = citizen.expansion
                    if expansion in grouped_citizens:
                        grouped_citizens[expansion].append(citizen)
                    else:
                        grouped_citizens[expansion] = [citizen]
                if "base1" in grouped_citizens:
                    base1_citizens = grouped_citizens["base1"]
                    base1_citizens = [citizen for citizen in base1_citizens if
                                      citizen.name not in ("Peasant", "Knight")]
                    grouped_citizens["base1"] = base1_citizens
                    other_expansion_citizens = []
                    for expansion in grouped_citizens.values():
                        other_expansion_citizens.extend(expansion)
                self.graveyard.extend(other_expansion_citizens)
            case "shadowvale":
                shadowvale_monsters = []
                other_expansion_monsters = []
                for monster in self.monster_stack:
                    if monster.expansion == "shadowvale":
                        shadowvale_monsters.append(monster)
                    else:
                        other_expansion_monsters.append(monster)
                self.monster_stack = shadowvale_monsters
                self.graveyard.extend(other_expansion_monsters)
                shadowvale_citizens = []
                other_expansion_citizens = []
                for citizen in self.citizen_stack:
                    if citizen.expansion == "shadowvale":
                        shadowvale_citizens.append(citizen)
                    else:
                        other_expansion_citizens.append(citizen)
                self.citizen_stack = shadowvale_citizens
                self.graveyard.extend(other_expansion_citizens)
            case "flamesandfrost":
                flamesandfrost_monsters = []
                other_expansion_monsters = []
                for monster in self.monster_stack:
                    if monster.expansion == "flamesandfrost":
                        flamesandfrost_monsters.append(monster)
                    else:
                        other_expansion_monsters.append(monster)
                self.monster_stack = flamesandfrost_monsters
                self.graveyard.extend(other_expansion_monsters)
                flamesandfrost_citizens = []
                other_expansion_citizens = []
                for citizen in self.citizen_stack:
                    if citizen.expansion == "flamesandfrost":
                        flamesandfrost_citizens.append(citizen)
                    else:
                        other_expansion_citizens.append(citizen)
                self.citizen_stack = flamesandfrost_citizens
                self.graveyard.extend(other_expansion_citizens)
            case _:
                if self.player_count != 5:
                    for stack in self.monster_grid:
                        # Remove monsters with isExtra = True from each stack
                        stack[:] = [monster for monster in stack if not monster.is_extra]
        # end remove extra cards
        # create players and determine order
        for player in player_list_from_lobby:
            my_player = Player(player.player_id, player.name)
            self.player_list.append(my_player)
        random.shuffle(self.player_list)
        self.player_list[0].is_first = True
        # give players starters and dukes
        for player in self.player_list:
            player.owned_starters.append(self.starter_stack[0])
            player.owned_starters.append(self.starter_stack[1])
            for i in range(number_of_dukes):
                player.owned_dukes.append(self.duke_stack.pop())
        # deal monsters onto the board
        grouped_monsters = {}
        for monster in self.monster_stack:
            area = monster.area
            if area in grouped_monsters:
                grouped_monsters[area].append(monster)
            else:
                grouped_monsters[area] = [monster]
        # Reverse the order of each group by monster_order
        for area, monsters in grouped_monsters.items():
            monsters.sort(key=lambda item: item.order, reverse=True)
        areas = list(grouped_monsters.keys())
        chosen_areas = random.sample(areas, 5)
        for i, area in enumerate(chosen_areas):
            monsters = grouped_monsters[area]
            self.monster_grid[i].extend(monsters)
        for i, stack in enumerate(self.monster_grid):
            for monster in stack:
                monster.toggle_visibility(True)
            # Make the last monster in the stack accessible
            stack[-1].toggle_accessibility(True)
        self.monster_stack = []
        # deal citizens onto the board
        # Create a dictionary to store citizen lists with roll numbers as keys
        citizens_by_roll = {roll: [] for roll in [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]}
        # Group citizens by roll number
        for citizen in self.citizen_stack:
            citizen.toggle_visibility()
            citizens_by_roll[citizen.roll_match1].append(citizen)
        for roll in citizens_by_roll:
            # Map 11 roll to index 9
            index = roll - 1 if roll < 11 else 9
            citizens = citizens_by_roll[roll]
            self.citizen_grid[index].extend(list(citizens))
            # Make the first citizen in each list accessible
            self.citizen_grid[index][-1].toggle_accessibility(True)
        self.citizen_stack = []
        # Deal the domains into the stacks
        for i in range(5):
            stack = self.domain_grid[i]
            for j in range(3):
                if j == 2:  # top domain is visible and accessible
                    domain = self.domain_stack.pop()
                    domain.toggle_visibility(True)
                    domain.toggle_accessibility(True)
                    stack.append(domain)
                else:  # other domains are not visible or accessible
                    domain = self.domain_stack.pop()
                    stack.append(domain)
        self.get_game_state()

    def get_game_state(self):
        for i, monster_list in enumerate(self.monster_grid):
            print(
                f"Monster Stack {i + 1}: {[f'{monster.name} ({monster.monster_id})' + ('E' if monster.is_extra else '') + ('V' if monster.is_visible else '') + ('A' if monster.is_accessible else '') for monster in monster_list]}")
        for i, citizen_list in enumerate(self.citizen_grid):
            print(
                f"Citizen Stack {i + 1}: {[f'{citizen.name} ({citizen.citizen_id})' + ('V' if citizen.is_visible else '') + ('A' if citizen.is_accessible else '') for citizen in citizen_list]}")
        for i, domain_list in enumerate(self.domain_grid):
            print(
                f"Domain Stack {i + 1}: {[f'{domain.name} ({domain.domain_id})' + ('V' if domain.is_visible else '') + ('A' if domain.is_accessible else '') for domain in domain_list]}")
        for i, player in enumerate(self.player_list):
            print(
                f"Player {i + 1}: {[f'{player.player_id}' + (' *' if player.is_first else '') + f' G{player.gold_score} S{player.strength_score} M{player.magic_score}']}")
        print(f"monster stack size {len(self.monster_stack)}")
        print(f"citizen stack size {len(self.citizen_stack)}")
        print(f"domain stack size {len(self.domain_stack)}")
        print(f"graveyard stack size {len(self.graveyard)}")

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
        if self.exhausted_count <= (self.player_count * 2):
            return False


class GameObjectEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Card):
            return {
                "name": obj.name,
                "is_visible": obj.is_visible,
                "is_accessible": obj.is_accessible,
            }
        elif isinstance(obj, Player):
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
            return {
                **super().default(obj),
                "duke_id": obj.duke_id,
                "gold_multiplier": obj.gold_multiplier,
                "strength_multiplier": obj.strength_multiplier,
                "magic_multiplier": obj.magic_multiplier,
                "shadow_multiplier": obj.shadow_multiplier,
                "holy_multiplier": obj.holy_multiplier,
                "soldier_multiplier": obj.soldier_multiplier,
                "worker_multiplier": obj.worker_multiplier,
                "monster_multiplier": obj.monster_multiplier,
                "citizen_multiplier": obj.citizen_multiplier,
                "domain_multiplier": obj.domain_multiplier,
                "boss_multiplier": obj.boss_multiplier,
                "minion_multiplier": obj.minion_multiplier,
                "beast_multiplier": obj.beast_multiplier,
                "titan_multiplier": obj.titan_multiplier,
                "expansion": obj.expansion,
            }
        elif isinstance(obj, Monster):
            return {
                **super().default(obj),
                "monster_id": obj.monster_id,
                "name": obj.name,
                "area": obj.area,
                "monster_type": obj.monster_type,
                "order": obj.order,
                "strength_cost": obj.strength_cost,
                "magic_cost": obj.magic_cost,
                "vp_reward": obj.vp_reward,
                "gold_reward": obj.gold_reward,
                "strength_reward": obj.strength_reward,
                "magic_reward": obj.magic_reward,
                "has_special_reward": obj.has_special_reward,
                "special_reward": obj.special_reward,
                "has_special_cost": obj.has_special_cost,
                "special_cost": obj.special_cost,
                "is_extra": obj.is_extra,
                "expansion": obj.expansion,
            }
        elif isinstance(obj, Starter):
            return {
                **super().default(obj),
                "starter_id": obj.starter_id,
                "name": obj.name,
                "roll_match1": obj.rollMatch1,
                "roll_match2": obj.rollMatch2,
                "gold_payout_on_turn": obj.goldPayoutOnTurn,
                "gold_payout_off_turn": obj.goldPayoutOffTurn,
                "strength_payout_on_turn": obj.strengthPayoutOnTurn,
                "strength_payout_off_turn": obj.strengthPayoutOffTurn,
                "magic_payout_on_turn": obj.magicPayoutOnTurn,
                "magic_payout_off_turn": obj.magicPayoutOffTurn,
                "has_special_payout_on_turn": obj.hasSpecialPayoutOnTurn,
                "has_special_payout_off_turn": obj.hasSpecialPayoutOffTurn,
                "special_payout_on_turn": obj.specialPayoutOnTurn,
                "special_payout_off_turn": obj.specialPayoutOffTurn,
                "expansion": obj.expansion,
            }
        elif isinstance(obj, Citizen):
            return {
                **super().default(obj),
                "citizen_id": obj.citizen_id,
                "name": obj.name,
                "gold_cost": obj.gold_cost,
                "roll_match1": obj.roll_match1,
                "roll_match2": obj.roll_match2,
                "shadow_count": obj.shadow_count,
                "holy_count": obj.holy_count,
                "soldier_count": obj.soldier_count,
                "worker_count": obj.worker_count,
                "gold_payout_on_turn": obj.gold_payout_on_turn,
                "gold_payout_off_turn": obj.gold_payout_off_turn,
                "strength_payout_on_turn": obj.strength_payout_on_turn,
                "strength_payout_off_turn": obj.strength_payout_off_turn,
                "magic_payout_on_turn": obj.magic_payout_on_turn,
                "magic_payout_off_turn": obj.magic_payout_off_turn,
                "has_special_payout_on_turn": obj.has_special_payout_on_turn,
                "has_special_payout_off_turn": obj.has_special_payout_off_turn,
                "special_payout_on_turn": obj.special_payout_on_turn,
                "special_payout_off_turn": obj.special_payout_off_turn,
                "special_citizen": obj.special_citizen,
                "expansion": obj.expansion,
                }
        elif isinstance(obj, Domain):
            return {
                'domain_id': obj.domain_id,
                'name': obj.name,
                'gold_cost': obj.gold_cost,
                'shadow_count': obj.shadow_count,
                'holy_count': obj.holy_count,
                'soldier_count': obj.soldier_count,
                'worker_count': obj.worker_count,
                'vp_reward': obj.vp_reward,
                'has_activation_effect': obj.has_activation_effect,
                'has_passive_effect': obj.has_passive_effect,
                'passive_effect': obj.passive_effect,
                'activation_effect': obj.activation_effect,
                'text': obj.text,
                'expansion': obj.expansion
            }
        elif isinstance(obj, Game):
            return {
                "game_id": obj.game_id,
                "player_count": obj.player_count,
                "preset": obj.preset,
                "number_of_dukes": obj.number_of_dukes,
                "player_list": obj.player_list,
                "citizen_grid": obj.citizen_grid,
                "domain_grid": obj.domain_grid,
                "monster_grid": obj.monster_grid,
                "duke_stack": obj.duke_stack,
                "domain_stack": obj.domain_stack,
                "citizen_stack": obj.citizen_stack,
                "monster_stack": obj.monster_stack,
                "starter_stack": obj.starter_stack,
                "graveyard": obj.graveyard,
                "die_one": obj.die_one,
                "die_two": obj.die_two,
                "die_sum": obj.die_sum,
                "exhausted_count": obj.exhausted_count
            }
        else:
            return super().default(obj)

