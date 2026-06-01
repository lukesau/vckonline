# Testing & diagnostics

## Database connectivity

> **Reminder:** the DB is at `127.0.0.1:3306` (SSH-forwarded) with **db == user == pass == `vckonline`**. Tunnel: `ssh -L 3306:localhost:3306 lukesau.com`. Tests that need the DB hard-code this dict; see `docs/database.md`.

### Port-level check

`check_db_server.py` checks whether `127.0.0.1:3306` is reachable (useful to verify your SSH tunnel).

```bash
python3 check_db_server.py
```

### End-to-end DB validation

`test_database.py` does a more complete validation:

- imports `mariadb`
- connects to the DB
- checks required tables exist
- prints row counts and card contents (citizens/monsters/domains/dukes/starters)
- checks required stored procedures exist
- calls stored procedures and prints returned rows

```bash
python3 test_database.py
```

## Engine unit/integration tests

Each `test_game_*.py` file targets a specific engine surface. The DB-free tests build minimal in-memory `Game` objects and exercise the engine directly. A few interaction tests pull canonical card data from the live DB so they regress against whatever the DB currently encodes (`special_reward`, `activation_effect`, etc.):

- `test_game_dragoon_slay_chain.py` — drives Dragoon's on-turn `slay` payout through a 3-prompt chain (Snow Queen `<domains>` -> Eye of Asteraten `s 5 + slay` -> Gnolls `choose <citizens>`). Skipped automatically when the tunnel isn't up.

Run a single test file:

```bash
python3 -m unittest test_game_dragoon_slay_chain -v
```

Or run every test in the repo:

```bash
python3 -m unittest discover -p "test_*.py" -v
```

## API server smoke test

See `docs/README_SERVER.md` to run the FastAPI server and use the built-in HTML client at `/`.

