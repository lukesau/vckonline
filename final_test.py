#!/usr/bin/env python3

import socket
import sys

def check_db():
    """Check if database is accessible"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex(('127.0.0.1', 3306))
        sock.close()

        if result == 0:
            print("SUCCESS: Database port 3306 is accessible")
            return True
        else:
            print("FAILED: Cannot connect to database port 3306")
            return False
    except Exception as e:
        print(f"ERROR checking DB: {e}")
        return False

def main():
    print("=== Final Database Test ===")
    
    # First check if we can reach the database
    if not check_db():
        print("\nTo connect to the database, you need to:")
        print("1. Start an SSH tunnel with:")
        print("   ssh -L 3306:localhost:3306 lukesau.com")
        print("2. Activate the virtual environment:")
        print("   source ./activate_with_env.sh")
        print("3. Then run this script again")
        return
    
    # If we get here, database is accessible
    print("\nDatabase is accessible! Now trying to connect...")
    
    try:
        import mariadb
        
        conn = mariadb.connect(
            user="vckonline",
            password="vckonline", 
            host="127.0.0.1",
            port=3306,
            database="vckonline"
        )
        
        cur = conn.cursor(dictionary=True)
        print("Connected to database successfully!")
        
        # Show dukes table contents
        cur.execute("SELECT * FROM dukes")
        rows = cur.fetchall()
        
        if not rows:
            print("Dukes table is empty")
        else:
            print(f"\nDukes table has {len(rows)} rows:")
            print("-" * 50)
            
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
        print("\nDone!")
        
    except ImportError as e:
        print(f"Cannot import mariadb: {e}")
        print("You need to activate the virtual environment first.")
        print("Run: source ./activate_with_env.sh")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()