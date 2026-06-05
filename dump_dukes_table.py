#!/usr/bin/env python3
"""
Dump the contents of the dukes table from the database.
"""

import mariadb
import sys

# Database configuration based on AGENTS.md
DB_CONFIG = {
    "user": "vckonline",
    "password": "vckonline",
    "host": "127.0.0.1",
    "port": 3306,
    "database": "vckonline",
}

def dump_dukes_table():
    try:
        # Connect to database
        conn = mariadb.connect(**DB_CONFIG)
        cur = conn.cursor(dictionary=True)
        
        # Query the dukes table
        cur.execute("SELECT * FROM dukes")
        rows = cur.fetchall()
        
        print("Contents of the dukes table:")
        print("-" * 50)
        
        if not rows:
            print("Table is empty")
        else:
            # Print column headers
            if rows:
                columns = list(rows[0].keys())
                header = " | ".join(f"{col:<20}" for col in columns)
                print(header)
                print("-" * (len(header)))
                
                # Print rows
                for row in rows:
                    values = [str(row[col]) if row[col] is not None else "NULL" for col in columns]
                    print(" | ".join(f"{val:<20}" for val in values))
        
        conn.close()
        
    except mariadb.Error as e:
        print(f"Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    dump_dukes_table()