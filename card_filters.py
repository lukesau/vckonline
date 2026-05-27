"""
Shared "is this card playable?" predicates.

Both the wiki (`wiki_data.py`) and the random-preset board dealer
(`game_setup.py`) need a consistent answer to:

  1. Is this row implemented? — i.e. does every `has_<effect>` flag on the
     row map to a non-empty effect string the engine can resolve?
  2. Does the row have an image on disk that the `/card-image/{kind}/{id}`
     endpoint will actually return?

Centralising both predicates here means a card the wiki shows as
implemented is the same card the random preset is allowed to deal, and a
fix to the implementation rule lands in both places at once.

The image check scans `images/{subdir}/` once at module load and caches
the (card_type, card_id) -> bool map. Card art is static between server
restarts, so a cold rescan only matters if you drop a new file in and
expect the running server to pick it up — restart the process for that.
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Mirrors `_CARD_IMAGE_DIRS` in `server.py`. Keys are the singular type
# names used as filename prefixes (e.g. `monster_44_gelatinous_cube.jpg`).
# Events live under `images/exhausted/` because the engine renders them
# as Exhausted-stack tokens once revealed.
_CARD_IMAGE_DIRS = {
    "monster": _REPO_ROOT / "images" / "monsters",
    "citizen": _REPO_ROOT / "images" / "citizens",
    "domain":  _REPO_ROOT / "images" / "domains",
    "duke":    _REPO_ROOT / "images" / "dukes",
    "starter": _REPO_ROOT / "images" / "starters",
    "event":   _REPO_ROOT / "images" / "exhausted",
}


def _scan_image_ids(card_type):
    """Return the set of int IDs that have at least one image on disk for `card_type`.

    Filenames follow the convention `{card_type}_{id:02d}_<slug>.<ext>`,
    matching how `/card-image/{kind}/{id}` resolves art at request time.
    """
    found = set()
    dir_path = _CARD_IMAGE_DIRS.get(card_type)
    if not dir_path or not dir_path.is_dir():
        return found
    prefix = f"{card_type}_"
    for f in dir_path.iterdir():
        if f.suffix.lower() not in _IMAGE_EXTS:
            continue
        name = f.name
        if not name.startswith(prefix):
            continue
        # Strip the prefix and pull the digits up to the next underscore.
        rest = name[len(prefix):]
        digits = []
        for ch in rest:
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if not digits:
            continue
        try:
            found.add(int("".join(digits)))
        except ValueError:
            continue
    return found


# Built once on first import and reused. If you add card art while the
# server is running, you'll need to restart for the random preset to see it.
_IMAGE_ID_SETS = {kind: _scan_image_ids(kind) for kind in _CARD_IMAGE_DIRS}


def has_card_image(card_type, card_id):
    """Return True if there is an art file for this `(card_type, card_id)`.

    Mirrors the resolution behaviour of `/card-image/{kind}/{id}` in
    `server.py` (filename prefix `{kind}_{id:02d}_`), but answers the
    question without walking the filesystem on every check.
    """
    if card_id is None:
        return False
    try:
        cid = int(card_id)
    except (TypeError, ValueError):
        return False
    return cid in _IMAGE_ID_SETS.get(card_type, set())


# ── "is this row implemented?" predicates ──────────────────────────────────
#
# Each predicate returns True when the row has a `has_<effect>` boolean set
# but the corresponding text column is NULL or whitespace-only — meaning
# the engine will try to resolve an effect that hasn't been authored yet.
# These are imported by `wiki_data.py` (to render the Unimplemented badge)
# and by `game_setup.py` (to filter the random-preset pool).

def _is_empty_special(value):
    if value is None:
        return True
    return not str(value).strip()


def is_unimplemented_citizen(row):
    if row.get("has_special_payout_on_turn") and _is_empty_special(row.get("special_payout_on_turn")):
        return True
    if row.get("has_special_payout_off_turn") and _is_empty_special(row.get("special_payout_off_turn")):
        return True
    return False


def is_unimplemented_monster(row):
    if row.get("has_special_reward") and _is_empty_special(row.get("special_reward")):
        return True
    if row.get("has_special_cost") and _is_empty_special(row.get("special_cost")):
        return True
    return False


def is_unimplemented_domain(row):
    if row.get("has_passive_effect") and _is_empty_special(row.get("passive_effect")):
        return True
    if row.get("has_activation_effect") and _is_empty_special(row.get("activation_effect")):
        return True
    return False


def is_unimplemented_event(row):
    if row.get("has_roll_effect") and _is_empty_special(row.get("roll_effect")):
        return True
    if row.get("has_activation_effect") and _is_empty_special(row.get("activation_effect")):
        return True
    if row.get("has_passive_effect") and _is_empty_special(row.get("passive_effect")):
        return True
    if row.get("has_special_reward") and _is_empty_special(row.get("special_reward")):
        return True
    return False


# Convenience: pair an implementation predicate + image lookup for each
# card kind. Used by the random preset to filter raw row pools to only
# those a player can actually be dealt and the client can render.

def keep_for_random(card_type, row):
    """True if `row` is implemented AND has an image on disk.

    `card_type` is the singular form used by `_CARD_IMAGE_DIRS`
    (`monster`, `citizen`, `domain`, `duke`, `event`).
    """
    if card_type == "monster":
        if is_unimplemented_monster(row):
            return False
        return has_card_image("monster", row.get("id_monsters"))
    if card_type == "citizen":
        if is_unimplemented_citizen(row):
            return False
        return has_card_image("citizen", row.get("id_citizens"))
    if card_type == "domain":
        if is_unimplemented_domain(row):
            return False
        return has_card_image("domain", row.get("id_domains"))
    if card_type == "event":
        if is_unimplemented_event(row):
            return False
        return has_card_image("event", row.get("id_events"))
    if card_type == "duke":
        # Dukes have no implementation predicate — they are pure stat
        # multipliers and ship implemented. Image-only filter.
        return has_card_image("duke", row.get("id_dukes"))
    return True
