# Agent quick start

This file is the one-stop overview for AI coding agents working in this repo. Read it before doing anything that touches the database or installs Python packages, otherwise you will burn several attempts re-discovering things written down here.

The full developer docs live in `docs/`. The most-referenced ones:

- `docs/database.md` — DB setup, SSH tunnel, stored procedures
- `docs/dev-setup.md` — Python venv + MariaDB Connector/C
- `docs/testing.md` — running the test suite
- `docs/game.md`, `docs/server.md`, `docs/wiki.md` — engine / server / wiki

## Database (the thing agents most often get wrong)

**One MariaDB instance, one set of credentials, one connector library. Do not try anything else.**

```
host     127.0.0.1     (loopback only — the real DB is remote; you go through an SSH tunnel)
port     3306          (standard MySQL/MariaDB port — not 3307, not anything else)
database vckonline
user     vckonline
password vckonline
```

Mnemonic: **db == user == pass == `vckonline`**.

### Step 1 — check whether the SSH tunnel is already up; do NOT recreate it

The repo owner usually starts the tunnel by hand in another terminal and leaves it running across sessions. **Always probe first; only start a tunnel if the probe fails.**

```bash
python3 scripts/check_db_server.py
```

It only does a `connect_ex` on `127.0.0.1:3306` (no Python deps) so it tells you "tunnel up?" without dragging in the venv.

- **Probe succeeds** ("OK: 127.0.0.1:3306 accepts TCP connections") → the tunnel is already running. **Do not run `ssh -L ...`.** Move on to Step 2.
- **Probe fails** ("FAIL: cannot reach 127.0.0.1:3306") → only then start a tunnel yourself:

  ```bash
  ssh -L 3306:localhost:3306 lukesau.com
  ```

  Run this in a separate terminal (or backgrounded) and leave it running for the rest of the session.

If you blindly try to start a tunnel while one already exists, `ssh` will exit with `bind [::1]:3306: Address already in use` / `channel_setup_fwd_listener_tcpip: cannot listen to port: 3306` — that is **not a failure**, it confirms the existing tunnel is healthy. Ignore the error and proceed.

Tunnel-down failures from the connector look like "Can't connect to MySQL server", "Connection refused", or "lost connection during query handshake". The fix is always the tunnel — never substitute a different host (`lukesau.com`, etc.) to bypass it.

### Step 2 — use the `mariadb` Python connector, nothing else

The repo uses the official **`mariadb`** package (a thin wrapper over MariaDB Connector/C). Every `*.py` that talks to the DB does:

```python
import mariadb
conn = mariadb.connect(
    user="vckonline",
    password="vckonline",
    host="127.0.0.1",
    port=3306,
    database="vckonline",
)
cur = conn.cursor(dictionary=True)   # dictionary=True is the project convention
```

Do **not** swap in alternatives. None of these are installed and none of them are wanted:

- `pymysql` — wrong package
- `mysql.connector` / `mysql-connector-python` — wrong package
- `mysqlclient` / `MySQLdb` — wrong package
- `sqlalchemy`, `asyncmy`, `aiomysql` — not in this stack
- `psycopg2`, `sqlite3` — different DB entirely

The `mariadb` package needs the MariaDB Connector/C native library on disk to build. The repo's `setup_venv.sh` and `activate_with_env.sh` handle that for macOS Homebrew. Use them.

### Step 3 — activate the venv before running anything

```bash
source ./activate_with_env.sh
```

This activates `.venv/` and sets `MARIADB_CONFIG` to the Homebrew path. Skipping this is the #2 cause of "ModuleNotFoundError: No module named 'mariadb'" failures — the module is installed inside `.venv`, not in system Python.

If `.venv/` doesn't exist yet:

```bash
./setup_venv.sh
```

### Step 4 — a complete, copy-pasteable connect script

This is the smallest correct script. Use it as a template for any one-off DB inspection you need:

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
cur.execute("SELECT COUNT(*) AS n FROM citizens")
print(cur.fetchone())
conn.close()
```

Run it via `python3 your_script.py` after `source ./activate_with_env.sh`.

### Step 5 — the canonical end-to-end check

```bash
python3 tests/test_database.py
```

Reads the same credentials, connects, lists tables, calls the stored procedures, and prints contents. If this passes, your DB setup is correct. If it fails, the failure message tells you which step is broken (tunnel / module / creds / procedures).

### Table primary keys (a small gotcha)

The PK columns are named `id_<table>` (legacy schema), not `<table>_id`:

| table      | pk            |
| ---------- | ------------- |
| `citizens` | `id_citizens` |
| `monsters` | `id_monsters` |
| `domains`  | `id_domains`  |
| `dukes`    | `id_dukes`    |
| `starters` | `id_starters` |
| `events`   | `id_events`   |
| `nobles`   | `id_nobles`   |

The Python card classes (`cards.py`) expose them as `citizen_id`, `monster_id`, etc. — the mapping happens in `game_setup.py` when building objects from DB rows.

## Python rules

- Always activate `.venv` first (`source ./activate_with_env.sh`).
- The `mariadb` connector needs `MARIADB_CONFIG` set at install time; the helper scripts do this. Don't `pip install mariadb` by hand without that env var.
- This codebase does not use strict typing in Python. Don't add `from __future__ import annotations` or sprinkle type hints onto existing modules.
- Avoid narrating-the-obvious comments in code (no `# loop over players`, etc.). Only comment intent or non-obvious trade-offs.

## Test conventions

- All tests live in the `tests/` directory as `tests/test_<area>.py` (Python `unittest`; there are no JavaScript tests). Run them from the repo root: a single file with `python3 -m unittest tests.<module>` (e.g. `python3 -m unittest tests.test_game_resting`), or the whole suite with `python3 -m unittest discover -s tests -t . -p "test_*.py"`.
- `tests/__init__.py` puts the repo root on `sys.path` so the test modules can import top-level modules (`game`, `cards`, `game_setup`, ...). New tests just `from game import Game` as before.
- Most engine tests build minimal in-memory `Game` objects without touching the DB. A few interaction tests (e.g. `tests/test_game_dragoon_slay_chain.py`) load canonical card data from the live DB and skip when the tunnel is down.
- Tests that need the DB hard-code the credentials dict above. Do not parameterize it.

## Utility scripts (`scripts/`)

Standalone CLI tools (not imported by the app):

- `scripts/check_db_server.py` — tunnel reachability probe (no venv required)
- `scripts/dump_tables.py` — dump all card tables to dated INSERT files in `sql/dumps/` (requires venv + tunnel)
- `scripts/card_image_utils.py` — normalize card artwork to 400×570 JPEG
- `scripts/generate_rotating_monster_set.py` — generate balanced `fixed_monster_areas` from the full monster pool (requires venv + tunnel)
