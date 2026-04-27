#!/bin/bash
# Helper script to run SQL files on remote database through SSH port forwarding
# Usage: ./sql/run_sql.sh sql/your_file.sql
# Or: bash sql/run_sql.sh sql/your_file.sql

# Find mysql binary (try PATH first, then specific location)
if command -v mysql >/dev/null 2>&1; then
    MYSQL_BIN="mysql"
elif [ -f "/opt/homebrew/opt/mysql-client/bin/mysql" ]; then
    MYSQL_BIN="/opt/homebrew/opt/mysql-client/bin/mysql"
elif [ -f "/opt/homebrew/Cellar/mysql-client/9.5.0/bin/mysql" ]; then
    MYSQL_BIN="/opt/homebrew/Cellar/mysql-client/9.5.0/bin/mysql"
else
    echo "Error: mysql binary not found"
    echo "Please install mysql-client: brew install mysql-client"
    echo "Or add to PATH: export PATH=\"/opt/homebrew/opt/mysql-client/bin:\$PATH\""
    exit 1
fi

# Check if SQL file is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <sql_file>"
    echo "Example: $0 sql/create_all_stored_procedures.sql"
    exit 1
fi

SQL_FILE="$1"

# Check if SQL file exists
if [ ! -f "$SQL_FILE" ]; then
    echo "Error: SQL file not found: $SQL_FILE"
    exit 1
fi

# Check if port 3306 is accessible (SSH tunnel check)
if ! nc -z 127.0.0.1 3306 2>/dev/null; then
    echo "Warning: Cannot connect to localhost:3306"
    echo "Make sure SSH port forwarding is active:"
    echo "  ssh -L 3306:localhost:3306 lukesau.com"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Run the SQL file
echo "Running SQL file: $SQL_FILE"
echo "Connecting to database through SSH tunnel (localhost:3306)..."
echo ""

"$MYSQL_BIN" -h 127.0.0.1 -P 3306 -u vckonline -p vckonline < "$SQL_FILE"

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ SQL file executed successfully"
else
    echo ""
    echo "✗ Error executing SQL file"
    exit 1
fi

