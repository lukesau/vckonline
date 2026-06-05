#!/usr/bin/env python3
import socket

host = '127.0.0.1'
port = 3306

try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex((host, port))
    sock.close()

    if result == 0:
        print(f"OK: {host}:{port} accepts TCP connections.")
        print("Database tunnel is up.")
    else:
        print(f"FAIL: cannot reach {host}:{port}.")
        print("Database tunnel is not running.")
except Exception as e:
    print(f"Error checking server: {e}")