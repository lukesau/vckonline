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
        out.append(c.to_dict())
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
        out.append(m.to_dict())
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
            row["text"],
            row["expansion"],
        )
        entry = d.to_dict()
        entry["is_banned"] = int(row["id_domains"]) in banned
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
        )
        out.append(s.to_dict())
    return out


def load_all_cards_for_wiki():
    """Return a dict of `{citizens, monsters, domains, dukes, starters}` lists.

    Each list contains plain dicts (via `cards.*.to_dict()`). Domain and
    duke entries additionally include an `is_banned` boolean so the
    client can flag entries listed in `banned_cards.json`.

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
            }
        finally:
            cur.close()
    finally:
        conn.close()
    counts = {k: len(v) for k, v in data.items()}
    return {"counts": counts, "cards": data}
