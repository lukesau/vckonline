#!/bin/bash

echo "Activating virtual environment..."
source ./activate_with_env.sh

echo ""
echo "Running database test..."
python3 test_database.py