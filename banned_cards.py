import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent / "banned_cards.json"


def banned_duke_ids():
    """Ids from banned_cards.json 'dukes' key; empty set if file missing or key absent."""
    return _banned_ids_for_key("dukes")


def banned_domain_ids():
    """Ids from banned_cards.json 'domains' key; empty set if file missing or key absent."""
    return _banned_ids_for_key("domains")


def _banned_ids_for_key(key):
    if not _CONFIG_PATH.is_file():
        return set()
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    raw = data.get(key) or []
    return {int(x) for x in raw}
