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

## Requirements

Dependencies are listed in `requirements.txt` and include:

- `fastapi` + `uvicorn` (API server)
- `mariadb` (DB access; requires MariaDB Connector/C to build)
- `shortuuid` (player id generation)

