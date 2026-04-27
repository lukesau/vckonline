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

