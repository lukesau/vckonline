#!/bin/bash
# Helper script to activate venv and set MariaDB environment variables

# Activate virtual environment
source .venv/bin/activate

# Find and set MARIADB_CONFIG
MARIADB_CONFIG_PATH=$(find /opt/homebrew -name mariadb_config 2>/dev/null | head -1)

if [ -n "$MARIADB_CONFIG_PATH" ]; then
    export MARIADB_CONFIG="$MARIADB_CONFIG_PATH"
    echo "✓ MARIADB_CONFIG set to: $MARIADB_CONFIG_PATH"
else
    echo "⚠ Warning: mariadb_config not found. Install with: brew install mariadb-connector-c"
fi

echo "Virtual environment activated and ready to use!"

