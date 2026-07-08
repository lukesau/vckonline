#!/bin/bash
# Setup script for VCK Online virtual environment

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

MARIADB_CONFIG_PATH=$(find_mariadb_config) || {
    echo "Error: mariadb_config not found."
    echo "Install MariaDB Connector/C development headers, then either:"
    echo "  - ensure mariadb_config is on your PATH, or"
    echo "  - export MARIADB_CONFIG=/path/to/mariadb_config"
    echo ""
    echo "macOS:         brew install mariadb-connector-c"
    echo "Debian/Ubuntu: sudo apt-get install libmariadb-dev"
    exit 1
}

echo "Found mariadb_config at: $MARIADB_CONFIG_PATH"

if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "Virtual environment activated"
else
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
fi

export MARIADB_CONFIG="$MARIADB_CONFIG_PATH"
pip install -r requirements.txt

echo ""
echo "Setup complete! To activate the environment in the future:"
echo "  source ./activate_with_env.sh"
