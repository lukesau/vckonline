# Testing & diagnostics

DB setup: [agents.md](agents.md).

## Database connectivity

### Port-level check

`scripts/check_db_server.py` checks whether `127.0.0.1:3306` is reachable (useful to verify your SSH tunnel).

```bash
python3 scripts/check_db_server.py
```

### End-to-end DB validation

`tests/test_database.py` does a more complete validation:

- imports `mariadb`
- connects to the DB
- checks required tables exist
- prints row counts and card contents (citizens/monsters/domains/dukes/starters)
- checks required stored procedures exist
- calls stored procedures and prints returned rows

```bash
python3 tests/test_database.py
```

## Engine unit/integration tests

All tests live in the `tests/` directory (Python `unittest`; there are no JavaScript tests). Each `tests/test_game_*.py` file targets a specific engine surface. The DB-free tests build minimal in-memory `Game` objects and exercise the engine directly. A few interaction tests pull canonical card data from the live DB so they regress against whatever the DB currently encodes (`special_reward`, `activation_effect`, etc.):

- `test_game_dragoon_slay_chain.py` — drives Dragoon's on-turn `slay` payout through a 3-prompt chain (Snow Queen `<domains>` -> Eye of Asteraten `s 5 + slay` -> Gnolls `choose <citizens>`). Skipped automatically when the tunnel isn't up.

Run a single test file (from the repo root):

```bash
python3 -m unittest tests.test_game_dragoon_slay_chain -v
```

Or run every test in the repo (from the repo root):

```bash
python3 -m unittest discover -s tests -t . -p "test_*.py" -v
```

## API server smoke test

See [server.md](server.md) to run the FastAPI server and use the built-in HTML client at `/`.
