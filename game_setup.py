import random
from typing import List

from banned_cards import banned_domain_ids, banned_duke_ids
from cards import Citizen, Domain, Duke, Exhausted, Monster, Starter
from game_models import Player


def load_game_data(game_id, preset, player_list_from_lobby, debug_starting_resources=False):
    import mariadb

    monster_query = ""
    monster_stack = []
    citizen_query = ""
    citizen_stack = []
    domain_query = "select_random_domains"
    domain_stack = []
    duke_query = "select_random_dukes"
    duke_stack = []
    exhausted_stack = [Exhausted(i) for i in range(len(player_list_from_lobby) * 2)]
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
        "action_phase": [],
    }
    action_required = {
        "id": "",
        "action": "",
    }
    tick_id = 0
    turn_number = 1
    turn_index = 0
    # Start in setup; if no setup actions are needed the engine will advance into roll.
    phase = "setup"
    actions_remaining = 0
    harvest_processed = False
    pending_harvest_choices = []
    match preset:
        case "base1":
            monster_query = "select_base1_monsters"
            citizen_query = "select_base1_citizens"
            domain_query = "select_random_domains"
        case "base2":
            monster_query = "select_base2_monsters"
            citizen_query = "select_base2_citizens"
            domain_query = "select_random_domains"
        case "test1":
            monster_query = "select_base1_monsters"
            citizen_query = "select_base1_citizens"
            domain_query = "select_test1_domains"
        case "test2" | "current":
            monster_query = "select_base2_monsters"
            citizen_query = "select_base2_citizens"
            domain_query = "select_test2_domains"
    try:
        my_connect = mariadb.connect(
            user="vckonline", password="vckonline", host="127.0.0.1", database="vckonline", port=3306
        )
        my_cursor = my_connect.cursor(dictionary=True)

        my_cursor.callproc(monster_query)

        results = my_cursor.fetchall()
        for row in results:
            my_monster = Monster(
                row["id_monsters"],
                row["name"],
                row["area"],
                row["monster_type"],
                row["monster_order"],
                row["strength_cost"],
                row["magic_cost"],
                row["vp_reward"],
                row["gold_reward"],
                row["strength_reward"],
                row["magic_reward"],
                row["has_special_reward"],
                row["special_reward"],
                row["has_special_cost"],
                row["special_cost"],
                row["is_extra"],
                row["expansion"],
            )
            monster_stack.append(my_monster)

        my_cursor.callproc(citizen_query)
        citizen_count = 5
        if len(player_list_from_lobby) == 5:
            citizen_count = 6
        results = my_cursor.fetchall()
        for row in results:
            for _ in range(citizen_count):
                my_citizen = Citizen(
                    row["id_citizens"],
                    row["name"],
                    row["gold_cost"],
                    row["roll_match1"],
                    row["roll_match2"],
                    row["shadow_count"],
                    row["holy_count"],
                    row["soldier_count"],
                    row["worker_count"],
                    row["gold_payout_on_turn"],
                    row["gold_payout_off_turn"],
                    row["strength_payout_on_turn"],
                    row["strength_payout_off_turn"],
                    row["magic_payout_on_turn"],
                    row["magic_payout_off_turn"],
                    row["has_special_payout_on_turn"],
                    row["has_special_payout_off_turn"],
                    row["special_payout_on_turn"],
                    row["special_payout_off_turn"],
                    row["special_citizen"],
                    row["expansion"],
                )
                citizen_stack.append(my_citizen)

        my_cursor.callproc(domain_query)
        results = my_cursor.fetchall()
        skip_domains = banned_domain_ids()
        if skip_domains:
            results = [r for r in results if int(r["id_domains"]) not in skip_domains]
        domains_needed = 15  # 5 stacks x 3 cards
        if len(results) < domains_needed:
            if skip_domains:
                raise ValueError(
                    "Not enough domains after applying banned_cards.json "
                    f"(need {domains_needed}, have {len(results)} from {domain_query}). "
                    "Remove ids from the \"domains\" list to unban, or widen the procedure's pool."
                )
            raise ValueError(
                f"Not enough domains returned by {domain_query} "
                f"(need {domains_needed}, have {len(results)})."
            )
        for row in results:
            my_domain = Domain(
                row["id_domains"],
                row["name"],
                row["gold_cost"],
                row["shadow_count"],
                row["holy_count"],
                row["soldier_count"],
                row["worker_count"],
                row["vp_reward"],
                row["has_activation_effect"],
                row["has_passive_effect"],
                row["passive_effect"],
                row["activation_effect"],
                row["text"],
                row["expansion"],
            )
            domain_stack.append(my_domain)

        my_cursor.callproc(duke_query)
        results = my_cursor.fetchall()
        skip_dukes = banned_duke_ids()
        if skip_dukes:
            results = [r for r in results if int(r["id_dukes"]) not in skip_dukes]
        dukes_needed = 2 * len(player_list_from_lobby)
        if len(results) < dukes_needed:
            raise ValueError(
                "Not enough dukes after applying banned_cards.json "
                f"(need {dukes_needed} for {len(player_list_from_lobby)} players, "
                f"have {len(results)}). Remove ids from the \"dukes\" list to unban."
            )
        for row in results:
            my_duke = Duke(
                row["id_dukes"],
                row["name"],
                row["gold_mult"],
                row["strength_mult"],
                row["magic_mult"],
                row["shadow_mult"],
                row["holy_mult"],
                row["soldier_mult"],
                row["worker_mult"],
                row["monster_mult"],
                row["citizen_mult"],
                row["domain_mult"],
                row["boss_mult"],
                row["minion_mult"],
                row["beast_mult"],
                row["titan_mult"],
                row["expansion"],
            )
            duke_stack.append(my_duke)

        my_cursor.execute(starter_query)
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_starter = Starter(
                row["id_starters"],
                row["name"],
                row["roll_match1"],
                row["roll_match2"],
                row["gold_payout_on_turn"],
                row["gold_payout_off_turn"],
                row["strength_payout_on_turn"],
                row["strength_payout_off_turn"],
                row["magic_payout_on_turn"],
                row["magic_payout_off_turn"],
                row["has_special_payout_on_turn"],
                row["has_special_payout_off_turn"],
                row["special_payout_on_turn"],
                row["special_payout_off_turn"],
                row["expansion"],
                row.get("activation_trigger", "") or "",
            )
            starter_stack.append(my_starter)
        my_cursor.close()
        my_connect.close()
    except Exception as e:
        print(f"Error: {e}")
    # create players and determine order
    if not all([player_list_from_lobby, starter_query, monster_stack, citizen_stack, domain_stack, duke_stack]):
        raise ValueError("One or more required lists are empty.")
    else:
        for player in player_list_from_lobby:
            my_player = Player(player.player_id, player.name)
            if debug_starting_resources:
                my_player.gold_score = 100
                my_player.strength_score = 100
                my_player.magic_score = 100
            player_list.append(my_player)
        random.shuffle(player_list)
        player_list[0].is_first = True
        # give players starters and dukes
        for player in player_list:
            player.owned_starters.append(starter_stack[0])
            player.owned_starters.append(starter_stack[1])
            for _ in range(2):
                player.owned_dukes.append(duke_stack.pop())
        # deal monsters onto the board.
        # is_extra monsters only ship with the 5-player stack; at smaller player
        # counts each area drops its is_extra card so the stacks are one shorter.
        include_extra_monsters = len(player_list_from_lobby) == 5
        grouped_monsters = {}
        for monster in monster_stack:
            if not include_extra_monsters and bool(getattr(monster, "is_extra", False)):
                continue
            area = monster.area
            if area in grouped_monsters:
                grouped_monsters[area].append(monster)
            else:
                grouped_monsters[area] = [monster]
        for area, monsters in grouped_monsters.items():
            monsters.sort(key=lambda item: item.order, reverse=True)
        areas = list(grouped_monsters.keys())
        chosen_areas = random.sample(areas, 5)
        monster_stack_areas = list(chosen_areas)
        for i, area in enumerate(chosen_areas):
            monsters = grouped_monsters[area]
            monster_grid[i].extend(monsters)
        for stack in monster_grid:
            for monster in stack:
                monster.toggle_visibility(True)
            stack[-1].toggle_accessibility(True)
        # deal citizens onto the board
        citizens_by_roll = {roll: [] for roll in [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]}
        for citizen in citizen_stack:
            citizen.toggle_visibility()
            citizens_by_roll[citizen.roll_match1].append(citizen)
        for roll in citizens_by_roll:
            index = roll - 1 if roll < 11 else 9
            citizens = citizens_by_roll[roll]
            citizen_grid[index].extend(list(citizens))
            citizen_grid[index][-1].toggle_accessibility(True)
        if debug_starting_resources:
            for player in player_list:
                for stack in citizen_grid:
                    c = stack.pop(-1)
                    c.is_flipped = False
                    c.toggle_visibility(True)
                    c.toggle_accessibility(True)
                    player.owned_citizens.append(c)
                    if stack:
                        stack[-1].toggle_accessibility(True)
        # deal the domains into stacks
        for i in range(5):
            stack = domain_grid[i]
            for j in range(3):
                if j == 2:
                    domain = domain_stack.pop()
                    domain.toggle_visibility(True)
                    domain.toggle_accessibility(True)
                    stack.append(domain)
                else:
                    domain = domain_stack.pop()
                    stack.append(domain)

        game_state = {
            "game_id": game_id,
            "pending_required_choice": None,
            "player_list": player_list,
            "monster_grid": monster_grid,
            "monster_stack_areas": monster_stack_areas,
            "citizen_grid": citizen_grid,
            "domain_grid": domain_grid,
            "die_one": die_one,
            "die_two": die_two,
            "die_sum": die_sum,
            "roll_events": [],
            "exhausted_count": exhausted_count,
            "exhausted_stack": exhausted_stack,
            "discard_pile": [],
            "pending_payout_continuation": None,
            "end_game_triggered": False,
            "final_scores": None,
            "final_result": None,
            "effects": effects,
            "action_required": action_required,
            "concurrent_action": None,
            "tick_id": tick_id,
            "turn_number": turn_number,
            "turn_index": turn_index,
            "phase": phase,
            "actions_remaining": actions_remaining,
            "harvest_processed": harvest_processed,
            "pending_harvest_choices": pending_harvest_choices,
            "harvest_player_order": None,
            "harvest_player_idx": 0,
            "harvest_consumed": {},
            "game_log": [],
            "pending_action_end_queue": [],
        }
        return game_state
