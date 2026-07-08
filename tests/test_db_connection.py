#!/usr/bin/env python3
"""
Test database connection and list tables to verify everything works.
"""

import mariadb
import sys

# Database configuration based on docs/agents.md
DB_CONFIG = {
    "user": "vckonline",
    "password": "vckonline",
    "host": "127.0.0.1",
    "port": 3306,
    "database": "vckonline",
}

def test_db_connection():
    try:
        # Connect to database
        conn = mariadb.connect(**DB_CONFIG)
        cur = conn.cursor(dictionary=True)
        
        # List all tables
        cur.execute("SHOW TABLES")
        tables = cur.fetchall()
        
        print("Database tables:")
        for table in tables:
            table_name = list(table.values())[0]  # Get the table name from dict
            print(f"  - {table_name}")
            
        # Check if dukes table exists and show its contents
        cur.execute("SELECT COUNT(*) as count FROM dukes")
        count_result = cur.fetchone()
        duke_count = count_result['count']
        
        print(f"\nDukes table has {duke_count} rows")
        
        if duke_count > 0:
            cur.execute("SELECT * FROM dukes LIMIT 10")
            rows = cur.fetchall()
            
            print("\nFirst 10 rows of dukes table:")
            print("-" * 50)
            
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