#!/usr/bin/env python3
"""
Full database test script - this is the canonical end-to-end check from docs/agents.md
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mariadb

from db_config import DB_CONFIG


def test_database():
    try:
        conn = mariadb.connect(**DB_CONFIG)
        cur = conn.cursor(dictionary=True)

        print("Connected to database successfully!")

        cur.execute("SHOW TABLES")
        tables = cur.fetchall()

        print("\nDatabase tables:")
        for table in tables:
            table_name = list(table.values())[0]
            print(f"  - {table_name}")

        print("\n--- DUKES TABLE CONTENTS ---")
        cur.execute("SELECT * FROM dukes")
        rows = cur.fetchall()

        if not rows:
            print("Dukes table is empty")
        else:
            columns = list(rows[0].keys())
            header = " | ".join(f"{col:<20}" for col in columns)
            print(header)
            print("-" * (len(header)))

            for row in rows:
                values = [str(row[col]) if row[col] is not None else "NULL" for col in columns]
                print(" | ".join(f"{val:<20}" for val in values))

        conn.close()
        return True

    except mariadb.Error as e:
        print(f"Database error: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    success = test_database()
    sys.exit(0 if success else 1)
