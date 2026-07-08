# Local development setup

This guide assumes MariaDB (or MySQL) is already installed and running on the same machine as the game server. It does not cover installing or administering the database server itself — only creating the `vckonline` schema, loading card data, and wiring up the Python environment.

For a headless client against the public hosted server (no local database), see [`vcko-api.md`](vcko-api.md).

## Connection parameters

Credentials live in a `.env` file at the repo root (gitignored). Copy the template and set your password:

```bash
cp .env.example .env
# edit .env — set VCKO_DB_PASSWORD
```

| Variable | Default |
| -------- | ------- |
| `VCKO_DB_HOST` | `127.0.0.1` |
| `VCKO_DB_PORT` | `3306` |
| `VCKO_DB_NAME` | `vckonline` |
| `VCKO_DB_USER` | `vckonline` |
| `VCKO_DB_PASSWORD` | *(required — no default)* |

Python code loads these via [`db_config.py`](../db_config.py). Shell helpers (`sql/run_sql.sh`, `activate_with_env.sh`) source `.env` automatically when present.

For a fresh local install, `sql/create_database.sql` bootstraps the `vckonline` user with a placeholder password — set `VCKO_DB_PASSWORD` in `.env` to match whatever you configure in MariaDB.

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

On macOS with Homebrew, `local/setup_venv.sh` and `local/activate_with_env.sh` (gitignored) auto-install Connector/C and set `MARIADB_CONFIG`. Everyone else uses the public scripts at the repo root:

```bash
./setup_venv.sh          # first time: creates .venv and installs requirements
source ./activate_with_env.sh   # every session
```

Install MariaDB Connector/C development headers first if `setup_venv.sh` cannot find `mariadb_config`:

- macOS: `brew install mariadb-connector-c`
- Debian/Ubuntu: `sudo apt-get install libmariadb-dev`

You can also set `MARIADB_CONFIG=/path/to/mariadb_config` before running `setup_venv.sh`.

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
| `Access denied for user 'vckonline'@'localhost'` | user not created or wrong password | check `.env` matches MariaDB; re-run `sql/create_database.sql` if needed |
| `VCKO_DB_PASSWORD is not set` | missing `.env` | `cp .env.example .env` and set the password |
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

## Production credential rotation

After deploying this repo to a public-facing host, rotate the database password and keep it only in `.env` on the server (never commit it).

1. Generate a new password: `openssl rand -base64 24`
2. As a MariaDB admin on the server:

```sql
ALTER USER 'vckonline'@'localhost' IDENTIFIED BY '<new-password>';
FLUSH PRIVILEGES;
```

3. Create `.env` in the app directory with the new `VCKO_DB_PASSWORD` (and other vars if non-default).
4. Restart the uvicorn/systemd service so Python reloads the environment.
5. Verify: `python3 tests/test_database.py` (or `python3 -c "from db_config import connect; connect().close(); print('ok')"`).
6. Mark any GitGuardian alert as resolved — the leaked password in git history is useless after rotation.

MariaDB should remain bound to localhost only; the web app connects via `127.0.0.1` and does not expose port 3306.
