# Testing & diagnostics

## Database connectivity

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

## API server smoke test

See `docs/README_SERVER.md` to run the FastAPI server and use the built-in HTML client at `/`.

