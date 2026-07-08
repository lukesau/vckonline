"""Generate a text report summarizing each monster area in the database.

Usage:
    python3 scripts/monster_area_report.py
    python3 scripts/monster_area_report.py -o reports/monster_areas.txt

Requires the venv + database (see docs/setup.md).
"""

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import mariadb

DB_CONFIG = {
    "user": "vckonline",
    "password": "vckonline",
    "host": "127.0.0.1",
    "port": 3306,
    "database": "vckonline",
}

MONSTER_TYPES = ("Minion", "Titan", "Warden", "Boss", "Beast")
FLEX_TYPES = ("Minion", "Beast", "Titan")
CURATED_EXPANSIONS = ("base1", "shadowvale", "crimsonseas", "flamesandfrost")
BASIC_REWARDS = (
    ("vp_reward", "Victory Points"),
    ("gold_reward", "Gold"),
    ("strength_reward", "Strength"),
    ("magic_reward", "Magic"),
)


def _reward_label(row):
    if row.get("has_special_reward"):
        text = (row.get("special_reward_text") or "").strip()
        if text:
            return text
        raw = (row.get("special_reward") or "").strip()
        if raw:
            return raw
    return None


def _card_slay_cost(row):
    return int(row.get("strength_cost") or 0) + int(row.get("magic_cost") or 0)


def _flex_counts_and_weights(cards):
    counts = Counter()
    weights = Counter()
    costs_by_type = defaultdict(list)
    for row in cards:
        monster_type = row.get("monster_type")
        if monster_type not in FLEX_TYPES:
            continue
        cost = _card_slay_cost(row)
        counts[monster_type] += 1
        weights[monster_type] += cost
        costs_by_type[monster_type].append(cost)
    return counts, weights, costs_by_type


def _avg_slay_cost_by_flex_type(costs_by_type):
    avgs = {}
    for monster_type in FLEX_TYPES:
        costs = costs_by_type.get(monster_type) or []
        if costs:
            avgs[monster_type] = sum(costs) / len(costs)
    return avgs


def _format_avg_slay_cost_by_type(avgs):
    if not avgs:
        return "n/a", "n/a"
    present = [t for t in FLEX_TYPES if t in avgs]
    by_type = ", ".join(f"{t} {avgs[t]:.2f}" for t in present)
    if len(present) < 2:
        return by_type, "n/a"
    anchor_type = "Minion" if "Minion" in avgs else present[0]
    anchor = avgs[anchor_type]
    ratio = ", ".join(f"{t} {avgs[t] / anchor:.2f}" for t in present)
    return by_type, f"{anchor_type}=1: {ratio}"


def _flex_mix_parts(type_counts):
    flex_total = sum(int(type_counts.get(t, 0)) for t in FLEX_TYPES)
    if flex_total <= 0:
        return "n/a"
    parts = []
    for monster_type in FLEX_TYPES:
        count = int(type_counts.get(monster_type, 0))
        if count:
            pct = 100.0 * count / flex_total
            parts.append(f"{monster_type} {pct:.0f}%")
    return ", ".join(parts) if parts else "n/a"


def _weighted_flex_mix_parts(weights):
    flex_total = sum(float(weights.get(t, 0) or 0) for t in FLEX_TYPES)
    if flex_total <= 0:
        return "n/a"
    parts = []
    for monster_type in FLEX_TYPES:
        weight = float(weights.get(monster_type, 0) or 0)
        if weight:
            pct = 100.0 * weight / flex_total
            parts.append(f"{monster_type} {pct:.0f}%")
    return ", ".join(parts) if parts else "n/a"


def _format_type_summary(type_counts, flex_weights, costs_by_type):
    flex_parts = []
    for monster_type in FLEX_TYPES:
        count = int(type_counts.get(monster_type, 0))
        if count:
            flex_parts.append(f"{monster_type} {count}")
    fixed_parts = []
    for monster_type in ("Warden", "Boss"):
        count = int(type_counts.get(monster_type, 0))
        if count:
            fixed_parts.append(f"{monster_type} {count}")
    avgs = _avg_slay_cost_by_flex_type(costs_by_type)
    avg_line, ratio_line = _format_avg_slay_cost_by_type(avgs)
    lines = []
    lines.append(
        "  Flex (Minion/Beast/Titan): "
        + (", ".join(flex_parts) if flex_parts else "(none)")
    )
    lines.append(
        "  Fixed (Warden/Boss): "
        + (", ".join(fixed_parts) if fixed_parts else "(none)")
    )
    lines.append(f"  Flex mix (count): {_flex_mix_parts(type_counts)}")
    lines.append(f"  Flex mix (slay-weighted): {_weighted_flex_mix_parts(flex_weights)}")
    lines.append(f"  Avg slay cost by flex type: {avg_line}")
    lines.append(f"  Avg slay cost ratio: {ratio_line}")
    return lines


def _expansion_benchmark_section(rows):
    lines = [
        "Curated expansion flex-type benchmarks (2-4 player stacks, excl. is_extra)",
        "=" * 72,
    ]
    combined = Counter()
    combined_weights = Counter()
    combined_costs_by_type = defaultdict(list)
    combined_areas = 0
    for expansion in CURATED_EXPANSIONS:
        by_area = defaultdict(list)
        for row in rows:
            if row.get("expansion") != expansion or row.get("is_extra"):
                continue
            by_area[row["area"]].append(row)
        if not by_area:
            continue
        totals = Counter()
        weights = Counter()
        costs_by_type = defaultdict(list)
        for cards in by_area.values():
            counts, area_weights, area_costs = _flex_counts_and_weights(cards)
            totals.update(counts)
            weights.update(area_weights)
            for monster_type, type_costs in area_costs.items():
                costs_by_type[monster_type].extend(type_costs)
        flex = {t: int(totals.get(t, 0)) for t in FLEX_TYPES}
        flex_total = sum(flex.values())
        weight_total = sum(weights.values())
        combined.update(flex)
        combined_weights.update(weights)
        for monster_type, type_costs in costs_by_type.items():
            combined_costs_by_type[monster_type].extend(type_costs)
        combined_areas += len(by_area)
        avgs = _avg_slay_cost_by_flex_type(costs_by_type)
        avg_line, ratio_line = _format_avg_slay_cost_by_type(avgs)
        lines.append(f"{expansion} ({len(by_area)} areas)")
        lines.append(
            f"  Board flex totals: Minion {flex['Minion']}, Beast {flex['Beast']}, Titan {flex['Titan']}"
        )
        if flex_total:
            lines.append(
                "  Flex mix (count): "
                + ", ".join(
                    f"{t} {100.0 * flex[t] / flex_total:.0f}%"
                    for t in FLEX_TYPES
                )
            )
        if weight_total:
            lines.append(
                "  Flex mix (slay-weighted): "
                + ", ".join(
                    f"{t} {100.0 * weights[t] / weight_total:.0f}%"
                    for t in FLEX_TYPES
                )
            )
        lines.append(f"  Avg slay cost by flex type: {avg_line}")
        lines.append(f"  Avg slay cost ratio: {ratio_line}")
        per_area = {
            t: flex[t] / len(by_area) for t in FLEX_TYPES
        }
        lines.append(
            "  Per area avg count: "
            + ", ".join(f"{t} {per_area[t]:.2f}" for t in FLEX_TYPES)
        )
        lines.append("")
    if combined_areas:
        flex_total = sum(combined.values())
        weight_total = sum(combined_weights.values())
        combined_avgs = _avg_slay_cost_by_flex_type(combined_costs_by_type)
        combined_avg_line, combined_ratio_line = _format_avg_slay_cost_by_type(combined_avgs)
        lines.append(f"Combined across {combined_areas} curated areas")
        lines.append(
            f"  Board flex totals: Minion {combined['Minion']}, Beast {combined['Beast']}, "
            f"Titan {combined['Titan']}"
        )
        lines.append(
            f"  Per 5-area board avg count: Minion {combined['Minion'] / (combined_areas / 5):.1f}, "
            f"Beast {combined['Beast'] / (combined_areas / 5):.1f}, "
            f"Titan {combined['Titan'] / (combined_areas / 5):.1f}"
        )
        if flex_total:
            lines.append(
                "  Flex mix (count): "
                + ", ".join(
                    f"{t} {100.0 * combined[t] / flex_total:.1f}%"
                    for t in FLEX_TYPES
                )
            )
        if weight_total:
            lines.append(
                "  Flex mix (slay-weighted): "
                + ", ".join(
                    f"{t} {100.0 * combined_weights[t] / weight_total:.1f}%"
                    for t in FLEX_TYPES
                )
            )
            lines.append(
                "  (Balanced rotating-set soft target: slay-weighted mix above)"
            )
        lines.append(f"  Avg slay cost by flex type: {combined_avg_line}")
        lines.append(f"  Avg slay cost ratio: {combined_ratio_line}")
        lines.append("")

    all_costs_by_type = defaultdict(list)
    all_counts = Counter()
    all_weights = Counter()
    for row in rows:
        if row.get("is_extra"):
            continue
        monster_type = row.get("monster_type")
        if monster_type not in FLEX_TYPES:
            continue
        cost = _card_slay_cost(row)
        all_counts[monster_type] += 1
        all_weights[monster_type] += cost
        all_costs_by_type[monster_type].append(cost)
    all_flex_total = sum(all_counts.values())
    all_weight_total = sum(all_weights.values())
    all_avgs = _avg_slay_cost_by_flex_type(all_costs_by_type)
    all_avg_line, all_ratio_line = _format_avg_slay_cost_by_type(all_avgs)
    lines.append("All playable flex monsters (every area, excl. is_extra)")
    lines.append(
        f"  Totals: Minion {all_counts['Minion']}, Beast {all_counts['Beast']}, "
        f"Titan {all_counts['Titan']} ({all_flex_total} cards)"
    )
    if all_flex_total:
        lines.append(
            "  Flex mix (count): "
            + ", ".join(
                f"{t} {100.0 * all_counts[t] / all_flex_total:.1f}%"
                for t in FLEX_TYPES
            )
        )
    if all_weight_total:
        lines.append(
            "  Flex mix (slay-weighted): "
            + ", ".join(
                f"{t} {100.0 * all_weights[t] / all_weight_total:.1f}%"
                for t in FLEX_TYPES
            )
        )
    lines.append(f"  Avg slay cost by flex type: {all_avg_line}")
    lines.append(f"  Avg slay cost ratio: {all_ratio_line}")
    lines.append("")
    return lines


def _load_monsters(cur):
    cur.execute(
        """
        SELECT area, expansion, monster_type, strength_cost, magic_cost,
               vp_reward, gold_reward, strength_reward, magic_reward,
               has_special_reward, special_reward, special_reward_text, is_extra
        FROM monsters
        ORDER BY area, monster_order
        """
    )
    return cur.fetchall()


def build_report(rows):
    playable_rows = [row for row in rows if not row.get("is_extra")]
    by_area = defaultdict(list)
    for row in playable_rows:
        by_area[row["area"]].append(row)

    lines = list(_expansion_benchmark_section(rows))
    for area in sorted(by_area):
        cards = by_area[area]
        n = len(cards)
        expansion = cards[0].get("expansion") or ""
        avg_strength = sum(int(c["strength_cost"] or 0) for c in cards) / n
        avg_magic = sum(int(c["magic_cost"] or 0) for c in cards) / n

        avg_rewards = {}
        for field, _label in BASIC_REWARDS:
            avg_rewards[field] = sum(int(c[field] or 0) for c in cards) / n

        type_counts = Counter(c["monster_type"] for c in cards)
        _, flex_weights, costs_by_type = _flex_counts_and_weights(cards)
        type_parts = []
        for t in MONSTER_TYPES:
            count = type_counts.get(t, 0)
            if count:
                type_parts.append(f"{t}: {count}")
        for t, count in sorted(type_counts.items()):
            if t not in MONSTER_TYPES:
                type_parts.append(f"{t}: {count}")

        rewards = []
        seen = set()
        for c in cards:
            label = _reward_label(c)
            if label and label not in seen:
                seen.add(label)
                rewards.append(label)

        lines.append("=" * 72)
        lines.append(f"{area} ({expansion})")
        lines.append("-" * 72)
        lines.append(f"Cards: {n}")
        lines.append(f"Avg strength cost: {avg_strength:.2f}")
        lines.append(f"Avg magic cost:    {avg_magic:.2f}")
        lines.append("Avg basic rewards:")
        for field, label in BASIC_REWARDS:
            lines.append(f"  {label:16} {avg_rewards[field]:.2f}")
        lines.append(f"Types: {', '.join(type_parts) if type_parts else '(none)'}")
        lines.append("Type summary:")
        lines.extend(_format_type_summary(type_counts, flex_weights, costs_by_type))
        lines.append("Special rewards:")
        if rewards:
            for r in rewards:
                lines.append(f"  - {r}")
        else:
            lines.append("  (none)")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Write report to this file (default: stdout only)",
    )
    args = parser.parse_args()

    conn = mariadb.connect(**DB_CONFIG)
    try:
        cur = conn.cursor(dictionary=True)
        report = build_report(_load_monsters(cur))
    finally:
        conn.close()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Wrote {args.output} ({len(report)} bytes)")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
