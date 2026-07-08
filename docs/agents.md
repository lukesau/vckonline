# Agent quick start

This file is the one-stop overview for AI coding agents working in this repo. Read it before doing anything that touches the database or installs Python packages.

> **Maintainer note:** if `docs/local/agents.md` exists on disk, read that file instead — it documents SSH-tunnel access to a remote database and overrides the connection workflow below.

The full developer docs live in this folder. The most-referenced ones:

- `setup.md` — database, venv, and server bootstrap (start here for new environments)
- `database.md` — stored procedures, presets, SQL layout
- `testing.md` — running the test suite
- `game.md`, `server.md`, `wiki.md` — engine / server / wiki

## Database

**One MariaDB instance, one set of credentials, one connector library. Do not try anything else.**

See [`setup.md`](setup.md) for creating the schema, loading seed data, and installing stored procedures.

Credentials are loaded from `.env` (copy `.env.example` to `.env` and set `VCKO_DB_PASSWORD`). See [`db_config.py`](../db_config.py).

| Variable | Default |
| -------- | ------- |
| `VCKO_DB_HOST` | `127.0.0.1` |
| `VCKO_DB_PORT` | `3306` |
| `VCKO_DB_NAME` | `vckonline` |
| `VCKO_DB_USER` | `vckonline` |
| `VCKO_DB_PASSWORD` | *(required)* |

### Step 1 — confirm MariaDB is reachable

```bash
python3 scripts/check_db_server.py
```

This probes the configured host/port with no Python dependencies. If it fails, MariaDB is not running or not listening on the expected port — see [`setup.md`](setup.md).

### Step 2 — use the `mariadb` Python connector, nothing else

```python
from db_config import connect

conn = connect()
cur = conn.cursor(dictionary=True)   # dictionary=True is the project convention
```

Do **not** swap in `pymysql`, `mysql.connector`, `mysqlclient`, `sqlalchemy`, or other drivers.

### Step 3 — activate the venv before running anything

```bash
source ./activate_with_env.sh
```

If `.venv/` doesn't exist yet: `./setup_venv.sh`

### Step 4 — canonical end-to-end check

```bash
python3 tests/test_database.py
```

### Connector troubleshooting

| symptom | actual cause | fix |
| ------- | ------------ | --- |
| `ModuleNotFoundError: No module named 'mariadb'` | venv not activated | `source ./activate_with_env.sh` |
| `Can't connect to MySQL server on '127.0.0.1'` | DB not running | see [`setup.md`](setup.md) |
| `VCKO_DB_PASSWORD is not set` | missing `.env` | `cp .env.example .env` and set the password |
| `Access denied for user '...'@'localhost'` | wrong credentials | check `.env` matches MariaDB |
| `Unknown column 'citizen_id' in ...` | wrong PK name | use `id_citizens` (see setup.md PK table) |
| `mariadb_config not found` during `pip install mariadb` | Connector/C not installed | `./setup_venv.sh` |

## Python rules

- Always activate `.venv` first (`source ./activate_with_env.sh`).
- The `mariadb` connector needs `MARIADB_CONFIG` set at install time; the helper scripts do this. Don't `pip install mariadb` by hand without that env var.
- This codebase does not use strict typing in Python. Don't add `from __future__ import annotations` or sprinkle type hints onto existing modules.
- Avoid narrating-the-obvious comments in code. Only comment intent or non-obvious trade-offs.

## Test conventions

- All tests live in `tests/` as `tests/test_<area>.py` (Python `unittest`). Run one file with `python3 -m unittest tests.<module>`, or the whole suite with `python3 -m unittest discover -s tests -t . -p "test_*.py"`.
- `tests/__init__.py` puts the repo root on `sys.path`.
- Most engine tests build minimal in-memory `Game` objects without touching the DB. A few interaction tests load canonical card data from the live DB and skip when the database is unreachable.
- Tests that need the DB import credentials from `db_config` (`connect()` or `DB_CONFIG`).

## Utility scripts (`scripts/`)

- `scripts/check_db_server.py` — port reachability probe (no venv required)
- `scripts/dump_tables.py` — dump all card tables to dated INSERT files in `sql/dumps/` (requires venv + DB)
- `scripts/card_image_utils.py` — normalize card artwork to 400×570 JPEG
- `scripts/generate_rotating_monster_set.py` — generate balanced `fixed_monster_areas` from the full monster pool (requires venv + DB)
