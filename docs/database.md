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
- `select_base2_monsters()`
- `select_base2_citizens()`
- `select_random_domains()`
- `select_random_dukes()`
- `select_test1_domains()` — hand-picked domain pool for the `test1` preset (crystallized "first set")
- `select_test2_domains()` — random 15 of domain ids 9..24 for the `test2` / `current` preset

The Python preset (passed to `load_game_data`) chooses which monster/citizen/domain procedures to call:

| preset    | monsters                  | citizens                  | domains                  |
| --------- | ------------------------- | ------------------------- | ------------------------ |
| `base1`   | `select_base1_monsters`   | `select_base1_citizens`   | `select_random_domains`  |
| `base2`   | `select_base2_monsters`   | `select_base2_citizens`   | `select_random_domains`  |
| `test1`   | `select_base1_monsters`   | `select_base1_citizens`   | `select_test1_domains`   |
| `test2`   | `select_base2_monsters`   | `select_base2_citizens`   | `select_test2_domains`   |
| `current` | (alias of `test2`)        | (alias of `test2`)        | (alias of `test2`)       |

`current` is just a Python-side alias; repointing it requires editing `game_setup.py` rather than SQL. The live server (`server.py`) starts games with the `current` preset. The `banned_cards.json` `domains` filter is applied to every preset (including `test1` / `test2` / `current`) — so if a procedure's pool overlaps the ban list heavily it may return fewer than the 15 domains required and the preset will fail to render.

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

