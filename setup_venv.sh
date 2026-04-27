#!/bin/bash
# Setup script for VCK Online virtual environment

# Find mariadb_config
MARIADB_CONFIG_PATH=$(find /opt/homebrew -name mariadb_config 2>/dev/null | head -1)

if [ -z "$MARIADB_CONFIG_PATH" ]; then
    echo "Error: mariadb_config not found. Installing mariadb-connector-c..."
    brew install mariadb-connector-c
    MARIADB_CONFIG_PATH=$(find /opt/homebrew -name mariadb_config 2>/dev/null | head -1)
fi

if [ -z "$MARIADB_CONFIG_PATH" ]; then
    echo "Error: Could not find mariadb_config after installation."
    echo "Please install manually: brew install mariadb-connector-c"
    exit 1
fi

echo "Found mariadb_config at: $MARIADB_CONFIG_PATH"
echo "Setting MARIADB_CONFIG environment variable..."

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "Virtual environment activated"
else
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
fi

# Set environment variable and install packages
export MARIADB_CONFIG="$MARIADB_CONFIG_PATH"
pip install -r requirements.txt

echo ""
echo "Setup complete! To activate the environment in the future:"
echo "  source .venv/bin/activate"
echo "  export MARIADB_CONFIG=\"$MARIADB_CONFIG_PATH\""

