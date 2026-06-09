import os
import sys

# Tests import top-level modules (game, cards, game_setup, ...) directly. Keep the
# repo root on sys.path so the suite runs no matter how it's invoked (discover,
# `python3 -m unittest tests.test_x`, etc.).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
