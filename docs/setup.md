# Local development setup

This guide assumes MariaDB (or MySQL) is already installed and running on the same machine as the game server. It does not cover installing or administering the database server itself — only creating the `vckonline` schema, loading card data, and wiring up the Python environment.

For a headless client against the public hosted server (no local database), see [`vcko-api.md`](vcko-api.md).

## Connection parameters

Every script and test in this repo uses the same hard-coded credentials:

```
host     127.0.0.1
port     3306
database vckonline
user     vckonline
password vckonline
```

Mnemonic: **db == user == pass == `vckonline`**.

## 1. Create the database and user

Run as a MariaDB admin user (e.g. `root`):

```bash
mysql -u root -p < sql/create_database.sql
```

This creates the `vckonline` database and a `vckonline`@`localhost` account with full privileges on it.

## 2. Create tables

```bash
./sql/run_sql.sh sql/schema/create_tables.sql
```

This creates all nine card tables: `citizens`, `monsters`, `domains`, `dukes`, `starters`, `events`, `nobles`, `agents`, and `relics`.

## 3. Load card data

Seed dumps live in `sql/seed/` — one file per table, generated from the canonical card database:

```bash
./sql/load_seed_data.sh
```

Or load individual tables:

```bash
./sql/run_sql.sh sql/seed/citizens.sql
./sql/run_sql.sh sql/seed/monsters.sql
# ... etc.
```

To refresh the seed files from a running database (e.g. after editing card rows), activate the venv and run `python3 scripts/dump_tables.py`, then copy the dated files from `sql/dumps/` into `sql/seed/`.

## 4. Install stored procedures

The game server calls stored procedures to select card pools at deal time:

```bash
./sql/run_sql.sh sql/create_all_stored_procedures.sql
```

See [`database.md`](database.md) for the full procedure list and preset wiring. See [`sql/INSTALL_PROCEDURES.md`](../sql/INSTALL_PROCEDURES.md) for alternate install methods.

## 5. Python environment

The repo uses the official `mariadb` Python connector, which requires the MariaDB Connector/C native library at install time.

```bash
./setup_venv.sh          # first time: creates .venv and installs requirements
source ./activate_with_env.sh   # every session
```

On macOS, `setup_venv.sh` installs Connector/C via Homebrew if needed. On Linux, install your distro's `libmariadb-dev` (or equivalent) before running `setup_venv.sh`, and set `MARIADB_CONFIG` to point at `mariadb_config` if it is not on your PATH.

Do **not** substitute other MySQL drivers (`pymysql`, `mysqlclient`, `sqlalchemy`, etc.) — they are not used in this codebase.

## 6. Verify

Port check (no venv required):

```bash
python3 scripts/check_db_server.py
```

Full end-to-end check (venv required):

```bash
source ./activate_with_env.sh
python3 tests/test_database.py
```

If both pass, the database is ready.

## 7. Run the game server

```bash
source ./activate_with_env.sh
python3 server.py
```

Open `http://localhost:8000` for the dev HTML client. See [`server.md`](server.md) for architecture and API details.

## Troubleshooting

| symptom | likely cause | fix |
| ------- | ------------ | --- |
| `ModuleNotFoundError: No module named 'mariadb'` | venv not activated | `source ./activate_with_env.sh` |
| `Can't connect to MySQL server on '127.0.0.1'` | MariaDB not running or wrong port | start MariaDB; confirm it listens on 3306 |
| `Access denied for user 'vckonline'@'localhost'` | user not created or wrong password | re-run `sql/create_database.sql` |
| `Table 'vckonline.citizens' doesn't exist` | schema not loaded | `./sql/run_sql.sh sql/schema/create_tables.sql` |
| `PROCEDURE vckonline.select_base_monsters does not exist` | stored procedures missing | `./sql/run_sql.sh sql/create_all_stored_procedures.sql` |
| `Unknown column 'citizen_id'` | wrong PK name in hand-written SQL | use `id_citizens` (see [`agents.md`](agents.md)) |

## Table primary keys

The PK columns are named `id_<table>` (legacy schema), not `<table>_id`:

| table | pk |
| ----- | -- |
| `citizens` | `id_citizens` |
| `monsters` | `id_monsters` |
| `domains` | `id_domains` |
| `dukes` | `id_dukes` |
| `starters` | `id_starters` |
| `events` | `id_events` |
| `nobles` | `id_nobles` |
| `agents` | `id_agents` |
| `relics` | `id_relics` |

The Python card classes (`cards.py`) expose them as `citizen_id`, `monster_id`, etc. — the mapping happens in `game_setup.py` when building objects from DB rows.
