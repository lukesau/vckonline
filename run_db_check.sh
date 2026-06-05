#!/bin/bash

echo "Checking if database tunnel is running..."
python3 check_db_simple.py

echo ""
echo "If the tunnel is not running, you'll need to start it with:"
echo "ssh -L 3306:localhost:3306 lukesau.com"
echo ""
echo "Then activate the virtual environment:"
echo "source ./activate_with_env.sh"
echo ""
echo "And then run the database test:"
echo "python3 test_database.py"