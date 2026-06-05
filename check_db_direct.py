#!/usr/bin/env python3

import socket

def main():
    host = '127.0.0.1'
    port = 3306
    
    print("Checking database connection...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            print(f"SUCCESS: {host}:{port} accepts TCP connections.")
            print("Database tunnel appears to be running.")
            return True
        else:
            print(f"FAILED: cannot reach {host}:{port}.")
            print("The database tunnel is not running.")
            return False
    except Exception as e:
        print(f"ERROR checking server: {e}")
        return False

if __name__ == "__main__":
    main()