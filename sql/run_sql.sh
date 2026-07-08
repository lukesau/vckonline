#!/bin/bash
# Helper script to run SQL files against the local vckonline database.
# Usage: ./sql/run_sql.sh sql/your_file.sql

# Find mysql binary (try PATH first, then common Homebrew location)
if command -v mysql >/dev/null 2>&1; then
    MYSQL_BIN="mysql"
elif [ -f "/opt/homebrew/opt/mysql-client/bin/mysql" ]; then
    MYSQL_BIN="/opt/homebrew/opt/mysql-client/bin/mysql"
else
    echo "Error: mysql binary not found"
    echo "Install a MySQL/MariaDB client and ensure mysql is on your PATH."
    exit 1
fi

if [ -z "$1" ]; then
    echo "Usage: $0 <sql_file>"
    echo "Example: $0 sql/create_all_stored_procedures.sql"
    exit 1
fi

SQL_FILE="$1"

if [ ! -f "$SQL_FILE" ]; then
    echo "Error: SQL file not found: $SQL_FILE"
    exit 1
fi

if ! nc -z 127.0.0.1 3306 2>/dev/null; then
    echo "Warning: cannot connect to 127.0.0.1:3306"
    echo "Make sure MariaDB is running. See docs/setup.md."
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Running SQL file: $SQL_FILE"
echo "Connecting to vckonline@127.0.0.1:3306 ..."
echo ""

"$MYSQL_BIN" -h 127.0.0.1 -P 3306 -u vckonline -pvckonline vckonline < "$SQL_FILE"

if [ $? -eq 0 ]; then
    echo ""
    echo "SQL file executed successfully"
else
    echo ""
    echo "Error executing SQL file"
    exit 1
fi
