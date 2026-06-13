"""Load and cache game preset definitions from `presets/*.json`.

Each preset is a JSON file merged over canonical defaults. Aliases (e.g.
`current` -> `june2026`) deep-copy the target and overlay the alias file's keys.
Configs are loaded once at import time so bad presets fail fast at server start.

Consumers: `game_setup.load_game_data`, `preset_preview.load_preset_preview`,
`server._validate_preset`.
"""
import copy
import json
import os

_PRESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "presets")

_INCLUDE_MODES = frozenset(("never", "always", "random", "draft"))

_DEFAULT_PRESET = {
    "id": None,
    "label": "",
    "short_label": "",
    "lobby_selectable": False,
    "alias": None,
    "monster_query": "select_all_monsters",
    "citizen_query": "select_all_citizens",
    "choose_one_citizen_per_roll": False,
    "domain_query": "select_random_domains",
    "duke_query": "select_random_dukes",
    "event_query": "select_all_events",
    "monster_expansion_filters": None,
    "citizen_expansion_filters": None,
    "domain_expansion_filters": None,
    "duke_expansion_filters": None,
    "event_expansion_filters": None,
    "exclude_domain_expansions": [],
    "guaranteed_domain_expansion": None,
    "fixed_citizen_ids": None,
    "fixed_monster_areas": None,
    "optional_starter_expansion": None,
    "apply_implemented_image_filter": False,
    "draft": False,
    "include_agents": "never",
    "include_relics": "never",
    "expansion_only": None,
}

# Raw entries keyed by preset id (before alias resolution).
_RAW_PRESETS = {}

# Fully resolved configs keyed by preset id (aliases resolved, no expansion_only applied).
_RESOLVED = {}


def _normalize_raw(data, source_path):
    """Merge JSON data over defaults and validate shape."""
    if not isinstance(data, dict):
        raise ValueError(f"{source_path}: preset must be a JSON object")
    explicit_keys = set(data.keys())
    preset_id = (data.get("id") or "").strip()
    if not preset_id:
        raise ValueError(f"{source_path}: preset must have a non-empty 'id'")
    cfg = copy.deepcopy(_DEFAULT_PRESET)
    cfg.update(data)
    cfg["id"] = preset_id
    cfg["_explicit_keys"] = explicit_keys
    for key in ("include_agents", "include_relics"):
        mode = str(cfg.get(key) or "never").strip().lower()
        if mode not in _INCLUDE_MODES:
            raise ValueError(
                f"{source_path}: '{key}' must be one of {sorted(_INCLUDE_MODES)}, got {mode!r}"
            )
        cfg[key] = mode
    for key in (
        "monster_expansion_filters",
        "citizen_expansion_filters",
        "domain_expansion_filters",
        "duke_expansion_filters",
        "event_expansion_filters",
        "exclude_domain_expansions",
    ):
        val = cfg.get(key)
        if val is None:
            continue
        if not isinstance(val, list):
            raise ValueError(f"{source_path}: '{key}' must be a list or null")
        cfg[key] = list(val)
    for key in ("fixed_citizen_ids", "fixed_monster_areas"):
        val = cfg.get(key)
        if val is None:
            continue
        if not isinstance(val, list):
            raise ValueError(f"{source_path}: '{key}' must be a list or null")
        cfg[key] = list(val)
    eo = cfg.get("expansion_only")
    if eo is not None and not isinstance(eo, dict):
        raise ValueError(f"{source_path}: 'expansion_only' must be an object or null")
    alias = cfg.get("alias")
    if alias is not None:
        alias = str(alias).strip().lower()
        if not alias:
            alias = None
        cfg["alias"] = alias
    return cfg


def _load_all_presets():
    if not os.path.isdir(_PRESETS_DIR):
        raise FileNotFoundError(f"Presets directory not found: {_PRESETS_DIR}")
    raw = {}
    for name in sorted(os.listdir(_PRESETS_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(_PRESETS_DIR, name)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cfg = _normalize_raw(data, path)
        pid = cfg["id"]
        if pid in raw:
            raise ValueError(f"Duplicate preset id {pid!r} in {path}")
        raw[pid] = cfg
    if not raw:
        raise ValueError(f"No preset JSON files found in {_PRESETS_DIR}")
    return raw


def _resolve_preset(preset_id, raw, resolved, stack=None):
    """Resolve one preset (follow alias chain), caching in `resolved`."""
    preset_id = (preset_id or "").strip().lower()
    if preset_id in resolved:
        return resolved[preset_id]
    if preset_id not in raw:
        raise ValueError(f"Unknown preset: {preset_id}")
    stack = list(stack or [])
    if preset_id in stack:
        raise ValueError(f"Preset alias cycle: {' -> '.join(stack + [preset_id])}")
    entry = raw[preset_id]
    alias = entry.get("alias")
    if alias:
        if alias not in raw:
            raise ValueError(f"Preset {preset_id!r} aliases unknown preset {alias!r}")
        base = _resolve_preset(alias, raw, resolved, stack + [preset_id])
        cfg = copy.deepcopy(base)
        explicit = entry.get("_explicit_keys") or set()
        for key in explicit:
            if key in ("alias", "_explicit_keys"):
                continue
            val = entry[key]
            cfg[key] = copy.deepcopy(val) if isinstance(val, (dict, list)) else val
        cfg["id"] = preset_id
        cfg["alias"] = alias
        explicit = set(explicit) | {"id", "alias"}
        cfg["_explicit_keys"] = explicit
    else:
        cfg = copy.deepcopy(entry)
    resolved[preset_id] = cfg
    return cfg


def _build_registry():
    global _RAW_PRESETS, _RESOLVED
    _RAW_PRESETS = _load_all_presets()
    _RESOLVED = {}
    for pid in _RAW_PRESETS:
        _resolve_preset(pid, _RAW_PRESETS, _RESOLVED)


def _apply_expansion_only(cfg, expansion_only):
    if not expansion_only:
        return cfg
    overrides = cfg.get("expansion_only")
    if not overrides:
        return cfg
    out = copy.deepcopy(cfg)
    for key, val in overrides.items():
        if isinstance(val, list):
            out[key] = list(val)
        else:
            out[key] = val
    return out


def _public_config(cfg):
    out = copy.deepcopy(cfg)
    out.pop("_explicit_keys", None)
    return out


def get_preset_config(preset_id, expansion_only=False):
    """Return the deal/preview config for `preset_id`.

    Applies `expansion_only` overrides when the lobby flag is set. Raises
    ValueError for unknown presets (matches legacy `match _` behavior).
    """
    pid = (preset_id or "").strip().lower()
    if pid not in _RESOLVED:
        raise ValueError(f"Unknown game data preset: {preset_id}")
    cfg = _public_config(_RESOLVED[pid])
    return _apply_expansion_only(cfg, expansion_only)


def preset_label(preset_id):
    pid = (preset_id or "").strip().lower()
    if pid not in _RESOLVED:
        return preset_id or ""
    label = (_RESOLVED[pid].get("label") or "").strip()
    return label or pid


def preset_short_label(preset_id):
    pid = (preset_id or "").strip().lower()
    if pid not in _RESOLVED:
        return preset_id or ""
    short = (_RESOLVED[pid].get("short_label") or "").strip()
    return short or preset_label(pid)


def lobby_selectable_presets():
    """Preset ids allowed in the lobby dropdown / `_validate_preset`."""
    ids = [pid for pid, cfg in sorted(_RESOLVED.items()) if cfg.get("lobby_selectable")]
    return tuple(ids)


def include_agents_mode(preset_id):
    pid = (preset_id or "").strip().lower()
    if pid not in _RESOLVED:
        return "never"
    return _RESOLVED[pid].get("include_agents") or "never"


def include_relics_mode(preset_id):
    pid = (preset_id or "").strip().lower()
    if pid not in _RESOLVED:
        return "never"
    return _RESOLVED[pid].get("include_relics") or "never"


def all_preset_ids():
    return tuple(sorted(_RESOLVED.keys()))


_build_registry()
