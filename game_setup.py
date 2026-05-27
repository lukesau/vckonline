import random
from typing import List

from banned_cards import banned_domain_ids, banned_duke_ids
from card_filters import keep_for_random
from cards import Citizen, Domain, Duke, Event, Exhausted, Monster, Starter
from game_models import Player

# Domain IDs granted (one extra copy per player) when the lobby's
# "Debug mode" toggle is on. These are all base-set
# roll.set_one_die domains, picked so a debug player can deterministically
# steer either die without needing to luck into the cards in the random deal:
#   1  Foxgrove Palisade   roll.set_one_die target=6 cost=g:2
#   2  The Desert Orchid   roll.set_one_die target=1 cost=g_per_owned_role:holy_citizen
#   19 Palace of the Dawn  roll.set_one_die subtract=1   (free; cost spec omitted)
# These same IDs are ALSO filtered out of the random board deal so no player
# can purchase a second copy on top of the debug grant (see `load_game_data`).
# Granting them onto a player's tableau is still "illegal" w.r.t. the printed
# game, but reuses the existing `_apply_roll_modification` / finalize_roll UI
# path so no engine or client changes are needed -- the prod game page renders
# them as modifier buttons automatically.
DEBUG_ROLL_MODIFIER_DOMAIN_IDS = (1, 2, 19)

# In debug mode `Game.roll_phase` does NOT call `random.randint(1, 6)` for the
# dice. It picks each die out of these constrained value sets instead. The
# split (die one in {2, 3}, die two in {4, 5}) is chosen so the three debug
# roll-modifier domains above between them can reach every value 1..6 on at
# least one die per roll:
#   2 or 3        -> kept as-is, or  -> 1 (Desert Orchid)  / 6 (Foxgrove) / 1..2 (Palace -1)
#   4 or 5        -> kept as-is, or  -> 1 (Desert Orchid)  / 6 (Foxgrove) / 3..4 (Palace -1)
# Side effect: because the two natural-roll value sets are disjoint, the
# `doubles` roll_event is never emitted in debug mode (see
# `_compute_roll_events`), so `roll.on_event doubles ...` passives are
# unreachable from a debug game. Final-dice doubles (e.g. (3,3) finalised
# from a natural (3,4) via Palace's -1 on die two) DO still match the
# starter `activation_trigger doubles` leg, which reads `self.die_one ==
# self.die_two` on the FINAL dice. See `docs/game.md` for the full
# reachability table.
DEBUG_DIE_ONE_VALUES = (2, 3)
DEBUG_DIE_TWO_VALUES = (4, 5)


def _choose_one_citizen_per_roll(rows):
    rows_by_roll = {}
    for row in rows:
        rows_by_roll.setdefault(int(row["roll_match1"]), []).append(row)
    return [random.choice(rows_by_roll[roll]) for roll in sorted(rows_by_roll)]


def _filter_monster_areas_for_random(rows, n_players):
    """Drop every monster area where any playable card fails keep_for_random.

    A monster stack is dealt as a unit: the entire ordered stack lands in
    one of the five board slots, so a single unimplemented or imageless
    card in the stack would block normal play of that area. For the
    `random` preset we therefore validate at the area level, not the row
    level — keep an area only if every card that would actually be in
    the dealt stack passes `card_filters.keep_for_random`.

    `is_extra` cards are only included at 5-player counts, so they only
    constrain the area's eligibility at 5 players. At 2-4 players an
    unimplemented `is_extra` is harmless and shouldn't disqualify the
    area; the dealer drops it anyway.
    """
    include_extra = n_players == 5
    rows_by_area = {}
    for r in rows:
        if not include_extra and bool(r.get("is_extra")):
            continue
        rows_by_area.setdefault(r["area"], []).append(r)
    valid = {
        area: arows
        for area, arows in rows_by_area.items()
        if all(keep_for_random("monster", r) for r in arows)
    }
    return [r for arows in valid.values() for r in arows]


# 10 board citizen stacks, one per dice trigger: 1, 2, 3, 4, 5, 6, 7, 8,
# 9-10 (roll_match1=9), 11-12 (roll_match1=11). Every preset's citizen
# pool must cover all of these or the engine will try to access an empty
# stack at deal time.
_EXPECTED_CITIZEN_ROLLS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 11)


def _validate_citizen_rolls(rows, citizen_query):
    present = {int(r["roll_match1"]) for r in rows}
    missing = set(_EXPECTED_CITIZEN_ROLLS) - present
    unexpected = present - set(_EXPECTED_CITIZEN_ROLLS)
    if missing or unexpected:
        parts = []
        if missing:
            parts.append(f"no eligible citizen for roll_match1 {sorted(missing)}")
        if unexpected:
            parts.append(f"unexpected roll_match1 values {sorted(unexpected)}")
        raise ValueError(
            f"Citizen pool from {citizen_query} is incomplete: {'; '.join(parts)}."
        )


def load_draft_card_pool(n_players: int):
    """Load the full card pool for draft mode (same pool as random preset).

    Returns:
        monsters_by_area: dict mapping area name -> list of raw DB rows, sorted
            by monster_order ascending (index 0 is the front/accessible card).
        citizens_by_roll: dict mapping roll_match1 -> list of raw DB rows.
    """
    import mariadb

    monsters_by_area = {}
    citizens_by_roll = {}

    conn = mariadb.connect(
        user="vckonline", password="vckonline", host="127.0.0.1", database="vckonline", port=3306
    )
    cursor = conn.cursor(dictionary=True)

    cursor.callproc("select_all_monsters")
    monster_rows = cursor.fetchall()
    filtered = _filter_monster_areas_for_random(monster_rows, n_players)
    for row in filtered:
        area = row["area"]
        monsters_by_area.setdefault(area, []).append(dict(row))
    for area in monsters_by_area:
        monsters_by_area[area].sort(key=lambda r: int(r.get("monster_order", 0)))

    cursor.callproc("select_all_citizens")
    citizen_rows = cursor.fetchall()
    for row in citizen_rows:
        if keep_for_random("citizen", row) and not int(row.get("special_citizen") or 0):
            roll = int(row["roll_match1"])
            citizens_by_roll.setdefault(roll, []).append(dict(row))

    cursor.close()
    conn.close()
    return monsters_by_area, citizens_by_roll


def load_game_data(game_id, preset, player_list_from_lobby, debug_mode=False, draft_selections=None):
    import mariadb

    monster_query = ""
    monster_stack = []
    citizen_query = ""
    choose_one_citizen_per_roll = False
    citizen_stack = []
    domain_query = "select_random_domains"
    domain_stack = []
    duke_query = "select_random_dukes"
    duke_stack = []
    event_query = "select_base_events"
    # Apply card_filters.keep_for_random (implemented AND has image) to every
    # raw row pool below. Off for the curated presets so a one-off missing
    # image or stub effect doesn't silently shrink Test 1/etc.
    apply_implemented_image_filter = False
    # exhausted_stack is built after DB queries (see below); placeholder here.
    exhausted_stack = []
    starter_query = "SELECT * FROM starters ORDER BY id_starters"
    starter_stack = []
    player_list = []
    citizen_grid: List[List[Citizen]] = [[] for _ in range(10)]
    domain_grid: List[List[Domain]] = [[] for _ in range(5)]
    monster_grid: List[List[Monster]] = [[] for _ in range(5)]
    # Raw rows for the roll-modifier domains the debug start hands out. Populated
    # while the DB cursor is open and consumed after player objects are built.
    debug_roll_modifier_domain_rows: list = []
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
        case "base" | "current":
            monster_query = "select_base_monsters"
            citizen_query = "select_base_citizens"
            choose_one_citizen_per_roll = True
            domain_query = "select_base_domains"
            duke_query = "select_base_dukes"
            event_query = "select_base_events"
        case "base1":
            monster_query = "select_base1_monsters"
            citizen_query = "select_base1_citizens"
            domain_query = "select_random_domains"
            event_query = "select_base_events"
        case "base2":
            monster_query = "select_base2_monsters"
            citizen_query = "select_base2_citizens"
            domain_query = "select_random_domains"
            event_query = "select_base_events"
        case "test1":
            monster_query = "select_base1_monsters"
            citizen_query = "select_base1_citizens"
            domain_query = "select_test1_domains"
            event_query = "select_base_events"
        case "test2":
            monster_query = "select_base2_monsters"
            citizen_query = "select_base2_citizens"
            domain_query = "select_test2_domains"
            event_query = "select_base_events"
        case "random":
            # Pull every card (every expansion) and let
            # card_filters.keep_for_random + the existing
            # _choose_one_citizen_per_roll / area-of-5 / sample-15 /
            # banned-cards filters narrow the pool down to a deal.
            monster_query = "select_all_monsters"
            citizen_query = "select_all_citizens"
            choose_one_citizen_per_roll = True
            domain_query = "select_random_domains"
            duke_query = "select_random_dukes"
            event_query = "select_all_events"
            apply_implemented_image_filter = True
        case "draft":
            # Same pool as random, but monsters/citizens are pre-selected by
            # the lobby draft phase and passed in via draft_selections.
            # Domains, dukes, and events are still randomised like random.
            monster_query = "select_all_monsters"
            citizen_query = "select_all_citizens"
            choose_one_citizen_per_roll = False  # selections are pre-determined
            domain_query = "select_random_domains"
            duke_query = "select_random_dukes"
            event_query = "select_all_events"
            apply_implemented_image_filter = True
        case _:
            raise ValueError(f"Unknown game data preset: {preset}")

    # Debug mode filters roll-modifier domain IDs out of the board deal because
    # it duplicates those cards onto every player's tableau. The test presets
    # have narrow domain pools that overlap those IDs, so widen only those pools
    # before applying the filter.
    if debug_mode and domain_query in ("select_test1_domains", "select_test2_domains"):
        domain_query = "select_random_domains"
    try:
        my_connect = mariadb.connect(
            user="vckonline", password="vckonline", host="127.0.0.1", database="vckonline", port=3306
        )
        my_cursor = my_connect.cursor(dictionary=True)

        my_cursor.callproc(monster_query)

        results = my_cursor.fetchall()
        if apply_implemented_image_filter:
            results = _filter_monster_areas_for_random(results, len(player_list_from_lobby))
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
        if apply_implemented_image_filter:
            results = [r for r in results if keep_for_random("citizen", r) and not int(r.get("special_citizen") or 0)]
        if draft_selections and preset == "draft":
            selected_ids = {int(v) for v in draft_selections.get("citizens", {}).values()}
            results = [r for r in results if int(r["id_citizens"]) in selected_ids]
        elif choose_one_citizen_per_roll:
            results = _choose_one_citizen_per_roll(results)
        _validate_citizen_rolls(results, citizen_query)
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
                    row["vp_payout_on_turn"],
                    row["vp_payout_off_turn"],
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
        if apply_implemented_image_filter:
            results = [r for r in results if keep_for_random("domain", r)]
        skip_domains = set(banned_domain_ids())
        # Debug mode duplicates these onto every player's tableau, so also
        # filter them out of the random board deal -- no one can purchase a
        # second copy that way.
        if debug_mode:
            skip_domains |= set(DEBUG_ROLL_MODIFIER_DOMAIN_IDS)
        if skip_domains:
            results = [r for r in results if int(r["id_domains"]) not in skip_domains]
        domains_needed = 15  # 5 stacks x 3 cards
        if len(results) < domains_needed:
            hints = []
            if banned_domain_ids():
                hints.append('remove ids from "domains" in banned_cards.json to unban')
            if debug_mode:
                hints.append("disable Debug mode, or widen the procedure's domain pool")
            hint = " (" + "; ".join(hints) + ")" if hints else ""
            raise ValueError(
                f"Not enough domains after filtering "
                f"(need {domains_needed}, have {len(results)} from {domain_query}){hint}."
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
                row["effect_text"],
                row["expansion"],
            )
            domain_stack.append(my_domain)

        # Debug-only side fetch: pull the roll-modifier domain rows so each
        # player can be handed an extra copy after player setup. Safe to
        # int()-cast and string-interp because the IDs are a module constant.
        if debug_mode and DEBUG_ROLL_MODIFIER_DOMAIN_IDS:
            ids_csv = ",".join(str(int(i)) for i in DEBUG_ROLL_MODIFIER_DOMAIN_IDS)
            my_cursor.execute(
                f"SELECT * FROM domains WHERE id_domains IN ({ids_csv})"
            )
            debug_roll_modifier_domain_rows = list(my_cursor.fetchall() or [])

        my_cursor.callproc(duke_query)
        results = my_cursor.fetchall()
        if apply_implemented_image_filter:
            results = [r for r in results if keep_for_random("duke", r)]
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
        # Load events and build the exhausted_stack. Each preset names
        # its source procedure in `event_query` (see the match block
        # above) so adding a new event pool is "add a thin SP + a case
        # branch" — same shape as monsters/citizens/domains/dukes.
        my_cursor.callproc(event_query)
        event_rows = my_cursor.fetchall()
        if apply_implemented_image_filter:
            event_rows = [r for r in event_rows if keep_for_random("event", r)]
        event_pool = []
        for row in event_rows:
            ev = Event(
                event_id=row["id_events"],
                name=row["name"],
                roll_match1=row["roll_match1"],
                roll_effect=row.get("roll_effect"),
                has_roll_effect=row.get("has_roll_effect", 0),
                is_monster=row.get("is_monster", 0),
                has_activation_effect=row.get("has_activation_effect", 0),
                has_passive_effect=row.get("has_passive_effect", 0),
                activation_effect=row.get("activation_effect"),
                passive_effect=row.get("passive_effect"),
                strength_cost=row.get("strength_cost", 0),
                magic_cost=row.get("magic_cost", 0),
                monster_type=row.get("monster_type"),
                vp_reward=row.get("vp_reward", 0),
                gold_reward=row.get("gold_reward", 0),
                strength_reward=row.get("strength_reward", 0),
                magic_reward=row.get("magic_reward", 0),
                has_special_reward=row.get("has_special_reward", 0),
                special_reward=row.get("special_reward"),
                expansion=row.get("expansion"),
            )
            event_pool.append(ev)

        n_players = len(player_list_from_lobby)
        total_tokens = n_players * 2
        n_events = n_players  # half the pool becomes Event cards

        if len(event_pool) >= n_events:
            chosen_events = random.sample(event_pool, n_events)
        else:
            print(
                f"Warning: only {len(event_pool)} events available from {event_query} "
                f"but need {n_events}. Filling remainder with plain Exhausted tokens."
            )
            chosen_events = list(event_pool)

        n_exhausted = total_tokens - len(chosen_events)
        plain_exhausted = [Exhausted(i) for i in range(n_exhausted)]
        exhausted_stack = chosen_events + plain_exhausted
        random.shuffle(exhausted_stack)

        my_cursor.close()
        my_connect.close()
    except Exception as e:
        print(f"Error: {e}")
        # Fallback: plain exhausted tokens if DB load failed
        if not exhausted_stack:
            exhausted_stack = [Exhausted(i) for i in range(len(player_list_from_lobby) * 2)]
    # create players and determine order
    if not all([player_list_from_lobby, starter_query, monster_stack, citizen_stack, domain_stack, duke_stack]):
        raise ValueError("One or more required lists are empty.")
    else:
        for player in player_list_from_lobby:
            my_player = Player(player.player_id, player.name)
            if debug_mode:
                my_player.gold_score = 100
                my_player.strength_score = 100
                my_player.magic_score = 100
            player_list.append(my_player)
        random.shuffle(player_list)
        player_list[0].is_first = True
        # give players starters and dukes. Every player gets one of every
        # starter; the stack is a shared template (instances aren't mutated
        # per-player).
        for player in player_list:
            for starter in starter_stack:
                player.owned_starters.append(starter)
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
        if len(areas) < 5:
            raise ValueError(
                f"Not enough monster areas after filtering "
                f"(need 5, have {len(areas)} from {monster_query}). "
                "If using the random preset, add card art or finish stub "
                "specials so more areas have all-playable stacks."
            )
        if draft_selections and preset == "draft":
            chosen_areas = list(draft_selections.get("monster_areas", []))
            if len(chosen_areas) != 5:
                raise ValueError("Draft selections must specify exactly 5 monster areas.")
            missing = [a for a in chosen_areas if a not in grouped_monsters]
            if missing:
                raise ValueError(f"Draft-selected areas not in available monster pool: {missing}")
        else:
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
        if debug_mode:
            for player in player_list:
                for stack in citizen_grid:
                    c = stack.pop(-1)
                    c.is_flipped = False
                    c.toggle_visibility(True)
                    c.toggle_accessibility(True)
                    player.owned_citizens.append(c)
                    if stack:
                        stack[-1].toggle_accessibility(True)
                # Grant a fresh copy of each roll-modifier domain. New instance per
                # player so per-card state (acquired_turn_number, visibility, etc.)
                # is independent across tableaus.
                for row in debug_roll_modifier_domain_rows:
                    d = Domain(
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
                        row["effect_text"],
                        row["expansion"],
                    )
                    d.toggle_visibility(True)
                    d.toggle_accessibility(True)
                    player.owned_domains.append(d)
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
            "debug_mode": bool(debug_mode),
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
            "banish_pile": [],
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
            "pending_event_slay_cost": None,
        }
        return game_state
