#!/bin/bash
# Activate the venv and set MARIADB_CONFIG when mariadb_config is available.

source .venv/bin/activate

find_mariadb_config() {
    if [ -n "${MARIADB_CONFIG:-}" ] && [ -x "$MARIADB_CONFIG" ]; then
        echo "$MARIADB_CONFIG"
        return 0
    fi
    if command -v mariadb_config >/dev/null 2>&1; then
        command -v mariadb_config
        return 0
    fi
    for dir in /opt/homebrew /usr/local; do
        if [ -d "$dir" ]; then
            found=$(find "$dir" -name mariadb_config 2>/dev/null | head -1)
            if [ -n "$found" ]; then
                echo "$found"
                return 0
            fi
        fi
    done
    return 1
}

MARIADB_CONFIG_PATH=$(find_mariadb_config)
if [ -n "$MARIADB_CONFIG_PATH" ]; then
    export MARIADB_CONFIG="$MARIADB_CONFIG_PATH"
    echo "✓ MARIADB_CONFIG set to: $MARIADB_CONFIG_PATH"
else
    echo "⚠ Warning: mariadb_config not found (only needed when (re)installing the mariadb package)."
    echo "  Set MARIADB_CONFIG or install Connector/C dev headers — see requirements.txt."
fi

echo "Virtual environment activated and ready to use!"
