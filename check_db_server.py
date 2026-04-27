#!/usr/bin/env python3
"""
Simple script to check if MariaDB/MySQL server is running
Doesn't require mariadb module - just checks if port is open
"""

import socket
import sys

def check_database_server():
    """Check if database server is listening on port 3306"""
    print("Checking if MariaDB/MySQL server is accessible on localhost:3306...")
    print("=" * 50)
    print("(Make sure SSH port forwarding is active: ssh -L 3306:localhost:3306 lukesau.com)")
    
    host = '127.0.0.1'
    port = 3306
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"✓ Database server is accessible at {host}:{port}")
            return True
        else:
            print(f"✗ Cannot reach {host}:{port}")
            print("\nMake sure SSH port forwarding is active:")
            print("  ssh -L 3306:localhost:3306 lukesau.com")
            return False
    except Exception as e:
        print(f"✗ Error checking server: {e}")
        return False

if __name__ == "__main__":
    success = check_database_server()
    sys.exit(0 if success else 1)

