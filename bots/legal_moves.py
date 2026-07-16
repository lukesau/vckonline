"""Backwards-compatible shim.

Legal-move enumeration now lives in the engine as the single source of truth
(`engines.available_actions`) so the server, the headless simulator, and
external bots all share one implementation. This module re-exports it so
existing imports (`from bots.legal_moves import enumerate_actions`) keep working.
"""

from engines.available_actions import (  # noqa: F401
    BINARY_PROMPTS,
    CHOOSE_MONSTER_SLAY_PREFIX,
    CHOOSE_N_PROMPTS,
    RESOURCES,
    enumerate_actions,
)

__all__ = [
    "BINARY_PROMPTS",
    "CHOOSE_MONSTER_SLAY_PREFIX",
    "CHOOSE_N_PROMPTS",
    "RESOURCES",
    "enumerate_actions",
]
