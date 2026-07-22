# VCK Online Docs

Developer documentation for the VCK Online dev/test server and game engine.

## Agents (no database setup)

The `agent/` package runs in-process sims and can play against the **hosted**
server at [vcko.lukesau.com](https://vcko.lukesau.com). Card deals use
`sql/seed/*.sql` in memory — no MariaDB required for agent work:

```bash
python -m agent.play_random --games 10 --seed 1
python -m agent.server_bot --policy mcts --host --preset base
```

See [`agent/README.md`](../agent/README.md) and `vcko-api.md` for the API and
bot workflow. Legal-move unit tests:
`python3 -m unittest tests.test_bot_legal_moves -v`.

Everything else in this repo (engine, server, wiki, live deals via `card_pool`)
loads card data from the database and needs the setup in [`setup.md`](setup.md).

> **AI coding agents (backend only):** if your work touches the engine, server,
> database, or venv — start at [`agents.md`](agents.md). On the maintainer
> machine, `docs/local/agents.md` (gitignored) may override with SSH-tunnel
> instructions.

## Doc index

- `setup.md`: create the database, load seed data, install stored procedures, run the server
- `agents.md`: DB credentials, venv, connector setup, Python/test conventions
- `vcko-api.md`: client API guide and in-repo agents (`agent/`, no DB required for sims)
- `server.md`: run the FastAPI server, dev HTML client, and server architecture
- `database.md`: stored procedures, presets, and SQL directory layout
- `game.md`: game engine model and the DB-backed game bootstrap flow
- `wiki.md`: the read-only `/wiki` card database explorer
- `testing.md`: how to run the included test scripts
