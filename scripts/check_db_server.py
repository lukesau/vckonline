#!/usr/bin/env python3
"""
Reachability probe for the local MariaDB server.

This script does NOT import `mariadb` — that way it works before the venv is
set up and it isolates "is the DB port open?" from any Python connector issue.
For the full end-to-end check use `tests/test_database.py` instead.

The canonical connection parameters for this repo are:
    host=127.0.0.1, port=3306, database=vckonline, user=vckonline, password=vckonline
See docs/setup.md (or docs/local/agents.md on the maintainer machine).
"""

import socket
import sys

def check_database_server():
    """Check if database server is listening on port 3306"""
    print("Probing 127.0.0.1:3306 (MariaDB)...")
    print("=" * 60)
    print("Credentials are hard-coded across the repo: db=user=pass=vckonline.")

    host = '127.0.0.1'
    port = 3306

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
