import mysql.connector
import random
from typing import List


class Card:
    def __init__(self):
        self.name = ""
        self.is_visible = False
        self.is_accessible = False

    def set_visibility(self, toggle: bool = True):
        self.is_visible = toggle

    def set_accessibility(self, toggle: bool = True):
        self.is_accessible = toggle


class Player:
    def __init__(self):
        self.name = "Player"
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
    def __init__(self, name, roll_match1, roll_match2, gold_payout_on_turn, gold_payout_off_turn,
                 strength_payout_on_turn, strength_payout_off_turn, magic_payout_on_turn, magic_payout_off_turn,
                 has_special_payout_on_turn, has_special_payout_off_turn, special_payout_on_turn,
                 special_payout_off_turn):
        super().__init__()
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


class Citizen(Card):
    def __init__(self, name, gold_cost, roll_match1, roll_match2, shadow_count, holy_count, soldier_count, worker_count,
                 gold_payout_on_turn, gold_payout_off_turn, strength_payout_on_turn, strength_payout_off_turn,
                 magic_payout_on_turn, magic_payout_off_turn, has_special_payout_on_turn, has_special_payout_off_turn,
                 special_payout_on_turn, special_payout_off_turn, special_citizen):
        super().__init__()
        self.name = name
        self.goldCost = gold_cost
        self.rollMatch1 = roll_match1
        self.rollMatch2 = roll_match2
        self.shadowCount = shadow_count
        self.holyCount = holy_count
        self.soldierCount = soldier_count
        self.workerCount = worker_count
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
        self.specialCitizen = special_citizen


class Domain(Card):
    def __init__(self, name, gold_cost, shadow_count, holy_count, soldier_count, worker_count, vp_reward,
                 has_activation_effect, has_passive_effect, passive_effect, activation_effect, text):
        super().__init__()
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


class Monster(Card):
    def __init__(self, name, area, type, order, strength_cost, magic_cost, vp_reward, gold_reward, strength_reward,
                 magic_reward, has_special_reward, special_reward, has_special_cost, special_cost, is_extra):
        super().__init__()
        self.name = name
        self.area = area
        self.type = type
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

    def add_strength_cost(self, added_strength):
        self.strength_cost = self.strength_cost + added_strength

    def add_magic_cost(self, added_magic):
        self.magic_cost = self.magic_cost + added_magic


class Duke(Card):
    def __init__(self, name, gold_mult, strength_mult, magic_mult, shadow_mult, holy_mult, soldier_mult, worker_mult,
                 monster_mult, citizen_mult, domain_mult, boss_mult, minion_mult, beast_mult, titan_mult):
        super().__init__()
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


class Board:
    def __init__(self, player_count, preset, number_of_dukes=2):
        self.player_count = player_count
        self.preset = preset
        self.number_of_dukes = number_of_dukes
        self.player_list = []
        self.citizen_grid = [[] for _ in range(10)]
        self.domain_grid = [[] for _ in range(5)]
        self.monster_grid: List[List[Monster]] = [[] for _ in range(5)]
        self.duke_stack = []
        self.domain_stack = []
        self.citizen_stack = []
        self.monster_stack = []
        self.starter_stack = []
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
            my_duke = Duke(row['name'], row['gold_mult'], row['strength_mult'], row['magic_mult'], row['shadow_mult'],
                           row['holy_mult'], row['soldier_mult'], row['worker_mult'], row['monster_mult'],
                           row['citizen_mult'], row['domain_mult'], row['boss_mult'], row['minion_mult'],
                           row['beast_mult'], row['titan_mult'])
            self.duke_stack.append(my_duke)
        random.shuffle(self.duke_stack)
        my_cursor.execute("SELECT * FROM domains")
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_domain = Domain(row['name'], row['gold_cost'], row['shadow_count'], row['holy_count'],
                               row['soldier_count'], row['worker_count'], row['vp_reward'],
                               row['has_activation_effect'],
                               row['has_passive_effect'], row['passive_effect'], row['activation_effect'], row['text'])
            self.domain_stack.append(my_domain)
        random.shuffle(self.domain_stack)

        my_cursor.execute("SELECT * FROM citizens")
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_citizen = Citizen(row['name'], row['gold_cost'], row['roll_match1'], row['roll_match2'],
                                 row['shadow_count'], row['holy_count'], row['soldier_count'], row['worker_count'],
                                 row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                 row['strength_payout_on_turn'],
                                 row['strength_payout_off_turn'], row['magic_payout_on_turn'],
                                 row['magic_payout_off_turn'], row['has_special_payout_on_turn'],
                                 row['has_special_payout_off_turn'], row['special_payout_on_turn'],
                                 row['special_payout_off_turn'], row['special_citizen'])
            self.citizen_stack.append(my_citizen)
        random.shuffle(self.citizen_stack)

        my_cursor.execute("SELECT * FROM starters")
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_starter = Starter(row['name'], row['roll_match1'], row['roll_match2'], row['gold_payout_on_turn'],
                                 row['gold_payout_off_turn'], row['strength_payout_on_turn'],
                                 row['strength_payout_off_turn'], row['magic_payout_on_turn'],
                                 row['magic_payout_off_turn'], row['has_special_payout_on_turn'],
                                 row['has_special_payout_off_turn'], row['special_payout_on_turn'],
                                 row['special_payout_off_turn'])
            self.starter_stack.append(my_starter)

        my_cursor.execute("SELECT * FROM monsters")
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_monster = Monster(row['name'], row['area'], row['type'], row['order'], row['strength_cost'],
                                 row['magic_cost'], row['vp_reward'], row['gold_reward'], row['strength_reward'],
                                 row['magic_reward'], row['has_special_reward'], row['special_reward'],
                                 row['has_special_cost'], row['special_cost'], row['is_extra'])
            self.monster_stack.append(my_monster)
        my_connect.close()
        # end load game data

        # create players and deal cards
        for x in range(0, self.player_count):
            my_player = Player()
            my_player.name = f"Player {(x + 1)}"
            self.player_list.append(my_player)
        random.shuffle(self.player_list)
        self.player_list[0].is_first = True
        for player in self.player_list:
            player.owned_starters.append(self.starter_stack[0])
            player.owned_starters.append(self.starter_stack[1])
            for i in range(number_of_dukes):
                player.owned_dukes.append(self.duke_stack.pop())
        grouped_monsters = {}
        for monster in self.monster_stack:
            area = monster.area
            if area in grouped_monsters:
                grouped_monsters[area].append(monster)
            else:
                grouped_monsters[area] = [monster]
        if self.preset == "shuffled":
            # Convert grouped_monsters to a list of (area, monsters) tuples
            area_monsters = list(grouped_monsters.items())
            # Shuffle the list of (area, monsters) tuples
            random.shuffle(area_monsters)
            # Convert the shuffled list back to a dictionary
            grouped_monsters = {area: monsters for area, monsters in area_monsters}

        # Fill the stacks with monsters from each area
        stack_index = 0
        for area, monsters in grouped_monsters.items():
            if stack_index >= 5:  # stop dealing after 5 stacks
                break
            stack = self.monster_grid[stack_index]
            for monster in monsters:
                stack.append(monster)
                stack_index = (stack_index + 1) % 5  # move to the next stack
        if self.player_count != 5:
            for stack in self.monster_grid:
                # Remove monsters with isExtra = True from each stack
                stack[:] = [monster for monster in stack if not monster.is_extra]
                # Turn monsters face up
                for monster in stack:
                    monster.set_visibility(True)
        for i, stack in enumerate(self.monster_grid):
            sorted_stack = sorted(stack, key=lambda monster: monster.order, reverse=True)
            self.monster_grid[i] = sorted_stack
        for stack in self.monster_grid:
            if stack:  # check if the stack is not empty
                monster = stack.pop()
                print(f"Popped {monster.name}")

    def roll_phase(self):
        self.die_one = random.randint(1, 6)
        self.die_two = random.randint(1, 6)
        self.die_sum = self.die_one + self.die_two
        print(f"{self.die_one} | {self.die_two} | {self.die_sum}")
        for citizen in self.player_list[0].owned_citizens:
            if (citizen.rollMatch1 == self.die_one) or (citizen.rollMatch1 == self.die_two) or (
                    citizen.rollMatch1 == self.die_sum) or (citizen.rollMatch2 == self.die_sum):
                print(f"{citizen.name} Payout")
                self.player_list[0].gold_score = self.player_list[0].gold_score + citizen.goldPayoutOnTurn
                self.player_list[0].strength_score = self.player_list[0].strength_score + citizen.strengthPayoutOnTurn
                self.player_list[0].magic_score = self.player_list[0].magic_score + citizen.magicPayoutOnTurn
        list_iterator = iter(self.player_list)
        next(list_iterator)
        for player in list_iterator:
            for citizen in player.owned_citizens:
                if (citizen.rollMatch1 == self.die_one) or (citizen.rollMatch1 == self.die_two) or (
                        citizen.rollMatch1 == self.die_sum) or (citizen.rollMatch2 == self.die_sum):
                    print(f"{citizen.name} Payout")
                    player.gold_score = player.gold_score + citizen.goldPayoutOffTurn
                    player.strength_score = player.strength_score + citizen.strengthPayoutOffTurn
                    player.magic_score = player.magic_score + citizen.magicPayoutOffTurn

    def play_turn(self):
        self.roll_phase()

    def end_check(self):
        if self.exhausted_count <= (self.player_count * 2):
            return False
