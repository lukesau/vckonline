# Dev setup

## Python environment

This repo expects a Python venv in `.venv/`.

The easiest path on macOS is to use the helper script:

```bash
./setup_venv.sh
```

That script:

- Creates (or reuses) `.venv/`
- Tries to locate `mariadb_config` under `/opt/homebrew`
- Installs `mariadb-connector-c` via Homebrew if needed
- Exports `MARIADB_CONFIG` and runs `pip install -r requirements.txt`

If you already have `.venv/` created and just want to activate with the MariaDB environment variable:

```bash
source ./activate_with_env.sh
```

This step is mandatory before running any DB-touching command. Without it, `import mariadb` will raise `ModuleNotFoundError` because the connector is installed inside `.venv/`, not system Python — and the answer is *not* to swap in a different connector.

## Requirements

Dependencies are listed in `requirements.txt` and include:

- `fastapi` + `uvicorn` (API server)
- **`mariadb`** (DB access; requires MariaDB Connector/C to build). This is the only supported DB driver in the project. Do not substitute `pymysql`, `mysql-connector-python`, `mysqlclient`, `sqlalchemy`, etc. — they are not installed and they don't fix any of the real connection problems (which are almost always the SSH tunnel being down, not the driver choice). See `docs/database.md` for the full anti-pattern list.
- `shortuuid` (player id generation)

