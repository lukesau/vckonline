"""
Read-only "what cards are in this preset?" preview for the lobby.

The lobby lets the owner pick a board `preset` (see `game_setup.load_game_data`).
Each preset deals a mix of *deterministic* cards (e.g. the Rotating set's fixed
monster areas / citizen ids, every player's core starters) and cards drawn at
random from a larger *candidate pool* (domains, dukes, events, and — for most
presets — the monster areas and citizens too). This module enumerates both so
the client can show a full preview of everything that could land on the board
without actually starting a game.

It deliberately mirrors the pool/filter selection in
`game_setup.load_game_data`. If you change which cards a preset can deal there,
update the `_preset_config` table below to match. The two share the
`card_filters` / `banned_cards` helpers so the implemented/banned rules can't
drift, only the per-preset query+filter wiring is duplicated.

The preview only ever surfaces cards that have art on disk (`has_card_image`),
since the client renders each as an image thumbnail — a pool card with no image
can't be shown and would otherwise render as a broken tile.
"""

import mariadb

from banned_cards import banned_domain_ids, banned_duke_ids
from card_filters import has_card_image, is_unimplemented_event, keep_for_random
from game_setup import (
    JUNE_2026_CITIZEN_IDS,
    JUNE_2026_MONSTER_AREAS,
    _filter_monster_areas_for_random,
    _is_optional_starter_row,
)

# Human-facing names, kept in sync with the lobby dropdown <option> labels.
_PRESET_LABELS = {
    "current": "Rotating Set",
    "june2026": "Rotating Set",
    "base": "Base Set",
    "flamesandfrost": "Flames and Frost",
    "shadowvale": "Shadowvale",
    "crimsonseas": "Crimson Seas",
    "random": "Random (all implemented cards)",
    "draft": "Draft (vote on monsters & citizens)",
}


def _connect():
    return mariadb.connect(
        user="vckonline",
        password="vckonline",
        host="127.0.0.1",
        database="vckonline",
        port=3306,
    )


def _preset_config(preset, expansion_only):
    """Return the pool/filter wiring for `preset` (mirror of game_setup).

    See the module docstring: this duplicates only the per-preset query +
    expansion-filter selection from `game_setup.load_game_data`'s `match`
    block, not the deal itself.
    """
    cfg = {
        "monster_query": "select_all_monsters",
        "monster_expansion_filters": None,
        "citizen_query": "select_all_citizens",
        "citizen_expansion_filters": None,
        "choose_one_citizen_per_roll": False,
        "domain_query": "select_random_domains",
        "domain_expansion_filters": None,
        "exclude_domain_expansions": (),
        "duke_query": "select_random_dukes",
        "duke_expansion_filters": None,
        "event_query": "select_all_events",
        "event_expansion_filters": None,
        "fixed_citizen_ids": None,
        "fixed_monster_areas": None,
        "optional_starter_expansion": None,
        "apply_implemented_image_filter": False,
        # Whether monsters/citizens/optional-starter are picked by the lobby
        # draft vote rather than fixed or randomly dealt.
        "draft": False,
    }

    if preset == "base":
        cfg.update(
            monster_query="select_base_monsters",
            citizen_query="select_base_citizens",
            choose_one_citizen_per_roll=True,
            domain_query="select_base_domains",
            optional_starter_expansion="base",
        )
    elif preset in ("june2026", "current"):
        cfg.update(
            exclude_domain_expansions=("crimsonseas",),
            fixed_monster_areas=JUNE_2026_MONSTER_AREAS,
            fixed_citizen_ids=JUNE_2026_CITIZEN_IDS,
            optional_starter_expansion="margraves",
        )
    elif preset == "flamesandfrost":
        cfg.update(
            monster_expansion_filters=("flamesandfrost",),
            citizen_expansion_filters=("flamesandfrost",),
            exclude_domain_expansions=("crimsonseas",),
            choose_one_citizen_per_roll=True,
            optional_starter_expansion="base",
        )
    elif preset == "shadowvale":
        cfg.update(
            monster_expansion_filters=("shadowvale",),
            citizen_expansion_filters=("shadowvale",),
            exclude_domain_expansions=("crimsonseas",),
            choose_one_citizen_per_roll=True,
            optional_starter_expansion="base",
        )
    elif preset == "crimsonseas":
        cfg.update(
            monster_expansion_filters=("crimsonseas",),
            citizen_expansion_filters=("crimsonseas",),
            domain_expansion_filters=("crimsonseas", "base"),
            choose_one_citizen_per_roll=True,
            optional_starter_expansion="crimsonseas",
        )
    elif preset == "random":
        cfg.update(
            choose_one_citizen_per_roll=True,
            apply_implemented_image_filter=True,
            exclude_domain_expansions=("crimsonseas",),
        )
    elif preset == "draft":
        cfg.update(
            apply_implemented_image_filter=True,
            exclude_domain_expansions=("crimsonseas",),
            draft=True,
        )
    else:
        raise ValueError(f"Unknown preset: {preset}")

    # Lobby "expansion-only" option narrows domains/dukes/events to the
    # preset's own set (matching game_setup).
    if expansion_only:
        if preset == "base":
            cfg["domain_query"] = "select_base_domains"
            cfg["domain_expansion_filters"] = None
            cfg["duke_expansion_filters"] = ("base",)
            cfg["event_expansion_filters"] = ("base",)
        elif preset == "flamesandfrost":
            cfg["domain_expansion_filters"] = ("flamesandfrost",)
            cfg["exclude_domain_expansions"] = ()
            cfg["duke_expansion_filters"] = ("base", "flamesandfrost")
            cfg["event_expansion_filters"] = ("flamesandfrost",)
        elif preset == "shadowvale":
            cfg["domain_expansion_filters"] = ("shadowvale",)
            cfg["exclude_domain_expansions"] = ()
            cfg["duke_expansion_filters"] = ("base", "shadowvale")
            cfg["event_expansion_filters"] = ("shadowvale",)

    return cfg


def _fetch_pool_rows(cur, proc_name, table_name, expansion_filters):
    if expansion_filters:
        placeholders = ", ".join(["%s"] * len(expansion_filters))
        cur.execute(
            f"SELECT * FROM {table_name} WHERE expansion IN ({placeholders})",
            tuple(expansion_filters),
        )
    else:
        cur.callproc(proc_name)
    return cur.fetchall()


def _card(kind, card_id, name, expansion):
    return {
        "kind": kind,
        "id": int(card_id),
        "name": name,
        "expansion": expansion or "",
    }


def _preview_monsters(cur, cfg, players):
    rows = _fetch_pool_rows(cur, cfg["monster_query"], "monsters", cfg["monster_expansion_filters"])
    # The preview always shows the full stack, including the is_extra 7th card
    # that only ships with 5-player games (flagged with a badge client-side).
    # For random/draft we still mirror which AREAS are deal-eligible at this
    # player count, but rebuild the stacks from the unfiltered rows so the
    # is_extra card (which `_filter_monster_areas_for_random` drops below 5
    # players) is still surfaced. Unimplemented/imageless extras are excluded by
    # the per-card keep_for_random check so we never show an undealable card.
    if cfg["apply_implemented_image_filter"]:
        valid_areas = {r["area"] for r in _filter_monster_areas_for_random(rows, players)}
        rows = [r for r in rows if r["area"] in valid_areas and keep_for_random("monster", r)]

    by_area = {}
    for r in rows:
        if not has_card_image("monster", r.get("id_monsters")):
            continue
        by_area.setdefault(r["area"], []).append(r)
    for area in by_area:
        by_area[area].sort(key=lambda r: int(r.get("monster_order", 0)))

    fixed_areas = cfg["fixed_monster_areas"]
    if fixed_areas:
        ordered_areas = [a for a in fixed_areas if a in by_area]
        selection = "fixed"
        note = "These 5 monster areas are always dealt to the board."
    elif cfg["draft"]:
        ordered_areas = sorted(by_area.keys())
        selection = "draft"
        note = "Players vote to pick 5 of these monster areas."
    elif len(by_area) == 5:
        # Expansion presets (flamesandfrost/shadowvale/crimsonseas) filter the
        # monster pool down to exactly 5 areas, so `random.sample(areas, 5)`
        # always returns all of them — the deal is deterministic.
        ordered_areas = sorted(by_area.keys())
        selection = "fixed"
        note = "These 5 monster areas are always dealt to the board."
    else:
        ordered_areas = sorted(by_area.keys())
        selection = "random"
        note = "5 of these monster areas are dealt to the board at random."

    groups = []
    for area in ordered_areas:
        cards = []
        for r in by_area[area]:
            c = _card("monster", r["id_monsters"], r["name"], r.get("expansion"))
            if bool(r.get("is_extra")):
                # 7th-card-in-stack, only dealt in 5-player games.
                c["extra_5p"] = True
            cards.append(c)
        if cards:
            groups.append({"label": area, "cards": cards})

    return {
        "key": "monsters",
        "title": "Monsters",
        "selection": selection,
        "note": note,
        "groups": groups,
    }


def _preview_citizens(cur, cfg, players):
    rows = _fetch_pool_rows(cur, cfg["citizen_query"], "citizens", cfg["citizen_expansion_filters"])
    if cfg["apply_implemented_image_filter"]:
        rows = [
            r for r in rows
            if keep_for_random("citizen", r) and not int(r.get("special_citizen") or 0)
        ]
    rows = [r for r in rows if has_card_image("citizen", r.get("id_citizens"))]

    fixed_ids = cfg["fixed_citizen_ids"]
    if fixed_ids:
        wanted = {int(i) for i in fixed_ids}
        chosen = [r for r in rows if int(r["id_citizens"]) in wanted]
        chosen.sort(key=lambda r: int(r.get("roll_match1", 0)))
        cards = [
            _card("citizen", r["id_citizens"], r["name"], r.get("expansion"))
            for r in chosen
        ]
        return {
            "key": "citizens",
            "title": "Citizens",
            "selection": "fixed",
            "note": "These citizen stacks are always dealt to the board.",
            "cards": cards,
        }

    by_roll = {}
    for r in rows:
        by_roll.setdefault(int(r.get("roll_match1", 0)), []).append(r)

    if cfg["draft"]:
        selection = "draft"
        note = "Players vote on which citizen fills each of the 10 dice slots."
    elif by_roll and all(len(group) == 1 for group in by_roll.values()):
        # Expansion presets filter citizens to exactly one per roll slot, so the
        # per-slot pick has no choice to make — the deal is deterministic.
        cards = [
            _card("citizen", by_roll[roll][0]["id_citizens"], by_roll[roll][0]["name"], by_roll[roll][0].get("expansion"))
            for roll in sorted(by_roll)
        ]
        return {
            "key": "citizens",
            "title": "Citizens",
            "selection": "fixed",
            "note": "These citizen stacks are always dealt to the board.",
            "cards": cards,
        }
    else:
        selection = "random"
        note = "One citizen is dealt at random for each of the 10 dice slots."

    groups = []
    for roll in sorted(by_roll):
        cards = [
            _card("citizen", r["id_citizens"], r["name"], r.get("expansion"))
            for r in by_roll[roll]
        ]
        if cards:
            label = f"Roll {roll}" if roll < 9 else ("Roll 9-10" if roll == 9 else "Roll 11-12")
            groups.append({"label": label, "cards": cards})

    return {
        "key": "citizens",
        "title": "Citizens",
        "selection": selection,
        "note": note,
        "groups": groups,
    }


def _preview_domains(cur, cfg, players):
    rows = _fetch_pool_rows(cur, cfg["domain_query"], "domains", cfg["domain_expansion_filters"])
    excluded = set(cfg["exclude_domain_expansions"])
    banned = set(banned_domain_ids())
    rows = [
        r for r in rows
        if (r.get("expansion") or "") not in excluded
        and int(r["id_domains"]) not in banned
        and has_card_image("domain", r.get("id_domains"))
    ]
    rows.sort(key=lambda r: int(r["id_domains"]))
    cards = [_card("domain", r["id_domains"], r["name"], r.get("expansion")) for r in rows]
    return {
        "key": "domains",
        "title": "Domains",
        "selection": "random",
        "note": "5 stacks of 3 domains (4 each in 5-player games) are dealt at random from this pool.",
        "cards": cards,
    }


def _preview_dukes(cur, cfg, players, duke_select_count):
    rows = _fetch_pool_rows(cur, cfg["duke_query"], "dukes", cfg["duke_expansion_filters"])
    banned = set(banned_duke_ids())
    rows = [
        r for r in rows
        if int(r["id_dukes"]) not in banned
        and has_card_image("duke", r.get("id_dukes"))
    ]
    rows.sort(key=lambda r: int(r["id_dukes"]))
    cards = [_card("duke", r["id_dukes"], r["name"], r.get("expansion")) for r in rows]
    return {
        "key": "dukes",
        "title": "Dukes",
        "selection": "random",
        "note": f"Each player is dealt {duke_select_count} duke(s) at random from this pool.",
        "cards": cards,
    }


def _preview_events(cur, cfg, players):
    rows = _fetch_pool_rows(cur, cfg["event_query"], "events", cfg["event_expansion_filters"])
    if cfg["apply_implemented_image_filter"]:
        rows = [r for r in rows if keep_for_random("event", r)]
    else:
        rows = [r for r in rows if not is_unimplemented_event(r)]
    rows = [r for r in rows if has_card_image("event", r.get("id_events"))]
    rows.sort(key=lambda r: int(r["id_events"]))
    cards = [_card("event", r["id_events"], r["name"], r.get("expansion")) for r in rows]
    return {
        "key": "events",
        "title": "Events",
        "selection": "random",
        "note": "One event per player is shuffled into the exhausted deck at random.",
        "cards": cards,
    }


def _preview_starters(cur, cfg):
    cur.execute("SELECT * FROM starters ORDER BY id_starters")
    rows = cur.fetchall()
    core = []
    optional = []
    for r in rows:
        if not has_card_image("starter", r.get("id_starters")):
            continue
        if _is_optional_starter_row(r):
            optional.append(r)
        else:
            core.append(r)

    groups = []
    core_cards = [_card("starter", r["id_starters"], r["name"], r.get("expansion")) for r in core]
    if core_cards:
        groups.append({
            "label": "Core (every player)",
            "cards": core_cards,
        })

    note = "Every player starts with the core starters."
    selection = "fixed"

    if cfg["draft"]:
        opt_rows = optional
        if opt_rows:
            groups.append({
                "label": "Third starter (voted)",
                "cards": [_card("starter", r["id_starters"], r["name"], r.get("expansion")) for r in opt_rows],
            })
            note = "Players also vote for one extra third starter."
            selection = "mixed"
    elif cfg["optional_starter_expansion"] == "random":
        # random preset picks any -1/-1 starter at random
        opt_rows = [r for r in optional if keep_for_random("starter", r)]
        if opt_rows:
            groups.append({
                "label": "Third starter (one dealt at random)",
                "cards": [_card("starter", r["id_starters"], r["name"], r.get("expansion")) for r in opt_rows],
            })
            note = "Every player also gets one random third starter."
            selection = "mixed"
    elif cfg["optional_starter_expansion"]:
        target = cfg["optional_starter_expansion"].strip().lower()
        opt_rows = [r for r in optional if (r.get("expansion") or "").strip().lower() == target]
        if opt_rows:
            groups.append({
                "label": "Third starter (every player)",
                "cards": [_card("starter", r["id_starters"], r["name"], r.get("expansion")) for r in opt_rows],
            })
            note = "Every player also gets the third starter shown."

    return {
        "key": "starters",
        "title": "Starters",
        "selection": selection,
        "note": note,
        "groups": groups,
    }


def load_preset_preview(preset, expansion_only=False, players=4, duke_select_count=2):
    """Return a structured preview of every card a preset can put in play.

    Shape::

        {
          "preset": "current",
          "label": "Rotating Set",
          "expansion_only": False,
          "players": 4,
          "sections": [ {key, title, selection, note, groups|cards}, ... ],
        }

    `selection` is one of "fixed" (deterministic), "random", "draft", or
    "mixed". A section carries either `groups` (list of {label, cards}) or a
    flat `cards` list. Each card is {kind, id, name, expansion} where `kind`
    plugs straight into `/card-image/{kind}/{id}`.
    """
    players = max(2, min(5, int(players or 4)))
    duke_select_count = int(duke_select_count or 2)
    if duke_select_count not in (2, 3):
        duke_select_count = 2

    cfg = _preset_config(preset, bool(expansion_only))
    if preset == "random":
        cfg["optional_starter_expansion"] = "random"

    conn = _connect()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            sections = [
                _preview_starters(cur, cfg),
                _preview_monsters(cur, cfg, players),
                _preview_citizens(cur, cfg, players),
                _preview_domains(cur, cfg, players),
                _preview_dukes(cur, cfg, players, duke_select_count),
                _preview_events(cur, cfg, players),
            ]
        finally:
            cur.close()
    finally:
        conn.close()

    return {
        "preset": preset,
        "label": _PRESET_LABELS.get(preset, preset),
        "expansion_only": bool(expansion_only),
        "players": players,
        "duke_select_count": duke_select_count,
        "sections": sections,
    }
