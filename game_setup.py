import random
from typing import List

from banned_cards import banned_domain_ids, banned_duke_ids
from card_filters import is_unimplemented_event, keep_for_random
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

# Recruit the King's Guard (event 10): the only event that introduces a brand-new
# citizen stack. When that event is in the deck we set aside the King's Guard
# citizens (citizens row with expansion = "kingsguard" AND special_citizen = 1)
# so the event can drop them onto the board on reveal. See engines/events.py.
KINGS_GUARD_EVENT_ACTIVATION = "place_kings_guard"
KINGS_GUARD_EXPANSION = "kingsguard"

# Starters split into two groups by roll_match:
#   - "core" starters (Peasant/Knight, real roll numbers) are mandatory: every
#     player always gets all of them.
#   - the "optional" starter (roll_match -1/-1, e.g. Herald/Margrave/Coxswain)
#     fires on doubles or a no-payout roll. At most one is granted per game, and
#     it is chosen by the preset's configured expansion. If no matching -1/-1
#     starter exists in the pool, none is dealt and the game simply plays
#     without a doubles/no-payout trigger.

# "June 2026" rotating preset: a hand-picked board. The monster areas and
# citizen ids are fixed (drawn from the full cross-expansion pool); domains,
# dukes, and events are randomized like the other presets (Crimson Seas
# domains still excluded). The `current` preset ("Rotating" in the
# lobby) is an alias of whichever dated rotating preset is live — currently
# this one. `june2026` itself is intentionally not offered as a separate
# lobby dropdown option; players reach it through the rotating alias.
JUNE_2026_MONSTER_AREAS = ("Barrens", "Gloom Gyre", "Forest", "Skerry", "Fire Temple")
JUNE_2026_CITIZEN_IDS = (19, 2, 41, 14, 33, 34, 35, 36, 9, 48)


def _is_optional_starter_row(row):
    try:
        return int(row.get("roll_match1", 0)) == -1 and int(row.get("roll_match2", 0)) == -1
    except (TypeError, ValueError):
        return False


def _is_optional_starter(card):
    try:
        return int(getattr(card, "roll_match1", 0)) == -1 and int(getattr(card, "roll_match2", 0)) == -1
    except (TypeError, ValueError):
        return False


def _choose_optional_starter(candidates, preset, optional_starter_expansion, draft_selections=None):
    """Pick the optional -1/-1 doubles-or-no-payout starter, or None.

    The optional starter is not mandatory: at most one is granted per game and
    it is selected by the preset's configured expansion. Returns None when no
    suitable -1/-1 starter exists, in which case the game plays without any
    doubles/no-payout trigger. (Herald is no longer a universal fallback — it is
    simply the base-set optional starter.)
    """
    if not candidates:
        return None

    by_id = {int(s.starter_id): s for s in candidates}

    if preset == "draft":
        sel = (draft_selections or {}).get("starter_id")
        return by_id.get(int(sel)) if sel is not None else None
    if preset == "random":
        return random.choice(candidates)
    if optional_starter_expansion:
        target = optional_starter_expansion.strip().lower()
        for s in candidates:
            if (getattr(s, "expansion", "") or "").strip().lower() == target:
                return s
    return None


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


def _sort_monster_areas_by_top_card_cost(chosen_areas, grouped_monsters):
    """Order chosen monster areas by top-card total cost (strength + magic)."""

    def _area_top_cost(area):
        stack = list(grouped_monsters.get(area) or [])
        if not stack:
            return 9999
        # Compare the face-up board top of the stack.
        top = stack[-1]
        strength = int(getattr(top, "strength_cost", 0) or 0)
        magic = int(getattr(top, "magic_cost", 0) or 0)
        return strength + magic

    return sorted(list(chosen_areas or []), key=_area_top_cost)


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
        starter_candidates: list of raw DB rows for the optional -1/-1 starter.
    """
    import mariadb

    monsters_by_area = {}
    citizens_by_roll = {}
    starter_candidates = []

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

    cursor.execute(
        "SELECT * FROM starters WHERE roll_match1 = -1 AND roll_match2 = -1 ORDER BY id_starters"
    )
    for row in cursor.fetchall():
        if keep_for_random("starter", row):
            starter_candidates.append(dict(row))

    cursor.close()
    conn.close()
    return monsters_by_area, citizens_by_roll, starter_candidates


def load_game_data(
    game_id,
    preset,
    player_list_from_lobby,
    debug_mode=False,
    draft_selections=None,
    expansion_only=False,
    duke_select_count=2,
):
    import mariadb

    duke_select_count = int(duke_select_count or 2)
    if duke_select_count not in (2, 3):
        raise ValueError(f"duke_select_count must be 2 or 3, got {duke_select_count}")

    monster_query = ""
    monster_stack = []
    citizen_query = ""
    choose_one_citizen_per_roll = False
    citizen_stack = []
    domain_query = "select_random_domains"
    domain_stack = []
    duke_query = "select_random_dukes"
    duke_stack = []
    # Events default to the full cross-expansion pool (including Crimson Seas)
    # for every preset. The expansion_only lobby option narrows them to the
    # preset's own expansion below.
    event_query = "select_all_events"
    monster_expansion_filters = None
    citizen_expansion_filters = None
    domain_expansion_filters = None
    duke_expansion_filters = None
    event_expansion_filters = None
    # Expansions whose domains must be dropped from the deal. Used by every
    # preset that pulls the full cross-expansion pool via select_random_domains
    # (base/base1/base2/flamesandfrost/shadowvale/random/draft): Crimson Seas domains
    # aren't implemented yet, so exclude them here until they ship rather than
    # letting them leak in.
    exclude_domain_expansions = ()
    # Preset-baked fixed selections (parallel to draft_selections but hard-coded
    # in the preset definition). When set, the citizen pool is narrowed to these
    # ids and the board is dealt exactly these 5 monster areas.
    fixed_citizen_ids = None
    fixed_monster_areas = None
    # Expansion whose -1/-1 doubles-or-no-payout starter every player gets this
    # game (Herald=base, Margrave=margraves, Coxswain=crimsonseas). None, or an
    # expansion with no matching -1/-1 starter, means no optional starter is
    # dealt and the game plays without a doubles/no-payout trigger. random/draft
    # presets ignore this (they pick randomly / from the draft selection).
    optional_starter_expansion = None
    # Apply card_filters.keep_for_random (implemented AND has image) to every
    # raw row pool below. Off for the curated presets so a one-off missing
    # image or stub effect doesn't silently shrink those pools.
    apply_implemented_image_filter = False
    # exhausted_stack is built after the monster areas are chosen (see below) so
    # the Undead Samurai Lord event can be blacklisted when the Undead Samurai
    # monster stack is already dealt to the board. `event_pool` is the materialized
    # Event objects (loaded while the DB cursor is open); `undead_samurai_reserve`
    # holds the set-aside minions (monsters 57-61) that the Lord event scatters.
    exhausted_stack = []
    event_pool = []
    undead_samurai_reserve = []
    # Undead Samurai Lord event state: the minions still waiting to be placed,
    # and whether the one-time "each player places a minion" step has run.
    undead_samurai_pool = []
    undead_samurai_placed = False
    # Set-aside King's Guard citizens. `kings_guard_reserve` is the raw DB row(s)
    # loaded while the cursor is open; `kings_guard_pool` is the materialized
    # stack of Citizen objects, only armed if the Recruit the King's Guard event
    # ends up in the deck (see the deck build after monster-area selection).
    kings_guard_reserve = []
    kings_guard_pool = []
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
        case "base":
            monster_query = "select_base_monsters"
            citizen_query = "select_base_citizens"
            choose_one_citizen_per_roll = True
            domain_query = "select_random_domains"
            exclude_domain_expansions = ("crimsonseas",)
            duke_query = "select_random_dukes"
            optional_starter_expansion = "base"
        case "june2026" | "current":
            # Rotating preset (current = "Rotating", aliased to the
            # live dated preset). Fixed monster areas + citizens; domains,
            # dukes, and events randomized across all expansions (no Crimson
            # Seas domains). Pulled from the full pool so the curated areas
            # and citizen ids can span expansions.
            monster_query = "select_all_monsters"
            citizen_query = "select_all_citizens"
            choose_one_citizen_per_roll = False
            domain_query = "select_random_domains"
            duke_query = "select_random_dukes"
            exclude_domain_expansions = ("crimsonseas",)
            fixed_monster_areas = JUNE_2026_MONSTER_AREAS
            fixed_citizen_ids = JUNE_2026_CITIZEN_IDS
            # June 2026 hands out the Margraves -1/-1 starter (Margrave).
            optional_starter_expansion = "margraves"
        case "base1":
            monster_query = "select_base1_monsters"
            citizen_query = "select_base1_citizens"
            domain_query = "select_random_domains"
            exclude_domain_expansions = ("crimsonseas",)
            optional_starter_expansion = "base"
        case "base2":
            monster_query = "select_base2_monsters"
            citizen_query = "select_base2_citizens"
            domain_query = "select_random_domains"
            exclude_domain_expansions = ("crimsonseas",)
            optional_starter_expansion = "base"
        case "flamesandfrost":
            # Preset rules:
            # - starters: core Peasant/Knight plus the base -1/-1 starter (Herald);
            #   Flames & Frost has no dedicated -1/-1 starter of its own.
            # - dukes: every duke (random across all expansions; default query)
            # - monsters/citizens: expansion = "flamesandfrost"
            # - domains: every expansion except Crimson Seas (random pool)
            # - events: every expansion (default all-events pool)
            monster_expansion_filters = ("flamesandfrost",)
            citizen_expansion_filters = ("flamesandfrost",)
            exclude_domain_expansions = ("crimsonseas",)
            choose_one_citizen_per_roll = True
            optional_starter_expansion = "base"
        case "shadowvale":
            # Preset rules:
            # - starters: core Peasant/Knight plus the base -1/-1 starter (Herald);
            #   Shadowvale has no dedicated -1/-1 starter of its own.
            # - dukes: every duke (random across all expansions; default query)
            # - monsters/citizens: expansion = "shadowvale"
            # - domains: every expansion except Crimson Seas (random pool)
            # - events: every expansion (default all-events pool)
            monster_expansion_filters = ("shadowvale",)
            citizen_expansion_filters = ("shadowvale",)
            exclude_domain_expansions = ("crimsonseas",)
            choose_one_citizen_per_roll = True
            optional_starter_expansion = "base"
        case "crimsonseas":
            # Crimson Seas expansion preset:
            # - monsters/citizens: expansion = "crimsonseas"
            # - domains: expansion in ("crimsonseas", "base")
            # - dukes: all dukes (random across every expansion; default query)
            # - events: every expansion (default all-events pool)
            # - starters: core Peasant/Knight plus the Crimson Seas -1/-1 starter
            #   (Coxswain; see `_choose_optional_starter`). The default starter
            #   query already loads all starters. If Crimson Seas has no -1/-1
            #   starter in the pool yet, the game plays without one.
            # Banned cards are still filtered by the shared domain/duke deal.
            monster_expansion_filters = ("crimsonseas",)
            citizen_expansion_filters = ("crimsonseas",)
            domain_expansion_filters = ("crimsonseas", "base")
            duke_query = "select_random_dukes"
            choose_one_citizen_per_roll = True
            optional_starter_expansion = "crimsonseas"
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
            exclude_domain_expansions = ("crimsonseas",)
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
            exclude_domain_expansions = ("crimsonseas",)
        case _:
            raise ValueError(f"Unknown game data preset: {preset}")
    # Lobby option: restrict domains/dukes/events to the preset's expansion set
    # (plus base dukes for expansion presets that don't have enough dukes
    # alone). Default (off) draws domains/dukes/events from the full pool.
    if expansion_only:
        if preset == "base":
            domain_query = "select_base_domains"
            domain_expansion_filters = None
            exclude_domain_expansions = ()
            duke_expansion_filters = ("base",)
            event_expansion_filters = ("base",)
        elif preset == "flamesandfrost":
            domain_expansion_filters = ("flamesandfrost",)
            exclude_domain_expansions = ()
            duke_expansion_filters = ("base", "flamesandfrost")
            event_expansion_filters = ("flamesandfrost",)
        elif preset == "shadowvale":
            domain_expansion_filters = ("shadowvale",)
            exclude_domain_expansions = ()
            duke_expansion_filters = ("base", "shadowvale")
            event_expansion_filters = ("shadowvale",)
    try:
        my_connect = mariadb.connect(
            user="vckonline", password="vckonline", host="127.0.0.1", database="vckonline", port=3306
        )
        my_cursor = my_connect.cursor(dictionary=True)

        def _fetch_pool_rows(proc_name, table_name, expansion_filters):
            if expansion_filters:
                placeholders = ", ".join(["%s"] * len(expansion_filters))
                my_cursor.execute(
                    f"SELECT * FROM {table_name} WHERE expansion IN ({placeholders})",
                    tuple(expansion_filters),
                )
            else:
                my_cursor.callproc(proc_name)
            return my_cursor.fetchall()

        results = _fetch_pool_rows(monster_query, "monsters", monster_expansion_filters)
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

        citizen_count = 5
        if len(player_list_from_lobby) == 5:
            citizen_count = 6
        results = _fetch_pool_rows(citizen_query, "citizens", citizen_expansion_filters)
        if apply_implemented_image_filter:
            results = [r for r in results if keep_for_random("citizen", r) and not int(r.get("special_citizen") or 0)]
        if draft_selections and preset == "draft":
            selected_ids = {int(v) for v in draft_selections.get("citizens", {}).values()}
            results = [r for r in results if int(r["id_citizens"]) in selected_ids]
        elif fixed_citizen_ids:
            wanted = {int(i) for i in fixed_citizen_ids}
            results = [r for r in results if int(r["id_citizens"]) in wanted]
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

        results = _fetch_pool_rows(domain_query, "domains", domain_expansion_filters)
        # Expansion-filtered presets (shadowvale, flamesandfrost) take the inline
        # SELECT branch in _fetch_pool_rows, which has no ORDER BY RAND(); rows
        # come back in PK order. The duke/domain deal pops from the end of the
        # list, so without a Python-side shuffle the highest-id (= expansion-set)
        # cards always pop first. Shuffling here makes the pool order random
        # regardless of fetch source, and is a no-op for the named-proc branch
        # which is already ORDER BY RAND().
        random.shuffle(results)
        # Drop domains from excluded expansions (e.g. Crimson Seas, which has
        # no implemented domains yet) before the deal. Set by the presets that
        # draw the full pool via select_random_domains.
        if exclude_domain_expansions:
            excluded = set(exclude_domain_expansions)
            results = [r for r in results if (r.get("expansion") or "") not in excluded]
        skip_domains = set(banned_domain_ids())
        # Debug mode duplicates these onto every player's tableau, so also
        # filter them out of the random board deal -- no one can purchase a
        # second copy that way.
        if debug_mode:
            skip_domains |= set(DEBUG_ROLL_MODIFIER_DOMAIN_IDS)
        if skip_domains:
            results = [r for r in results if int(r["id_domains"]) not in skip_domains]
        # Standard board is 5 stacks of 3 (15 domains). At 5 players each
        # stack is dealt 4 deep (3 hidden + 1 face-up top), so the pool needs
        # 20 valid domains.
        domain_stack_depth = 4 if len(player_list_from_lobby) == 5 else 3
        domains_needed = 5 * domain_stack_depth
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

        results = _fetch_pool_rows(duke_query, "dukes", duke_expansion_filters)
        # See the matching comment above the domains shuffle: the inline
        # SELECT branch is not random, and players pop dukes off the end,
        # so without this shuffle expansion-filtered presets always hand
        # the highest-id (= expansion-set) dukes to the first players.
        random.shuffle(results)
        skip_dukes = banned_duke_ids()
        if skip_dukes:
            results = [r for r in results if int(r["id_dukes"]) not in skip_dukes]
        dukes_needed = duke_select_count * len(player_list_from_lobby)
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
        # Load events and build the exhausted_stack. Every preset now draws
        # events from the full cross-expansion pool (select_all_events) unless
        # the expansion_only option narrowed event_expansion_filters above.
        event_rows = _fetch_pool_rows(event_query, "events", event_expansion_filters)
        if apply_implemented_image_filter:
            # random/draft: drop unimplemented AND imageless rows.
            event_rows = [r for r in event_rows if keep_for_random("event", r)]
        else:
            # Curated presets pull the full event pool too, so guard against
            # dealing a stub event the engine can't resolve. Image presence is
            # not required here the way it is for random/draft.
            event_rows = [r for r in event_rows if not is_unimplemented_event(r)]
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

        # Set-aside Undead Samurai minions (monsters 57-61). These are NOT dealt
        # as a normal monster area; the Undead Samurai Lord event scatters them
        # onto the board when revealed. Loaded here while the cursor is open and
        # only attached to the game if that event ends up in the deck (see the
        # deck build after monster-area selection). `_filter_monster_areas_for_random`
        # is intentionally not applied — these enter via the event, not as an area.
        try:
            my_cursor.execute(
                "SELECT * FROM monsters WHERE area = %s AND monster_type = %s "
                "ORDER BY monster_order",
                ("Undead Samurai", "Minion"),
            )
            for row in my_cursor.fetchall():
                undead_samurai_reserve.append(Monster(
                    row["id_monsters"], row["name"], row["area"], row["monster_type"],
                    row["monster_order"], row["strength_cost"], row["magic_cost"],
                    row["vp_reward"], row["gold_reward"], row["strength_reward"],
                    row["magic_reward"], row["has_special_reward"], row["special_reward"],
                    row["has_special_cost"], row["special_cost"], row["is_extra"],
                    row["expansion"],
                ))
        except Exception:
            undead_samurai_reserve = []

        # Set-aside King's Guard citizen row(s). Loaded while the cursor is open;
        # only materialized into a stack if the Recruit the King's Guard event is
        # dealt to the deck. There must be exactly one such citizen (validated at
        # arm time so non-kingsguard games never trip the check).
        try:
            my_cursor.execute(
                "SELECT * FROM citizens WHERE expansion = %s AND special_citizen = 1",
                (KINGS_GUARD_EXPANSION,),
            )
            kings_guard_reserve = [dict(r) for r in (my_cursor.fetchall() or [])]
        except Exception:
            kings_guard_reserve = []

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
        # Core starters (Peasant/Knight, roll_match != -1) are mandatory; the
        # optional -1/-1 doubles-or-no-payout starter is granted only when one
        # matching the preset's expansion exists.
        core_starters = [s for s in starter_stack if not _is_optional_starter(s)]
        optional_candidates = [s for s in starter_stack if _is_optional_starter(s)]
        if preset == "random":
            optional_candidates = [
                s for s in optional_candidates
                if keep_for_random("starter", {
                    "id_starters": s.starter_id,
                    "has_special_payout_on_turn": s.has_special_payout_on_turn,
                    "special_payout_on_turn": s.special_payout_on_turn,
                    "has_special_payout_off_turn": s.has_special_payout_off_turn,
                    "special_payout_off_turn": s.special_payout_off_turn,
                })
            ]
        chosen_optional = _choose_optional_starter(
            optional_candidates, preset, optional_starter_expansion, draft_selections
        )
        # Snapshot the full duke pool for this game's config (post-ban,
        # post-expansion-filter) BEFORE dealing pops cards off the stack. This
        # is the public catalog the client uses to list "every duke and the VP
        # it would score" against a player's tableau. It carries no ownership
        # info, so surfacing it to all players leaks nothing.
        all_dukes = list(duke_stack)
        for player in player_list:
            for starter in core_starters:
                player.owned_starters.append(starter)
            if chosen_optional is not None:
                player.owned_starters.append(chosen_optional)
            for _ in range(duke_select_count):
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
        elif fixed_monster_areas:
            chosen_areas = list(fixed_monster_areas)
            if len(chosen_areas) != 5:
                raise ValueError(
                    f"Preset {preset!r} must specify exactly 5 monster areas, got {len(chosen_areas)}."
                )
            missing = [a for a in chosen_areas if a not in grouped_monsters]
            if missing:
                raise ValueError(
                    f"Preset {preset!r} monster areas not in available pool: {missing}."
                )
        else:
            chosen_areas = random.sample(areas, 5)
        chosen_areas = _sort_monster_areas_by_top_card_cost(chosen_areas, grouped_monsters)
        monster_stack_areas = list(chosen_areas)
        for i, area in enumerate(chosen_areas):
            monsters = grouped_monsters[area]
            monster_grid[i].extend(monsters)
        for stack in monster_grid:
            for monster in stack:
                monster.toggle_visibility(True)
            stack[-1].toggle_accessibility(True)

        # Build the event/exhausted deck now that the monster areas are fixed.
        # The Undead Samurai Lord event and the Undead Samurai monster stack are
        # mutually exclusive (same cards, two different rule sets): if that area
        # was dealt to the board, drop the Lord event so it can't also appear.
        # Doing this after area selection keeps draft/random honest — a player can
        # always pick the Undead Samurai area without the event having pre-claimed it.
        UNDEAD_SAMURAI_AREA = "Undead Samurai"
        UNDEAD_SAMURAI_LORD_EVENT = "Undead Samurai Lord"
        if UNDEAD_SAMURAI_AREA in monster_stack_areas:
            event_pool = [ev for ev in event_pool
                          if getattr(ev, "name", "") != UNDEAD_SAMURAI_LORD_EVENT]

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

        # Arm the Undead Samurai reserve when its Lord event made it into the
        # deck. Registering the area (a 6th entry, with no board column) lets the
        # Lord's `count area "Undead Samurai" v 1` slay reward tally owned minions.
        if any(getattr(ev, "name", "") == UNDEAD_SAMURAI_LORD_EVENT for ev in chosen_events):
            undead_samurai_pool = list(undead_samurai_reserve)
            if UNDEAD_SAMURAI_AREA not in monster_stack_areas:
                monster_stack_areas = list(monster_stack_areas) + [UNDEAD_SAMURAI_AREA]

        # Arm the King's Guard reserve when the Recruit the King's Guard event made
        # it into the deck. The set-aside guards are kept invisible/off-board until
        # the event is revealed (engines/events.py places them on top of the event
        # card). The number of guards mirrors the board citizen stack depth
        # (`citizen_count`: 5 at 2-4 players, 6 at 5 players).
        if any(
            (getattr(ev, "activation_effect", "") or "").strip().lower() == KINGS_GUARD_EVENT_ACTIVATION
            for ev in chosen_events
        ):
            if len(kings_guard_reserve) != 1:
                raise ValueError(
                    "Expected exactly one King's Guard citizen "
                    f"(expansion='{KINGS_GUARD_EXPANSION}', special_citizen=1), "
                    f"found {len(kings_guard_reserve)}."
                )
            kg_row = kings_guard_reserve[0]
            for _ in range(citizen_count):
                kings_guard_pool.append(Citizen(
                    kg_row["id_citizens"],
                    kg_row["name"],
                    kg_row["gold_cost"],
                    kg_row["roll_match1"],
                    kg_row["roll_match2"],
                    kg_row["shadow_count"],
                    kg_row["holy_count"],
                    kg_row["soldier_count"],
                    kg_row["worker_count"],
                    kg_row["gold_payout_on_turn"],
                    kg_row["gold_payout_off_turn"],
                    kg_row["strength_payout_on_turn"],
                    kg_row["strength_payout_off_turn"],
                    kg_row["magic_payout_on_turn"],
                    kg_row["magic_payout_off_turn"],
                    kg_row["vp_payout_on_turn"],
                    kg_row["vp_payout_off_turn"],
                    kg_row["has_special_payout_on_turn"],
                    kg_row["has_special_payout_off_turn"],
                    kg_row["special_payout_on_turn"],
                    kg_row["special_payout_off_turn"],
                    kg_row["special_citizen"],
                    kg_row["expansion"],
                ))

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
        # deal the domains into stacks. 5-player games use 4-deep stacks
        # (3 hidden + 1 face-up top); 2-4 players use the standard 3-deep
        # layout. Only the top of each stack starts face-up either way.
        for i in range(5):
            stack = domain_grid[i]
            for j in range(domain_stack_depth):
                domain = domain_stack.pop()
                if j == domain_stack_depth - 1:
                    domain.toggle_visibility(True)
                    domain.toggle_accessibility(True)
                stack.append(domain)

        game_state = {
            "game_id": game_id,
            "debug_mode": bool(debug_mode),
            "preset": preset,
            "pending_required_choice": None,
            "player_list": player_list,
            "all_dukes": all_dukes,
            "monster_grid": monster_grid,
            "monster_stack_areas": monster_stack_areas,
            "undead_samurai_pool": undead_samurai_pool,
            "undead_samurai_placed": undead_samurai_placed,
            "kings_guard_pool": kings_guard_pool,
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
