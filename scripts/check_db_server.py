#!/usr/bin/env python3
"""
Reachability probe for the local MariaDB server.

This script does NOT import `mariadb` — that way it works before the venv is
set up and it isolates "is the DB port open?" from any Python connector issue.
For the full end-to-end check use `tests/test_database.py` instead.

Host/port are read from VCKO_DB_HOST / VCKO_DB_PORT in `.env` when present.
See docs/setup.md (or docs/local/agents.md on the maintainer machine).
"""

import os
import socket
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass


def check_database_server():
    """Check if database server is listening on the configured host/port."""
    host = os.environ.get("VCKO_DB_HOST", "127.0.0.1")
    port = int(os.environ.get("VCKO_DB_PORT", "3306"))

    print(f"Probing {host}:{port} (MariaDB)...")
    print("=" * 60)
    print("Credentials are loaded from .env — see .env.example.")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            print(f"\nOK: {host}:{port} accepts TCP connections.")
            print("Next: activate the venv (source ./activate_with_env.sh) and run")
            print("      python3 tests/test_database.py for a full DB validation.")
            return True
        else:
            print(f"\nFAIL: cannot reach {host}:{port}.")
            print("MariaDB is not running or not listening on that port.")
            print("See docs/setup.md for database setup.")
            return False
    except Exception as e:
        print(f"FAIL: error checking server: {e}")
        return False


if __name__ == "__main__":
    success = check_database_server()
    sys.exit(0 if success else 1)
