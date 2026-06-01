# Database

## Connection (read this first)

**Everything DB-related in this repo connects to a single MariaDB instance with the same credentials hard-coded everywhere.** Do not invent alternative hosts/users/passwords; if a tool or test seems to "need" a different one, that's a bug in the tool, not a real configuration.

| field    | value       |
| -------- | ----------- |
| host     | `127.0.0.1` |
| port     | `3306`      |
| database | `vckonline` |
| user     | `vckonline` |
| password | `vckonline` |

Mnemonic: **db == user == pass == `vckonline`**, host == loopback, port == default 3306.

The DB itself is not local — it lives on `lukesau.com`. The `127.0.0.1:3306` endpoint is provided by an SSH port forward that you start before doing anything that touches the DB:

```bash
ssh -L 3306:localhost:3306 lukesau.com
```

Keep that tunnel running for the whole session. `check_db_server.py` (port reachability) and `test_database.py` (full validation) both expect this exact endpoint, as do `game.py`, `game_setup.py`, `server.py`, and every test that opens a `mariadb.connect(...)`. If a test you're writing needs the DB, copy the dict above verbatim — do not parameterize.

## First-try connect script

Copy this template instead of writing your own from scratch. It is what every Python entry point in this repo does:

```python
import mariadb

DB_CONFIG = {
    "user": "vckonline",
    "password": "vckonline",
    "host": "127.0.0.1",
    "port": 3306,
    "database": "vckonline",
}

conn = mariadb.connect(**DB_CONFIG)
cur = conn.cursor(dictionary=True)
cur.execute("SELECT id_citizens, name FROM citizens LIMIT 3")
for row in cur:
    print(row)
conn.close()
```

Two prerequisites for this to work:

1. SSH tunnel up (`ssh -L 3306:localhost:3306 lukesau.com`).
2. Venv activated with `MARIADB_CONFIG` exported: `source ./activate_with_env.sh`.

## Use the `mariadb` Python connector, nothing else

The repo is built on the official **`mariadb`** package (a thin wrapper over MariaDB Connector/C, declared in `requirements.txt`). Substituting any other client library is a wasted detour — none of them are installed, and switching connectors does not solve "tunnel is down" or "venv not activated", which are the actual root causes of most connect failures.

Do **not** try:

- `pymysql` — wrong package, not installed.
- `mysql.connector` / `mysql-connector-python` — wrong package, not installed.
- `mysqlclient` / `MySQLdb` — wrong package, not installed.
- `sqlalchemy`, `asyncmy`, `aiomysql`, `aiosqlite` — not in this stack.
- `psycopg2` (PostgreSQL), `sqlite3` (file DB) — wrong database engine entirely.

If `import mariadb` raises `ModuleNotFoundError`, you are not in the venv. Run `source ./activate_with_env.sh` from the repo root and try again. Do not `pip install` a different connector to "fix" it.

## Connector troubleshooting cheat sheet

| symptom                                                   | actual cause                              | fix                                                 |
| --------------------------------------------------------- | ----------------------------------------- | --------------------------------------------------- |
| `ModuleNotFoundError: No module named 'mariadb'`          | venv not activated                        | `source ./activate_with_env.sh`                     |
| `Can't connect to MySQL server on '127.0.0.1'` / refused  | SSH tunnel not running                    | `ssh -L 3306:localhost:3306 lukesau.com`            |
| `Access denied for user '...'@'localhost'`                | tried to use creds other than `vckonline` | use the table above; no other accounts exist        |
| `Unknown column 'citizen_id' in ...`                      | wrong PK name (see schema gotcha below)   | use `id_citizens` (similarly `id_monsters`, etc.)   |
| `mariadb_config not found` during `pip install mariadb`   | Connector/C not installed                 | `./setup_venv.sh` (handles Homebrew install for you)|

## Schema gotcha: primary key column names

The DB pre-dates a newer naming convention. Primary key columns are `id_<table>`, not `<table>_id`:

| table      | pk            |
| ---------- | ------------- |
| `citizens` | `id_citizens` |
| `monsters` | `id_monsters` |
| `domains`  | `id_domains`  |
| `dukes`    | `id_dukes`    |
| `starters` | `id_starters` |
| `events`   | `id_events`   |

The Python card classes (`cards.py`) expose them as `citizen_id`, `monster_id`, etc.; the rename happens in `game_setup.py` when building card objects from DB rows. SQL queries (and `cursor.execute(...)`) use the `id_<table>` names.

## Overview

The game bootstrap in `game.py` loads card data from the `vckonline` database using stored procedures to select card sets and randomize stacks.

## Stored procedures

The server/game code expects these procedures to exist:

- `select_base1_monsters()`
- `select_base1_citizens()`
- `select_base_monsters()`
- `select_base_citizens()`
- `select_base2_monsters()`
- `select_base2_citizens()`
- `select_base_domains()`
- `select_base_dukes()`
- `select_random_domains()`
- `select_random_dukes()`
- `select_test1_domains()` — hand-picked domain pool for the `test1` preset (crystallized "first set")
- `select_test2_domains()` — random 15 of domain ids 9..24 for the `test2` preset
- `select_all_monsters()` — every row of `monsters` (used by the `random` preset)
- `select_all_citizens()` — every row of `citizens` (used by the `random` preset)
- `select_base_events()` — events where `expansion='base'` (the default events pool)
- `select_all_events()` — every row of `events` (used by the `random` preset)

The Python preset (passed to `load_game_data`) chooses which monster/citizen/domain/duke/event procedures to call:

| preset    | monsters                  | citizens                  | domains                  | dukes                 | events                  |
| --------- | ------------------------- | ------------------------- | ------------------------ | --------------------- | ----------------------- |
| `base`    | `select_base_monsters`    | `select_base_citizens`    | `select_base_domains`    | `select_base_dukes`   | `select_base_events`    |
| `base1`   | `select_base1_monsters`   | `select_base1_citizens`   | `select_random_domains`  | `select_random_dukes` | `select_base_events`    |
| `base2`   | `select_base2_monsters`   | `select_base2_citizens`   | `select_random_domains`  | `select_random_dukes` | `select_base_events`    |
| `test1`   | `select_base1_monsters`   | `select_base1_citizens`   | `select_test1_domains`   | `select_random_dukes` | `select_base_events`    |
| `test2`   | `select_base2_monsters`   | `select_base2_citizens`   | `select_test2_domains`   | `select_random_dukes` | `select_base_events`    |
| `random`  | `select_all_monsters`     | `select_all_citizens`     | `select_random_domains`  | `select_random_dukes` | `select_all_events`     |
| `current` | (alias of `base`)         | (alias of `base`)         | (alias of `base`)         | (alias of `base`)     | (alias of `base`)       |

The `base` / `current` preset uses the canonical Base Set board: all base1/base2 monster areas are fetched and Python randomly chooses 5 areas; all base1/base2 citizens are fetched and Python randomly chooses one citizen per roll-match stack; base domains and base dukes are randomized by procedure. `current` is just a Python-side alias for `base`; repointing it (e.g. when a future format becomes the default) requires editing `game_setup.py` rather than SQL — and `base` remains a separate preset value so "Base Set" stays in the lobby dropdown regardless.

The `random` preset draws from every expansion. Each card-type pool is post-filtered in Python by `card_filters.keep_for_random`, which drops rows the wiki flags as `is_unimplemented` and rows whose `/card-image/{kind}/{id}` art file is missing on disk. Monsters are filtered at the **area** level rather than per-row: if any card in a stack (after `is_extra` exclusion based on player count) fails the predicate, the whole area is dropped — a stack is dealt as a unit and a single unplayable card in it would block normal play of that area. Citizens, domains, dukes, and events are filtered per-row. After filtering, the same area-of-5 / one-citizen-per-roll / sample-15 / banned-cards logic that runs for the curated presets runs here too. If the filter wipes out coverage for any of the ten citizen dice slots (1..9, 11), or fewer than 5 monster areas survive, `load_game_data` raises a clear error rather than dealing an empty stack.

The live server (`server.py`) lets each lobby owner pick from `current`, `base`, `test1`, `test2`, or `random` (see `docs/server.md`); `current` is the default. The `banned_cards.json` `domains` filter is applied to every preset — so if a procedure's pool overlaps the ban list heavily it may return fewer than the 15 domains required and the preset will fail to render.

To install all procedures:

```bash
./sql/run_sql.sh sql/create_all_stored_procedures.sql
```

See `sql/INSTALL_PROCEDURES.md` for additional options (mysql client, interactive MariaDB session, installing individually).

## User / grants setup

If you have authentication or permissions problems, use:

- `sql/USER_SETUP_GUIDE.md`: investigation and fix commands (create users for `localhost`, `127.0.0.1`, `%`, and grant privileges)
- `sql/fix_user_setup.sql`: a convenience SQL script in this repo (if you prefer to run a script vs copy/paste commands)

## Verifying the DB

Quick port-level check (no Python deps):

```bash
python3 check_db_server.py
```

Full end-to-end check (Python + DB + tables + stored procs):

```bash
python3 test_database.py
```

