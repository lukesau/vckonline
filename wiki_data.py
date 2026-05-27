"""
Loader for the read-only card wiki at /wiki.

Pulls every row of every card table directly (no stored procedures, no
banned-card filtering, no shuffling) and returns plain dicts using the
same field names that the rest of the codebase already uses on
`cards.py` instances.

The wiki is meant for browsing the database itself, so unfinished /
banned / unreleased rows are intentionally included. Cards that appear
in `banned_cards.json` are flagged via an extra `is_banned` boolean so
the client can render a small badge, but they are not filtered out.
"""

from cards import Citizen, Domain, Duke, Monster, Starter
from banned_cards import banned_domain_ids, banned_duke_ids
from card_filters import (
    is_unimplemented_citizen as _is_unimplemented_citizen,
    is_unimplemented_monster as _is_unimplemented_monster,
    is_unimplemented_domain as _is_unimplemented_domain,
    is_unimplemented_event as _is_unimplemented_event,
)


def _connect():
    import mariadb
    return mariadb.connect(
        user="vckonline",
        password="vckonline",
        host="127.0.0.1",
        database="vckonline",
        port=3306,
    )


def _fetch_all(cur, sql):
    cur.execute(sql)
    return cur.fetchall()


def _load_citizens(cur):
    rows = _fetch_all(cur, "SELECT * FROM citizens ORDER BY id_citizens")
    out = []
    for row in rows:
        c = Citizen(
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
        entry = c.to_dict()
        entry["is_unimplemented"] = _is_unimplemented_citizen(row)
        out.append(entry)
    return out


def _load_monsters(cur):
    rows = _fetch_all(cur, "SELECT * FROM monsters ORDER BY area ASC, monster_order ASC, id_monsters ASC")
    out = []
    for row in rows:
        m = Monster(
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
        entry = m.to_dict()
        entry["is_unimplemented"] = _is_unimplemented_monster(row)
        out.append(entry)
    return out


def _load_domains(cur, banned):
    rows = _fetch_all(cur, "SELECT * FROM domains ORDER BY id_domains")
    out = []
    for row in rows:
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
        entry = d.to_dict()
        entry["is_banned"] = int(row["id_domains"]) in banned
        entry["is_unimplemented"] = _is_unimplemented_domain(row)
        out.append(entry)
    return out


def _load_dukes(cur, banned):
    rows = _fetch_all(cur, "SELECT * FROM dukes ORDER BY id_dukes")
    out = []
    for row in rows:
        d = Duke(
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
        entry = d.to_dict()
        entry["is_banned"] = int(row["id_dukes"]) in banned
        out.append(entry)
    return out


def _load_events(cur):
    rows = _fetch_all(cur, "SELECT * FROM events ORDER BY id_events")
    out = []
    for row in rows:
        entry = {
            "id_events":               row["id_events"],
            "name":                    row["name"],
            "roll_match1":             row["roll_match1"],
            "roll_effect":             row["roll_effect"],
            "has_roll_effect":         row["has_roll_effect"],
            "is_monster":              row["is_monster"],
            "has_activation_effect":   row["has_activation_effect"],
            "has_passive_effect":      row["has_passive_effect"],
            "strength_cost":           row["strength_cost"],
            "magic_cost":              row["magic_cost"],
            "monster_type":            row["monster_type"],
            "vp_reward":               row["vp_reward"],
            "gold_reward":             row["gold_reward"],
            "strength_reward":         row["strength_reward"],
            "magic_reward":            row["magic_reward"],
            "has_special_reward":      row["has_special_reward"],
            "special_reward":          row["special_reward"],
            "activation_effect":       row["activation_effect"],
            "passive_effect":          row["passive_effect"],
            "roll_effect_text":        row["roll_effect_text"],
            "special_reward_text":     row["special_reward_text"],
            "activation_effect_text":  row["activation_effect_text"],
            "passive_effect_text":     row["passive_effect_text"],
            "expansion":               row["expansion"],
        }
        entry["is_unimplemented"] = _is_unimplemented_event(row)
        out.append(entry)
    return out


def _load_starters(cur):
    rows = _fetch_all(cur, "SELECT * FROM starters ORDER BY id_starters")
    out = []
    for row in rows:
        s = Starter(
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
        out.append(s.to_dict())
    return out


def load_all_cards_for_wiki():
    """Return a dict of `{citizens, monsters, domains, dukes, starters}` lists.

    Each list contains plain dicts (via `cards.*.to_dict()`). Domain and
    duke entries additionally include an `is_banned` boolean so the
    client can flag entries listed in `banned_cards.json`. Citizen,
    monster, and domain entries also include an `is_unimplemented`
    boolean — true when a row has a special/effect flag set but the
    corresponding text column is null or empty.

    Raises whatever `mariadb` raises if the DB is unreachable. The
    server wraps the call so the wiki endpoint returns a clear error
    instead of 500ing.
    """
    conn = _connect()
    try:
        cur = conn.cursor(dictionary=True)
        try:
            banned_domains = banned_domain_ids()
            banned_dukes = banned_duke_ids()
            data = {
                "citizens": _load_citizens(cur),
                "monsters": _load_monsters(cur),
                "domains": _load_domains(cur, banned_domains),
                "dukes": _load_dukes(cur, banned_dukes),
                "starters": _load_starters(cur),
                "events": _load_events(cur),
            }
        finally:
            cur.close()
    finally:
        conn.close()
    counts = {k: len(v) for k, v in data.items()}
    return {"counts": counts, "cards": data}
