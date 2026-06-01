#!/usr/bin/env python3
"""
Reachability probe for the MariaDB tunnel.

This script does NOT import `mariadb` — that way it works before the venv is
set up and it isolates "is the tunnel up?" from any Python connector issue.
For the full end-to-end check use `test_database.py` instead.

The canonical connection parameters for this repo are:
    host=127.0.0.1, port=3306, database=vckonline, user=vckonline, password=vckonline
The DB is reached via an SSH tunnel; see AGENTS.md / docs/database.md.
"""

import socket
import sys

def check_database_server():
    """Check if database server is listening on port 3306"""
    print("Checking if MariaDB server is accessible on 127.0.0.1:3306...")
    print("=" * 60)
    print("DB is remote; reached via SSH tunnel:")
    print("  ssh -L 3306:localhost:3306 lukesau.com")
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
            print("      python3 test_database.py for a full DB validation.")
            return True
        else:
            print(f"\nFAIL: cannot reach {host}:{port}.")
            print("Start the SSH tunnel and retry:")
            print("  ssh -L 3306:localhost:3306 lukesau.com")
            return False
    except Exception as e:
        print(f"FAIL: error checking server: {e}")
        return False

if __name__ == "__main__":
    success = check_database_server()
    sys.exit(0 if success else 1)

