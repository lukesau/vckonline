"""In-memory card tables loaded once; replaces MariaDB stored procedures at deal time.

Stored procedures are simple static SELECTs (filter and/or ORDER BY RAND()). This
module mirrors them in Python so `load_game_data` can deal from RAM after a
single bulk load instead of opening a DB round-trip per game.
"""

import random
import threading

_POOL = None
_LOCK = threading.Lock()

TABLES = (
    "monsters",
    "citizens",
    "domains",
    "dukes",
    "events",
    "starters",
    "nobles",
    "agents",
    "relics",
)


def ensure_loaded():
    """Load every card table from MariaDB once (per process)."""
    global _POOL
    if _POOL is not None:
        return _POOL
    with _LOCK:
        if _POOL is not None:
            return _POOL
        from db_config import connect

        conn = connect()
        cur = conn.cursor(dictionary=True)
        pool = {}
        for table in TABLES:
            cur.execute(f"SELECT * FROM {table}")
            pool[table] = [dict(row) for row in cur.fetchall()]
        cur.close()
        conn.close()
        _POOL = pool
    return _POOL


def reset_pool():
    """Drop the cached pool (tests only)."""
    global _POOL
    with _LOCK:
        _POOL = None


def _rows(table):
    return list(ensure_loaded()[table])


def _copy(rows):
    return [dict(r) for r in rows]


def _shuffled(rows):
    out = _copy(rows)
    random.shuffle(out)
    return out


def _proc_base1_citizens(rows):
    return [r for r in rows if r.get("expansion") == "base1"]


def _proc_base1_monsters(rows):
    return [r for r in rows if r.get("expansion") == "base1"]


def _proc_base_citizens(rows):
    return [r for r in rows if r.get("expansion") in ("base1", "base2")]


def _proc_base_monsters(rows):
    return [r for r in rows if r.get("expansion") in ("base1", "base2")]


def _proc_base2_citizens(rows):
    out = [r for r in rows if r.get("expansion") == "base2"]
    out += [
        r for r in rows
        if r.get("expansion") == "base1" and r.get("name") in ("Peasant", "Knight")
    ]
    return out


def _proc_base2_monsters(rows):
    return [r for r in rows if r.get("expansion") in ("base2", "gnolls", "undeadsamurai")]


def _proc_base_domains(rows):
    return _shuffled([r for r in rows if r.get("expansion") == "base"])


def _proc_base_dukes(rows):
    return _shuffled([r for r in rows if r.get("expansion") == "base"])


def _proc_random_domains(rows):
    return _shuffled(rows)


def _proc_random_dukes(rows):
    return _shuffled(rows)


def _proc_test1_domains(rows):
    wanted = {1, 2, 3, 4, 5, 6, 7, 8, 93, 94, 95, 96, 97, 98, 99}
    return _shuffled([r for r in rows if int(r["id_domains"]) in wanted])


def _proc_test2_domains(rows):
    candidates = [r for r in rows if 9 <= int(r["id_domains"]) <= 24]
    random.shuffle(candidates)
    return candidates[:15]


def _proc_all_monsters(rows):
    return _copy(rows)


def _proc_all_citizens(rows):
    return _copy(rows)


def _proc_base_events(rows):
    out = [r for r in rows if r.get("expansion") == "base"]
    out.sort(key=lambda r: int(r["id_events"]))
    return out


def _proc_all_events(rows):
    out = _copy(rows)
    out.sort(key=lambda r: int(r["id_events"]))
    return out


_PROC_HANDLERS = {
    "select_base1_citizens": _proc_base1_citizens,
    "select_base1_monsters": _proc_base1_monsters,
    "select_base_citizens": _proc_base_citizens,
    "select_base_monsters": _proc_base_monsters,
    "select_base2_citizens": _proc_base2_citizens,
    "select_base2_monsters": _proc_base2_monsters,
    "select_base_domains": _proc_base_domains,
    "select_base_dukes": _proc_base_dukes,
    "select_random_domains": _proc_random_domains,
    "select_random_dukes": _proc_random_dukes,
    "select_test1_domains": _proc_test1_domains,
    "select_test2_domains": _proc_test2_domains,
    "select_all_monsters": _proc_all_monsters,
    "select_all_citizens": _proc_all_citizens,
    "select_base_events": _proc_base_events,
    "select_all_events": _proc_all_events,
}


def fetch_pool_rows(proc_name, table_name, expansion_filters=None):
    """Drop-in replacement for game_setup's old _fetch_pool_rows DB helper."""
    if expansion_filters:
        ex = set(expansion_filters)
        return [
            dict(r) for r in _rows(table_name)
            if (r.get("expansion") or "") in ex
        ]
    handler = _PROC_HANDLERS.get(proc_name)
    if not handler:
        raise ValueError(f"Unknown card pool procedure: {proc_name!r}")
    return handler(_rows(table_name))


def fetch_starters():
    rows = _rows("starters")
    rows.sort(key=lambda r: int(r["id_starters"]))
    return _copy(rows)


def fetch_optional_starter_candidates(exclude_starter_expansions=()):
    ex = set(exclude_starter_expansions or ())
    return [
        dict(r) for r in _rows("starters")
        if int(r.get("roll_match1") or 0) == -1
        and int(r.get("roll_match2") or 0) == -1
        and (r.get("expansion") or "") not in ex
    ]


def fetch_domains_by_ids(domain_ids):
    wanted = {int(i) for i in domain_ids}
    return [dict(r) for r in _rows("domains") if int(r["id_domains"]) in wanted]


def fetch_undead_samurai_reserve():
    rows = [
        r for r in _rows("monsters")
        if r.get("area") == "Undead Samurai" and r.get("monster_type") == "Minion"
    ]
    rows.sort(key=lambda r: int(r.get("monster_order") or 0))
    return _copy(rows)


def fetch_kings_guard_citizens(expansion):
    return [
        dict(r) for r in _rows("citizens")
        if r.get("expansion") == expansion and int(r.get("special_citizen") or 0) == 1
    ]


def fetch_nobles():
    return _copy(_rows("nobles"))


def fetch_agents():
    rows = _rows("agents")
    rows.sort(key=lambda r: int(r["id_agents"]))
    return _copy(rows)


def fetch_relics():
    rows = _rows("relics")
    rows.sort(key=lambda r: int(r["id_relics"]))
    return _copy(rows)
