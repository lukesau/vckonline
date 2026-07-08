#!/bin/bash
# Helper script to run SQL files against the local vckonline database.
# Usage: ./sql/run_sql.sh sql/your_file.sql

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

VCKO_DB_HOST="${VCKO_DB_HOST:-127.0.0.1}"
VCKO_DB_PORT="${VCKO_DB_PORT:-3306}"
VCKO_DB_NAME="${VCKO_DB_NAME:-vckonline}"
VCKO_DB_USER="${VCKO_DB_USER:-vckonline}"

if [ -z "${VCKO_DB_PASSWORD:-}" ]; then
    echo "Error: VCKO_DB_PASSWORD is not set."
    echo "Copy .env.example to .env and set your database password."
    exit 1
fi

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

if ! nc -z "$VCKO_DB_HOST" "$VCKO_DB_PORT" 2>/dev/null; then
    echo "Warning: cannot connect to ${VCKO_DB_HOST}:${VCKO_DB_PORT}"
    echo "Make sure MariaDB is running. See docs/setup.md."
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "Running SQL file: $SQL_FILE"
echo "Connecting to ${VCKO_DB_USER}@${VCKO_DB_HOST}:${VCKO_DB_PORT} ..."
echo ""

export MYSQL_PWD="$VCKO_DB_PASSWORD"
"$MYSQL_BIN" -h "$VCKO_DB_HOST" -P "$VCKO_DB_PORT" -u "$VCKO_DB_USER" "$VCKO_DB_NAME" < "$SQL_FILE"
status=$?
unset MYSQL_PWD

if [ $status -eq 0 ]; then
    echo ""
    echo "SQL file executed successfully"
else
    echo ""
    echo "Error executing SQL file"
    exit 1
fi
