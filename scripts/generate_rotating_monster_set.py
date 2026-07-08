"""Generate balanced 5-area monster sets for rotating presets.

Balance targets come from the creator-authored expansion sets (base1, shadowvale,
crimsonseas, flamesandfrost). By default this draws from the full monster pool
(select_all_monsters). Output is meant for paste into a preset JSON as
`fixed_monster_areas` (board order, weak -> strong by face-up top card).

Usage:
    python3 scripts/generate_rotating_monster_set.py
    python3 scripts/generate_rotating_monster_set.py --seed 42 --count 5
    python3 scripts/generate_rotating_monster_set.py --pool implemented
    python3 scripts/generate_rotating_monster_set.py --preset shadowvale --count 5
    python3 scripts/generate_rotating_monster_set.py --json
    python3 scripts/generate_rotating_monster_set.py -o reports/rotating_set.txt

Requires the venv + database (see docs/setup.md).
"""

import argparse
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mariadb

from game_setup import _filter_monster_areas_for_random, _sort_monster_areas_by_top_card_cost
from monster_area_balance import (
    CURATED_WEIGHTED_RATIOS,
    area_avg_slay_cost,
    area_flex_type_counts,
    flex_totals_for_areas,
    flex_weight_ratios_for_areas,
    pick_balanced_monster_areas,
)
from preset_registry import get_preset_config

from db_config import DB_CONFIG

FLEX_TYPES = ("Minion", "Beast", "Titan")


def _load_monster_pool(pool_mode, n_players, preset_id=None, expansion_only=False):
    """Load grouped monsters for set generation.

    pool_mode:
      full — every monster area (select_all_monsters, default for rotating sets)
      implemented — random-lobby filter (implemented specials + card art)
    preset_id — optional; when set, use that preset's monster_query / expansion
      filters instead of pool_mode (e.g. shadowvale for a 5-area expansion pool).
    """
    if preset_id:
        cfg = get_preset_config(preset_id, expansion_only=expansion_only)
        pool_label = f"preset {preset_id}"
    elif pool_mode == "implemented":
        cfg = get_preset_config("random", expansion_only=expansion_only)
        pool_label = "implemented (random lobby filter)"
    else:
        cfg = {
            "monster_query": "select_all_monsters",
            "monster_expansion_filters": None,
            "apply_implemented_image_filter": False,
            "label": "full monster pool",
        }
        pool_label = "full monster pool"

    monster_query = cfg["monster_query"]
    monster_expansion_filters = cfg.get("monster_expansion_filters")
    apply_filter = bool(cfg.get("apply_implemented_image_filter"))

    conn = mariadb.connect(**DB_CONFIG)
    try:
        cur = conn.cursor(dictionary=True)
        if monster_expansion_filters:
            placeholders = ", ".join(["%s"] * len(monster_expansion_filters))
            cur.execute(
                f"SELECT * FROM monsters WHERE expansion IN ({placeholders})",
                tuple(monster_expansion_filters),
            )
            rows = cur.fetchall()
        else:
            cur.callproc(monster_query)
            rows = cur.fetchall()
    finally:
        conn.close()

    if apply_filter:
        rows = _filter_monster_areas_for_random(rows, n_players)

    grouped = {}
    include_extra = n_players == 5
    for row in rows:
        if not include_extra and row.get("is_extra"):
            continue
        grouped.setdefault(row["area"], []).append(dict(row))
    for area in grouped:
        grouped[area].sort(key=lambda r: int(r.get("monster_order", 0)))
    return grouped, cfg, pool_label


def _grouped_as_monster_objects(grouped):
    from types import SimpleNamespace

    out = {}
    for area, rows in grouped.items():
        stack = []
        for row in rows:
            stack.append(SimpleNamespace(
                strength_cost=row.get("strength_cost", 0),
                magic_cost=row.get("magic_cost", 0),
                order=int(row.get("monster_order", 0)),
            ))
        stack.sort(key=lambda m: m.order, reverse=True)
        out[area] = stack
    return out


def _format_type_counts(counts):
    parts = []
    for monster_type in FLEX_TYPES:
        n = int(counts.get(monster_type, 0))
        if n:
            parts.append(f"{monster_type[:1]}{n}")
    return " ".join(parts) if parts else "-"


def _format_ratio_line(ratios):
    parts = []
    for monster_type in FLEX_TYPES:
        parts.append(f"{monster_type[:1]} {100 * ratios[monster_type]:.0f}%")
    return ", ".join(parts)


def _describe_set(index, board_order, grouped):
    lines = [f"Set {index}", "-" * 60]
    lines.append(f"Board order (weak -> strong): {' -> '.join(board_order)}")
    lines.append("")
    lines.append(f"{'Area':<18} {'AvgCost':>7}  Types")
    for area in board_order:
        cards = grouped[area]
        avg = area_avg_slay_cost(cards)
        types = area_flex_type_counts(cards)
        lines.append(f"{area:<18} {avg:7.2f}  {_format_type_counts(types)}")
    counts = flex_totals_for_areas(board_order, grouped)
    ratios = flex_weight_ratios_for_areas(board_order, grouped)
    lines.append("")
    lines.append(
        f"Board flex counts: Minion {counts['Minion']}, Beast {counts['Beast']}, Titan {counts['Titan']}"
    )
    lines.append(f"Board slay-weighted mix: {_format_ratio_line(ratios)}")
    target = ", ".join(
        f"{t[:1]} {100 * CURATED_WEIGHTED_RATIOS[t]:.0f}%"
        for t in FLEX_TYPES
    )
    lines.append(f"Curated soft target:     {target}")
    lines.append("")
    lines.append('"fixed_monster_areas": ' + json.dumps(list(board_order)) + ",")
    lines.append("")
    return lines


def generate_sets(pool_mode, n_players, count, seed, preset_id=None, expansion_only=False):
    grouped, cfg, pool_label = _load_monster_pool(
        pool_mode, n_players, preset_id=preset_id, expansion_only=expansion_only,
    )
    areas = list(grouped.keys())
    if len(areas) < 5:
        raise SystemExit(
            f"Only {len(areas)} eligible areas for {pool_label!r} "
            f"({n_players} players). Need at least 5."
        )

    rng = random.Random(seed)
    sortable = _grouped_as_monster_objects(grouped)
    lines = [
        "Rotating monster set generator",
        "=" * 60,
        f"Pool: {pool_label} ({len(areas)} areas, {n_players} players)",
        f"Sets: {count}",
        f"Seed: {seed if seed is not None else '(random)'}",
        "",
    ]

    unique_boards = set()
    board_orders = []
    for _ in range(count):
        picked = pick_balanced_monster_areas(areas, grouped, rng=rng)
        board_order = _sort_monster_areas_by_top_card_cost(picked, sortable)
        board_orders.append(board_order)
        unique_boards.add(tuple(board_order))

    if count > 1:
        lines.append(f"Unique board orders in this run: {len(unique_boards)} / {count}")
        lines.append("")

    for i, board_order in enumerate(board_orders, 1):
        lines.extend(_describe_set(i, board_order, grouped))

    return "\n".join(lines).rstrip() + "\n", board_orders


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool",
        choices=("full", "implemented"),
        default="full",
        help="Monster pool: all areas (default) or random-lobby implemented filter",
    )
    parser.add_argument(
        "--preset",
        default=None,
        help="Optional preset for a narrowed pool (e.g. shadowvale = 5 expansion areas)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="How many candidate sets to generate (default: 3)",
    )
    parser.add_argument(
        "--players",
        type=int,
        default=4,
        choices=(2, 3, 4, 5),
        help="Player count for is_extra filtering (default: 4)",
    )
    parser.add_argument(
        "--expansion-only",
        action="store_true",
        help="Apply expansion_only overlay when loading the preset pool",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for reproducible output (default: random)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print only the first set as a JSON array (board order)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Write full report to this file (default: stdout)",
    )
    args = parser.parse_args()
    if args.count < 1:
        raise SystemExit("--count must be at least 1")

    seed = args.seed if args.seed is not None else random.randint(0, 2**31 - 1)
    report, board_orders = generate_sets(
        args.pool,
        args.players,
        args.count,
        seed,
        preset_id=args.preset,
        expansion_only=args.expansion_only,
    )

    if args.json:
        output = json.dumps(list(board_orders[0])) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
            print(f"Wrote {args.output} (seed={seed})")
        else:
            print(output, end="")
        return

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output} ({len(report)} bytes, seed={seed})")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
