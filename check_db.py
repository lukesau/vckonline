#!/usr/bin/env python3
import socket
import sys

def check_database_server():
    """Check if database server is listening on port 3306"""
    print("Probing 127.0.0.1:3306 (MariaDB via SSH tunnel)...")
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
            print("==> Tunnel is already up. DO NOT start another `ssh -L 3306:...` —")
            print("    the repo owner usually runs it manually and it's persistent.")
            print("Next: activate the venv (source ./activate_with_env.sh) and run")
            print("      python3 test_database.py for a full DB validation.")
            return True
        else:
            print(f"\nFAIL: cannot reach {host}:{port}.")
            print("The SSH tunnel is not running. Ask the user to start it, or run:")
            print("  ssh -L 3306:localhost:3306 lukesau.com")
            print("in a separate terminal, then re-run this probe.")
            return False
    except Exception as e:
        print(f"FAIL: error checking server: {e}")
        return False

if __name__ == "__main__":
    success = check_database_server()
    sys.exit(0 if success else 1)