# VCK Online Docs

This folder contains developer documentation for the VCK Online dev/test server and game engine.

## Bots (no database setup)

The `bots/` package is a separate headless client for playing against the **hosted** server at [vcko.lukesau.com](https://vcko.lukesau.com). It talks only over HTTP — no SSH tunnel, MariaDB, venv, or local FastAPI server required. System Python plus the stdlib is enough:

```bash
python3 scripts/run_bot_match.py --preset base
```

See `vcko-api.md` for the full API reference and `bots/` for the client, legal-move enumeration, and bot runner. Unit tests: `python3 -m unittest tests.test_bot_legal_moves -v`.

Everything else in this repo (engine, server, wiki, card dumps) loads card data from the database and needs the setup below.

> **AI coding agents (backend only):** if your work touches the engine, server, database, or venv — not the `bots/` package — start at `../AGENTS.md` in the repo root. It collapses the DB / venv / connector setup into a single page so you can connect on the first try.

## Database in one paragraph

Anything that touches the DB connects to MariaDB at `127.0.0.1:3306` (an SSH port forward) with **db == user == pass == `vckonline`**, via the `mariadb` Python package (do not substitute `pymysql`, `mysql.connector`, `mysqlclient`, etc.). Start the tunnel with `ssh -L 3306:localhost:3306 lukesau.com`, activate the venv with `source ./activate_with_env.sh`, and you're done. Full details in `database.md`.

## Start here

- `vcko-api.md`: client API guide and in-repo bots (`bots/`, no DB required)
- `README_SERVER.md`: how to run the FastAPI server and use the dev HTML client
- `dev-setup.md`: local environment setup (venv + MariaDB connector)
- `database.md`: database expectations, SSH tunnel, and stored procedure setup
- `server.md`: FastAPI server architecture and API surface
- `game.md`: game engine model and the DB-backed game bootstrap flow
- `wiki.md`: the read-only `/wiki` card database explorer
- `testing.md`: how to run the included test scripts

