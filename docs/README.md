# VCK Online Docs

This folder contains developer documentation for the VCK Online dev/test server and game engine.

> **AI coding agents:** start at `../AGENTS.md` in the repo root before reading anything in this folder. It collapses the DB / venv / connector setup into a single page so you can connect on the first try.

## Database in one paragraph

Anything that touches the DB connects to MariaDB at `127.0.0.1:3306` (an SSH port forward) with **db == user == pass == `vckonline`**, via the `mariadb` Python package (do not substitute `pymysql`, `mysql.connector`, `mysqlclient`, etc.). Start the tunnel with `ssh -L 3306:localhost:3306 lukesau.com`, activate the venv with `source ./activate_with_env.sh`, and you're done. Full details in `database.md`.

## Start here

- `README_SERVER.md`: how to run the FastAPI server and use the dev HTML client
- `dev-setup.md`: local environment setup (venv + MariaDB connector)
- `database.md`: database expectations, SSH tunnel, and stored procedure setup
- `server.md`: FastAPI server architecture and API surface
- `game.md`: game engine model and the DB-backed game bootstrap flow
- `wiki.md`: the read-only `/wiki` card database explorer
- `testing.md`: how to run the included test scripts

