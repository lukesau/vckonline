#!/usr/bin/env python3
"""
Direct database test without environment activation.
"""

import sys
import os

# Add current directory to path to make sure we can import modules if needed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # Try to import mariadb directly
    import mariadb
    
    # Database configuration based on AGENTS.md
    DB_CONFIG = {
        "user": "vckonline",
        "password": "vckonline",
        "host": "127.0.0.1",
        "port": 3306,
        "database": "vckonline",
    }

    # Connect to database
    conn = mariadb.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)
    
    print("Connected to database successfully!")
    
    # Show contents of dukes table specifically
    print("\n--- DUKES TABLE CONTENTS ---")
    cur.execute("SELECT * FROM dukes")
    rows = cur.fetchall()
    
    if not rows:
        print("Dukes table is empty")
    else:
        # Print column headers
        columns = list(rows[0].keys())
        header = " | ".join(f"{col:<20}" for col in columns)
        print(header)
        print("-" * (len(header)))
        
        # Print rows
        for row in rows:
            values = [str(row[col]) if row[col] is not None else "NULL" for col in columns]
            print(" | ".join(f"{val:<20}" for val in values))
    
    conn.close()
    
except ImportError as e:
    print(f"Cannot import mariadb: {e}")
    print("You need to activate the virtual environment first.")
    print("Run: source ./activate_with_env.sh")
except Exception as e:
    print(f"Error: {e}")