#!/usr/bin/env python3

import sys
import os

print("Python path:")
for p in sys.path:
    print(f"  {p}")

print("\nCurrent working directory:", os.getcwd())
print("Environment variables:")
for key in sorted(os.environ.keys()):
    if 'mariadb' in key.lower() or 'db' in key.lower() or 'path' in key.lower():
        print(f"  {key}: {os.environ[key]}")

# Try to import mariadb
try:
    import mariadb
    print("\nSUCCESS: mariadb module imported successfully")
except ImportError as e:
    print(f"\nFAILED: Cannot import mariadb: {e}")
    
# Check if venv exists
if os.path.exists('.venv'):
    print("Found .venv directory")
else:
    print("No .venv directory found")

# Check if activate script exists
if os.path.exists('activate_with_env.sh'):
    print("Found activate_with_env.sh")
else:
    print("No activate_with_env.sh found")