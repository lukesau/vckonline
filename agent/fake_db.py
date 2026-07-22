"""In-memory stand-in for db_config.connect, serving rows parsed from sql/seed/*.sql.

Emulates exactly the cursor surface load_game_data uses: cursor(dictionary=True),
callproc(name), execute(sql[, params]), fetchall(), close(). Stored procedures are
reimplemented from their verbatim bodies in sql/create_all_stored_procedures.sql.
Unknown procs/SQL raise immediately so a missed query can never silently produce
an empty board.
"""

import random
import re

from . import seed_data

_tables = None


def get_tables():
    global _tables
    if _tables is None:
        _tables = seed_data.load_seed_tables()
    return _tables


def _shuffled(rows):
    rows = list(rows)
    random.shuffle(rows)
    return rows


# proc name -> function(tables) -> rows, mirroring the SQL bodies.
# ORDER BY RAND() uses the global `random` module so simulations stay seedable.
_PROCS = {
    "select_base1_monsters": lambda t: [r for r in t["monsters"] if r.get("expansion") == "base1"],
    "select_base1_citizens": lambda t: [r for r in t["citizens"] if r.get("expansion") == "base1"],
    "select_random_domains": lambda t: _shuffled(t["domains"]),
    "select_random_dukes": lambda t: _shuffled(t["dukes"]),
    "select_all_events": lambda t: sorted(t["events"], key=lambda r: r["id_events"]),
    "select_all_monsters": lambda t: list(t["monsters"]),
    "select_all_citizens": lambda t: list(t["citizens"]),
}

_SQL_PATTERNS = [
    (
        re.compile(r"^SELECT \* FROM starters ORDER BY id_starters$", re.I),
        lambda t, p: sorted(t["starters"], key=lambda r: r["id_starters"]),
    ),
    (
        re.compile(
            r"^SELECT \* FROM starters WHERE roll_match1 = -1 AND roll_match2 = -1 ORDER BY id_starters$",
            re.I,
        ),
        lambda t, p: sorted(
            (r for r in t["starters"] if r["roll_match1"] == -1 and r["roll_match2"] == -1),
            key=lambda r: r["id_starters"],
        ),
    ),
    (
        re.compile(
            r"^SELECT \* FROM monsters WHERE area = %s AND monster_type = %s ORDER BY monster_order$",
            re.I,
        ),
        lambda t, p: sorted(
            (r for r in t["monsters"] if r.get("area") == p[0] and r.get("monster_type") == p[1]),
            key=lambda r: r.get("monster_order") or 0,
        ),
    ),
    (
        re.compile(r"^SELECT \* FROM citizens WHERE expansion = %s AND special_citizen = 1$", re.I),
        lambda t, p: [
            r for r in t["citizens"]
            if r.get("expansion") == p[0] and int(r.get("special_citizen") or 0) == 1
        ],
    ),
    (
        re.compile(r"^SELECT \* FROM domains WHERE id_domains IN \(([\d\s,]+)\)$", re.I),
        None,  # handled specially below (ids captured from the SQL text)
    ),
    (
        re.compile(r"^SELECT \* FROM nobles$", re.I),
        lambda t, p: list(t.get("nobles") or []),
    ),
    (
        re.compile(r"^SELECT \* FROM agents ORDER BY id_agents$", re.I),
        lambda t, p: sorted(t.get("agents") or [], key=lambda r: r["id_agents"]),
    ),
    (
        re.compile(r"^SELECT \* FROM relics ORDER BY id_relics$", re.I),
        lambda t, p: sorted(t.get("relics") or [], key=lambda r: r["id_relics"]),
    ),
]


class FakeCursor:
    def __init__(self, tables):
        self._tables = tables
        self._rows = []

    def callproc(self, name, args=()):
        fn = _PROCS.get(name)
        if fn is None:
            raise ValueError(f"FakeDB: stored procedure {name!r} is not implemented")
        self._rows = [dict(r) for r in fn(self._tables)]

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split()).rstrip(";").strip()
        for pattern, fn in _SQL_PATTERNS:
            m = pattern.match(normalized)
            if not m:
                continue
            if fn is None:
                ids = {int(x) for x in m.group(1).replace(",", " ").split()}
                rows = [r for r in self._tables["domains"] if r["id_domains"] in ids]
            else:
                rows = fn(self._tables, params or ())
            self._rows = [dict(r) for r in rows]
            return
        raise ValueError(f"FakeDB: unsupported SQL: {normalized!r}")

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, tables):
        self._tables = tables

    def cursor(self, dictionary=False):
        if not dictionary:
            raise ValueError("FakeDB: only dictionary=True cursors are supported")
        return FakeCursor(self._tables)

    def commit(self):
        pass

    def close(self):
        pass


def connect(**kwargs):
    return FakeConnection(get_tables())


def install():
    """Point db_config.connect at the fake and seed card_pool from sql/seed.

    load_game_data prefers card_pool.ensure_loaded() (bulk SELECT * FROM each
    table). Injecting the parsed seed tables into card_pool means agent deals
    never open MariaDB, while the live server still loads from the real DB.
    """
    import db_config
    import card_pool

    db_config.connect = connect
    tables = get_tables()
    pool = {}
    for name in card_pool.TABLES:
        pool[name] = [dict(r) for r in (tables.get(name) or [])]
    card_pool.reset_pool()
    card_pool._POOL = pool
