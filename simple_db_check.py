#!/usr/bin/env python3

import socket

def main():
    print("Checking if database is accessible...")
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex(('127.0.0.1', 3306))
        sock.close()

        if result == 0:
            print("SUCCESS: Database port 3306 is accessible")
            print("The SSH tunnel appears to be running.")
            return True
        else:
            print("FAILED: Cannot connect to database port 3306")
            print("The SSH tunnel may not be running.")
            return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False

if __name__ == "__main__":
    main()