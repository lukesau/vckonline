import time
import random
from json import JSONEncoder
from typing import List
import mariadb
from constants import *
from cards import *


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
        self.effects = {
            "roll_phase": [],
            "harvest_phase": [],
            "action_phase": []
        }

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
        player.victory_score = data['victory_score']
        player.is_first = data['is_first']
        player.shadow_count = data['shadow_count']
        player.holy_count = data['holy_count']
        player.soldier_count = data['soldier_count']
        player.worker_count = data['worker_count']
        player.effects = data['effects']
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
        roles_dict = {
            "shadow_count": shadow_count,
            "holy_count": holy_count,
            "soldier_count": soldier_count,
            "worker_count": worker_count
        }
        return roles_dict


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
        self.effects = game_state['effects']
        self.action_required = game_state['action_required']
        self.last_active_time = 0

    def roll_phase(self):
        self.die_one = random.randint(1, 6)
        self.die_two = random.randint(1, 6)
        self.die_sum = self.die_one + self.die_two
        print(f"{self.die_one} | {self.die_two} | {self.die_sum}")
        # check for player effects that are able to change roll
        # check for board effects that trigger from rolls

    def harvest_phase(self):
        # steal activates first
        for starter in self.player_list[0].owned_starters:
            if (starter.roll_match1 == self.die_one) or (starter.roll_match1 == self.die_two) or (
                    starter.roll_match1 == self.die_sum) or (starter.roll_match2 == self.die_sum):
                count = 1
                if starter.roll_match1 == self.die_one == self.die_two:
                    count = 2
                print(f"Payout for {self.player_list[0].name}: Starter {starter.name}{' x2' if count == 2 else ''}")
                for i in range(count):
                    self.player_list[0].gold_score = self.player_list[0].gold_score + starter.gold_payout_on_turn
                    self.player_list[0].strength_score = self.player_list[
                                                             0].strength_score + starter.strength_payout_on_turn
                    self.player_list[0].magic_score = self.player_list[0].magic_score + starter.magic_payout_on_turn
                    if starter.has_special_payout_on_turn:
                        payout = self.execute_special_payout(starter.special_payout_on_turn,
                                                             self.player_list[0].player_id)
                        self.player_list[0].gold_score = self.player_list[0].gold_score + payout[0]
                        self.player_list[0].strength_score = self.player_list[0].strength_score + payout[1]
                        self.player_list[0].magic_score = self.player_list[0].magic_score + payout[2]
        for citizen in self.player_list[0].owned_citizens:
            if (citizen.roll_match1 == self.die_one) or (citizen.roll_match1 == self.die_two) or (
                    citizen.roll_match1 == self.die_sum) or (citizen.roll_match2 == self.die_sum):
                count = 1
                if citizen.roll_match1 == self.die_one == self.die_two:
                    count = 2
                print(f"Payout for {self.player_list[0].name}: Citizen {citizen.name}{' x2' if count == 2 else ''}")
                for i in range(count):
                    self.player_list[0].gold_score = self.player_list[0].gold_score + citizen.gold_payout_on_turn
                    self.player_list[0].strength_score = self.player_list[
                                                             0].strength_score + citizen.strength_payout_on_turn
                    self.player_list[0].magic_score = self.player_list[0].magic_score + citizen.magic_payout_on_turn
                    if citizen.has_special_payout_on_turn:
                        print(f"Citizen {citizen.name} special payout text: {citizen.special_payout_on_turn}")
                        payout = self.execute_special_payout(citizen.special_payout_on_turn,
                                                             self.player_list[0].player_id)
                        print(f"right after running execute special payout {payout}")
                        self.player_list[0].gold_score = self.player_list[0].gold_score + payout[0]
                        self.player_list[0].strength_score = self.player_list[0].strength_score + payout[1]
                        self.player_list[0].magic_score = self.player_list[0].magic_score + payout[2]

        list_iterator = iter(self.player_list)  # skip first player when paying out the rest of the board
        next(list_iterator)
        for player in list_iterator:
            for starter in player.owned_starters:
                if (starter.roll_match1 == self.die_one) or (starter.roll_match1 == self.die_two) or (
                        starter.roll_match1 == self.die_sum) or (starter.roll_match2 == self.die_sum):
                    count = 1
                    if starter.roll_match1 == self.die_one == self.die_two:
                        count = 2
                    print(f"Payout for {player.name}: Starter {starter.name}{' x2' if count == 2 else ''}")
                    for i in range(count):
                        player.gold_score = player.gold_score + starter.gold_payout_off_turn
                        player.strength_score = player.strength_score + starter.strength_payout_off_turn
                        player.magic_score = player.magic_score + starter.magic_payout_off_turn
                        if starter.has_special_payout_off_turn:
                            payout = self.execute_special_payout(starter.special_payout_off_turn, player.player_id)
                            player.gold_score = player.gold_score + payout[0]
                            player.strength_score = player.strength_score + payout[1]
                            player.magic_score = player.magic_score + payout[2]

            for citizen in player.owned_citizens:
                if (citizen.roll_match1 == self.die_one) or (citizen.roll_match1 == self.die_two) or (
                        citizen.roll_match1 == self.die_sum) or (citizen.roll_match2 == self.die_sum):
                    count = 1
                    if citizen.roll_match1 == self.die_one == self.die_two:
                        count = 2
                    print(f"Payout for {player.name}: Citizen {citizen.name}{' x2' if count == 2 else ''}")
                    for i in range(count):
                        player.gold_score = player.gold_score + citizen.gold_payout_off_turn
                        player.strength_score = player.strength_score + citizen.strength_payout_off_turn
                        player.magic_score = player.magic_score + citizen.magic_payout_off_turn
                        if citizen.has_special_payout_off_turn:
                            print("special payout off turn triggered")
                            print(citizen.special_payout_off_turn)
                            payout = self.execute_special_payout(citizen.special_payout_off_turn, player.player_id)
                            player.gold_score = player.gold_score + payout[0]
                            player.strength_score = player.strength_score + payout[1]
                            player.magic_score = player.magic_score + payout[2]
        for player in self.player_list:
            print(f"Player {player.name}: {player.gold_score} G, {player.strength_score} S, {player.magic_score} M,"
                  f" {player.victory_score} VP, Monsters: {len(player.owned_monsters)}, "
                  f"Citizens: {len(player.owned_citizens)}, Domains {len(player.owned_domains)}")

    def execute_special_payout(self, command, player_id):
        print("executing special payout")
        payout = [0, 0, 0, 0]  # gp, sp, mp, vp, todo: citizen, monster, domain
        split_command = command.split()
        first_word = split_command[0]
        second_word = split_command[1]
        third_word = split_command[2]
        fourth_word = split_command[3]
        match first_word:
            case "count":
                print("Matched count")
                match second_word:
                    case "owned_shadow":
                        self.update_payout_for_role('shadow_count', player_id, payout, split_command)
                    case "owned_holy":
                        self.update_payout_for_role('holy_count', player_id, payout, split_command)
                    case "owned_soldier":
                        self.update_payout_for_role('soldier_count', player_id, payout, split_command)
                    case "owned_worker":

                        self.update_payout_for_role('worker_count', player_id, payout, split_command)
                    case "owned_monsters":
                        self.update_payout_for_role('owned_monsters', player_id, payout, split_command)
                    case "owned_citizens":
                        self.update_payout_for_role('owned_citizens', player_id, payout, split_command)
                    case "owned_domains":
                        self.update_payout_for_role('owned_domains', player_id, payout, split_command)
                    case _:
                        payout[0] = -9999
            case "exchange":
                print("Matched exchange")
                match second_word:
                    case 'g':
                        payout[0] = payout[0] - int(third_word)
                    case 's':
                        payout[1] = payout[1] - int(third_word)
                    case 'm':
                        payout[2] = payout[2] - int(third_word)
                    case 'v':
                        payout[3] = payout[3] - int(third_word)
                    case _:
                        payout[0] = -9999
                match fourth_word:
                    case 'g':
                        payout[0] = payout[0] + int(split_command[4])
                    case 's':
                        payout[1] = payout[1] + int(split_command[4])
                    case 'm':
                        payout[2] = payout[2] + int(split_command[4])
                    case 'v':
                        payout[3] = payout[3] + int(split_command[4])
                    case _:
                        payout[0] = -9999
            case "choose":
                print("Matched choose")
                self.action_required['player_id'] = player_id
                self.action_required['action'] = command
                # need to pause execution here until we get player input
                while self.action_required['player_id'] != self.game_id:
                    time.sleep(1)
                choice = []
                match self.action_required['action']:
                    case 'choose 1':
                        choice = [second_word, third_word]
                    case 'choose 2':
                        choice = [fourth_word, split_command[4]]
                    case 'choose 3':
                        choice = [split_command[5], split_command[6]]  # [sixth_word, seventh_word]
                    case _:
                        payout[0] = -9999
                match choice[0]:
                    case 'g':
                        payout[0] = payout[0] + choice[1]
                    case 's':
                        payout[1] = payout[1] + choice[1]
                    case 'm':
                        payout[2] = payout[2] + choice[1]
                    case 'v':
                        payout[3] = payout[3] + choice[1]
                    case _:
                        payout[0] = -9999
            case _:
                payout[0] = -9999
        print(payout)
        return payout

    def owned_monster_attributes(self, player_id):
        return_dict = {attr: 0 for attr in Constants.areas + Constants.types}
        for player in self.player_list:
            if player.player_id == player_id:
                for monster in player.owned_monsters:
                    for area in Constants.areas:
                        if monster.area == area:
                            return_dict[area] += 1
                    for monster_type in Constants.types:
                        if monster.monster_type == monster_type:
                            return_dict[monster_type] += 1

        return return_dict

    def update_payout_for_role(self, role_name, player_id, payout, split_command):
        role_count = 0
        for player in self.player_list:
            if player.player_id == player_id:
                role_count = player.calc_roles()[role_name]
                break
        if role_count > 0:
            match split_command[2]:
                case 'g':
                    payout[0] = int(split_command[3]) * role_count
                case 's':
                    payout[1] = int(split_command[3]) * role_count
                case 'm':
                    payout[2] = int(split_command[3]) * role_count
                case 'v':
                    payout[3] = int(split_command[3]) * role_count
                case _:
                    payout[0] = -9999
        else:
            payout[0] = -9999

    def hire_citizen(self, player_id, citizen_id, gp, mp=0):
        for citizen_stack in self.citizen_grid:
            for citizen in citizen_stack:
                if citizen.citizen_id == citizen_id and citizen.is_accessible:
                    for player in self.player_list:
                        if player.player_id == player_id:
                            player.gold_score = player.gold_score - gp
                            player.magic_score = player.magic_score - mp
                            player.owned_citizens.append(citizen_stack.pop(-1))
                    citizen_stack[-1].toggle_accessibility(True)

    def slay_monster(self, player_id, monster_id, sp, mp=0):
        payout = [0, 0, 0, 0]
        for monster_stack in self.monster_grid:
            for monster in monster_stack:
                if monster.monster_id == monster_id:  # and monster.is_accessible:
                    for player in self.player_list:
                        if player.player_id == player_id:
                            player.strength_score = player.strength_score - sp
                            player.magic_score = player.magic_score - mp
                            player.owned_monsters.append(monster_stack.pop(-1))
                    if monster.has_special_reward:
                        payout = self.execute_special_payout(monster.special_reward, player_id)
                    payout[0] = payout[0] + monster.gold_reward
                    payout[1] = payout[1] + monster.strength_reward
                    payout[2] = payout[2] + monster.magic_reward
                    payout[3] = payout[3] + monster.vp_reward
                    for player in self.player_list:
                        if player.player_id == player_id:
                            player.gold_score = player.gold_score + payout[0]
                            player.strength_score = player.strength_score + payout[1]
                            player.magic_score = player.magic_score + payout[2]
                            player.victory_score = player.victory_score + payout[3]
                    monster_stack[-1].toggle_accessibility(True)

    def buy_domain(self, player_id, domain_id, gp, mp=0):
        for domain_stack in self.domain_grid:
            for domain in domain_stack:
                if domain.domain_id == domain_id and domain.is_accessible:
                    for player in self.player_list:
                        if player.player_id == player_id:
                            player.gold_score = player.gold_score - gp
                            player.magic_score = player.magic_score - mp
                            player.owned_domains.append(domain_stack.pop(-1))
                    domain_stack[-1].toggle_accessibility(True)

    def action_phase(self):
        return

    def play_turn(self):
        self.roll_phase()
        self.harvest_phase()
        self.action_phase()

    def end_check(self):
        if self.exhausted_count <= (len(self.player_list) * 2):
            return False

    def prompt(self):
        return


class LobbyMember:
    def __init__(self, player_name, player_id):
        self.name = player_name
        self.player_id = player_id
        self.is_ready = False
        self.last_active_time = 0


class GameMember:
    def __init__(self, player_id, player_name, game_id):
        self.name = player_name
        self.player_id = player_id
        self.game_id = game_id


def load_game_data(game_id, preset, player_list_from_lobby):
    monster_query = ""
    monster_stack = []
    citizen_query = ""
    citizen_stack = []
    domain_query = "select_random_domains"
    domain_stack = []
    duke_query = "select_random_dukes"
    duke_stack = []
    starter_query = "SELECT * FROM starters"
    starter_stack = []
    player_list = []
    citizen_grid: List[List[Citizen]] = [[] for _ in range(10)]
    domain_grid: List[List[Domain]] = [[] for _ in range(5)]
    monster_grid: List[List[Monster]] = [[] for _ in range(5)]
    die_one = 0
    die_two = 0
    die_sum = 0
    exhausted_count = 0
    effects = {
        "roll_phase": [],
        "harvest_phase": [],
        "action_phase": []
    }
    action_required = {
        "player_id": "",
        "action": ""
    }
    match preset:
        case "base1":
            monster_query = "select_base1_monsters"
            citizen_query = "select_base1_citizens"
        case "base2":
            monster_query = "select_base2_monsters"
            citizen_query = "select_base2_citizens"
    try:
        my_connect = mariadb.connect(user='vckonline', password='vckonline', host='127.0.0.1',
                                     database='vckonline')
        my_cursor = my_connect.cursor(dictionary=True)

        my_cursor.callproc(monster_query)

        results = my_cursor.fetchall()
        for row in results:
            my_monster = Monster(row['id_monsters'], row['name'], row['area'], row['monster_type'],
                                 row['monster_order'], row['strength_cost'], row['magic_cost'], row['vp_reward'],
                                 row['gold_reward'], row['strength_reward'], row['magic_reward'],
                                 row['has_special_reward'], row['special_reward'], row['has_special_cost'],
                                 row['special_cost'], row['is_extra'], row['expansion'])
            monster_stack.append(my_monster)

        my_cursor.callproc(citizen_query)
        citizen_count = 5
        if len(player_list_from_lobby) == 5:
            citizen_count = 6
        results = my_cursor.fetchall()
        for row in results:
            for i in range(citizen_count):
                my_citizen = Citizen(row['id_citizens'], row['name'], row['gold_cost'], row['roll_match1'],
                                     row['roll_match2'], row['shadow_count'], row['holy_count'], row['soldier_count'],
                                     row['worker_count'], row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                     row['strength_payout_on_turn'], row['strength_payout_off_turn'],
                                     row['magic_payout_on_turn'], row['magic_payout_off_turn'],
                                     row['has_special_payout_on_turn'], row['has_special_payout_off_turn'],
                                     row['special_payout_on_turn'], row['special_payout_off_turn'],
                                     row['special_citizen'],
                                     row['expansion'])
                citizen_stack.append(my_citizen)

        my_cursor.callproc(domain_query)
        results = my_cursor.fetchall()
        for row in results:
            my_domain = Domain(row['id_domains'], row['name'], row['gold_cost'], row['shadow_count'], row['holy_count'],
                               row['soldier_count'], row['worker_count'], row['vp_reward'],
                               row['has_activation_effect'], row['has_passive_effect'], row['passive_effect'],
                               row['activation_effect'], row['text'], row['expansion'])
            domain_stack.append(my_domain)

        my_cursor.callproc(duke_query)
        results = my_cursor.fetchall()
        for row in results:
            my_duke = Duke(row['id_dukes'], row['name'], row['gold_mult'], row['strength_mult'], row['magic_mult'],
                           row['shadow_mult'], row['holy_mult'], row['soldier_mult'], row['worker_mult'],
                           row['monster_mult'], row['citizen_mult'], row['domain_mult'], row['boss_mult'],
                           row['minion_mult'], row['beast_mult'], row['titan_mult'], row['expansion'])
            duke_stack.append(my_duke)

        my_cursor.execute(starter_query)
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_starter = Starter(row['id_starters'], row['name'], row['roll_match1'], row['roll_match2'],
                                 row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                 row['strength_payout_on_turn'], row['strength_payout_off_turn'],
                                 row['magic_payout_on_turn'], row['magic_payout_off_turn'],
                                 row['has_special_payout_on_turn'], row['has_special_payout_off_turn'],
                                 row['special_payout_on_turn'], row['special_payout_off_turn'], row['expansion'])
            starter_stack.append(my_starter)
        my_cursor.close()
        my_connect.close()
    except Exception as e:
        print(f"Error: {e}")
    # print(f"size of monster stack: {len(monster_stack)}")
    # print(f"size of citizen stack: {len(citizen_stack)}")
    # print(f"size of domain stack: {len(domain_stack)}")
    # print(f"size of duke stack: {len(duke_stack)}")
    # print(f"size of starter stack: {len(starter_stack)}")
    # create players and determine order
    if not all([player_list_from_lobby, starter_query, monster_stack, citizen_stack, domain_stack, duke_stack]):
        raise ValueError("One or more required lists are empty.")
    else:
        for player in player_list_from_lobby:
            my_player = Player(player.player_id, player.name)
            player_list.append(my_player)
        random.shuffle(player_list)
        player_list[0].is_first = True
        # give players starters and dukes
        for player in player_list:
            player.owned_starters.append(starter_stack[0])
            player.owned_starters.append(starter_stack[1])
            for i in range(2):
                player.owned_dukes.append(duke_stack.pop())
        # deal monsters onto the board
        grouped_monsters = {}
        for monster in monster_stack:
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
            monster_grid[i].extend(monsters)
        for i, stack in enumerate(monster_grid):
            for monster in stack:
                monster.toggle_visibility(True)
            # Make the last monster in the stack accessible
            stack[-1].toggle_accessibility(True)
        # deal citizens onto the board
        # Create a dictionary to store citizen lists with roll numbers as keys
        citizens_by_roll = {roll: [] for roll in [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]}
        # Group citizens by roll number
        for citizen in citizen_stack:
            citizen.toggle_visibility()
            citizens_by_roll[citizen.roll_match1].append(citizen)
        for roll in citizens_by_roll:
            # Map 11 roll to index 9
            index = roll - 1 if roll < 11 else 9
            citizens = citizens_by_roll[roll]
            citizen_grid[index].extend(list(citizens))
            # Make the first citizen in each list accessible
            citizen_grid[index][-1].toggle_accessibility(True)
        # Deal the domains into the stacks
        for i in range(5):
            stack = domain_grid[i]
            for j in range(3):
                if j == 2:  # top domain is visible and accessible
                    domain = domain_stack.pop()
                    domain.toggle_visibility(True)
                    domain.toggle_accessibility(True)
                    stack.append(domain)
                else:  # other domains are not visible or accessible
                    domain = domain_stack.pop()
                    stack.append(domain)

        # Create a dictionary to store all the stacks
        game_state = {'game_id': game_id,
                      'player_list': player_list,
                      'monster_grid': monster_grid,
                      'citizen_grid': citizen_grid,
                      'domain_grid': domain_grid,
                      'die_one': die_one,
                      'die_two': die_two,
                      'die_sum': die_sum,
                      'exhausted_count': exhausted_count,
                      'effects': effects,
                      'action_required': action_required}
        # Return the dictionary
        return game_state


class SummaryEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Player):
            return {
                'player_id': obj.player_id,
                'name': obj.name,
                'owned_citizens': len(obj.owned_citizens),
                'owned_domains': len(obj.owned_domains),
                'owned_monsters': len(obj.owned_monsters),
                'gold_score': obj.gold_score,
                'strength_score': obj.strength_score,
                'magic_score': obj.magic_score,
                'victory_score': obj.victory_score,
                'is_first': obj.is_first
            }
        elif isinstance(obj, LobbyMember):
            return {
                "player_name": obj.name,
                "player_id": obj.player_id,
                "is_ready": obj.is_ready
            }
        elif isinstance(obj, GameMember):
            return {
                "player_name": obj.name,
                "player_id": obj.player_id
            }
        elif isinstance(obj, Game):
            return {
                "game_id": obj.game_id,
                "player_list": obj.player_list
            }
        else:
            return super().default(obj)


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
                'victory_score': obj.victory_score,
                'is_first': obj.is_first,
                'shadow_count': obj.shadow_count,
                'holy_count': obj.holy_count,
                'soldier_count': obj.soldier_count,
                'worker_count': obj.worker_count,
                'effects': obj.effects
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
                "exhausted_count": obj.exhausted_count,
                "effects": obj.effects,
                "action_required": obj.action_required
            }
        else:
            return super().default(obj)
