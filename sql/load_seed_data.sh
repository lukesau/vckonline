#!/bin/bash
# Load all card-table seed dumps from sql/seed/.
# Usage: ./sql/load_seed_data.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

TABLES=(
    citizens
    monsters
    domains
    dukes
    starters
    events
    nobles
    agents
    relics
)

for table in "${TABLES[@]}"; do
    file="$SCRIPT_DIR/seed/${table}.sql"
    if [ ! -f "$file" ]; then
        echo "Error: missing seed file: $file"
        exit 1
    fi
    echo "Loading $table ..."
    "$SCRIPT_DIR/run_sql.sh" "$file"
done

echo "All seed tables loaded."
