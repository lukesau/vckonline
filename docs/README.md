# VCK Online Docs

Developer documentation for the VCK Online dev/test server and game engine.

## Bots (no database setup)

The `bots/` package is a separate headless client for playing against the **hosted** server at [vcko.lukesau.com](https://vcko.lukesau.com). It talks only over HTTP — no SSH tunnel, MariaDB, venv, or local FastAPI server required. System Python plus the stdlib is enough:

```bash
python3 scripts/run_bot_match.py --preset base
```

Play against ControlBot from the browser (bot hosts, you join the lobby at [vcko.lukesau.com](https://vcko.lukesau.com)):

```bash
python3 scripts/host_control_bot.py --preset base
```

See `vcko-api.md` for the full API reference and `bots/` for the client, legal-move enumeration, and bot runner. Unit tests: `python3 -m unittest tests.test_bot_legal_moves -v`.

Everything else in this repo (engine, server, wiki, card dumps) loads card data from the database and needs the setup in [`agents.md`](agents.md).

> **AI coding agents (backend only):** if your work touches the engine, server, database, or venv — not the `bots/` package — start at [`agents.md`](agents.md). It collapses the DB / venv / connector setup into a single page so you can connect on the first try.

## Doc index

- `agents.md`: DB credentials, SSH tunnel, venv, connector setup, Python/test conventions
- `vcko-api.md`: client API guide and in-repo bots (`bots/`, no DB required)
- `server.md`: run the FastAPI server, dev HTML client, and server architecture
- `database.md`: stored procedures, presets, and SQL directory layout
- `game.md`: game engine model and the DB-backed game bootstrap flow
- `wiki.md`: the read-only `/wiki` card database explorer
- `testing.md`: how to run the included test scripts
