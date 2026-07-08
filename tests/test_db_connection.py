#!/usr/bin/env python3
"""
Test database connection and list tables to verify everything works.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mariadb

from db_config import DB_CONFIG


def test_db_connection():
    try:
        conn = mariadb.connect(**DB_CONFIG)
        cur = conn.cursor(dictionary=True)

        cur.execute("SHOW TABLES")
        tables = cur.fetchall()

        print("Database tables:")
        for table in tables:
            table_name = list(table.values())[0]
            print(f"  - {table_name}")

        cur.execute("SELECT COUNT(*) as count FROM dukes")
        count_result = cur.fetchone()
        duke_count = count_result["count"]

        print(f"\nDukes table has {duke_count} rows")

        if duke_count > 0:
            cur.execute("SELECT * FROM dukes LIMIT 10")
            rows = cur.fetchall()

            print("\nFirst 10 rows of dukes table:")
            print("-" * 50)

            if rows:
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
    success = test_db_connection()
    sys.exit(0 if success else 1)
