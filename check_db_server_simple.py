#!/usr/bin/env python3
"""
Simple version of check_db_server.py to see if we can connect to the DB.
"""

import socket
import sys

def check_database_server():
    """Check if database server is listening on port 3306"""
    print("Probing 127.0.0.1:3306 (MariaDB via SSH tunnel)...")
    
    host = '127.0.0.1'
    port = 3306

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            print(f"OK: {host}:{port} accepts TCP connections.")
            return True
        else:
            print(f"FAIL: cannot reach {host}:{port}.")
            return False
    except Exception as e:
        print(f"FAIL: error checking server: {e}")
        return False

if __name__ == "__main__":
    success = check_database_server()
    sys.exit(0 if success else 1)