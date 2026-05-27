# Database

## Overview

The game bootstrap in `game.py` loads card data from a MariaDB database named `vckonline` using stored procedures to select card sets and randomize stacks.

The code assumes it can connect to:

- host: `127.0.0.1`
- port: `3306`
- user: `vckonline`
- password: `vckonline`
- database: `vckonline`

This is designed to work with an SSH tunnel that forwards the remote DB to local port 3306.

## SSH tunnel

Keep an SSH port forward running while using the DB locally:

```bash
ssh -L 3306:localhost:3306 lukesau.com
```

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

