import random
import unittest
from types import SimpleNamespace

from monster_area_balance import (
    CURATED_FLEX_COUNTS,
    CURATED_WEIGHTED_RATIOS,
    area_avg_slay_cost,
    flex_totals_for_areas,
    flex_weight_ratios_for_areas,
    pick_balanced_monster_areas,
    pick_random_monster_areas,
)


FLEX_TYPES = ("Minion", "Beast", "Titan")


def _row(area, strength, magic, monster_type="Minion"):
    return {
        "area": area,
        "strength_cost": strength,
        "magic_cost": magic,
        "monster_type": monster_type,
    }


def _stack(*cards):
    return list(cards)


def _area(name, cost, minion=0, beast=0, titan=0):
    cards = []
    for _ in range(minion):
        cards.append(_row(name, cost, 0, "Minion"))
    for _ in range(beast):
        cards.append(_row(name, cost, 0, "Beast"))
    for _ in range(titan):
        cards.append(_row(name, cost, 0, "Titan"))
    cards.append(_row(name, cost, 0, "Warden"))
    cards.append(_row(name, cost, 0, "Boss"))
    return cards


class MonsterAreaBalanceTests(unittest.TestCase):
    def test_area_avg_slay_cost(self):
        cards = [_row("A", 2, 1), _row("A", 4, 3)]
        self.assertEqual(area_avg_slay_cost(cards), 5.0)

    def test_shadowvale_pool_picks_all_five_areas(self):
        grouped = {
            "Sewer": _stack(_row("Sewer", 3, 1, "Beast"), _row("Sewer", 4, 0, "Titan")),
            "Necropolis": _stack(_row("Necropolis", 5, 0, "Minion"), _row("Necropolis", 6, 0, "Beast")),
            "Den": _stack(_row("Den", 6, 2, "Beast"), _row("Den", 7, 1, "Titan")),
            "Woods": _stack(_row("Woods", 7, 2, "Minion"), _row("Woods", 8, 1, "Beast")),
            "Crypt": _stack(_row("Crypt", 9, 1, "Minion"), _row("Crypt", 10, 0, "Titan")),
        }
        rng = random.Random(0)
        picked = pick_balanced_monster_areas(list(grouped), grouped, rng=rng)
        self.assertEqual(set(picked), set(grouped))
        costs = sorted(area_avg_slay_cost(grouped[a]) for a in picked)
        self.assertEqual(costs[0], 4.0)
        self.assertEqual(costs[-1], 10.0)

    def test_balanced_spread_uses_varied_cost_anchors(self):
        grouped = {
            "easy": _stack(_row("easy", 1, 0)),
            "low_mid": _stack(_row("low_mid", 3, 0)),
            "mid": _stack(_row("mid", 5, 0)),
            "high_mid": _stack(_row("high_mid", 7, 0)),
            "hard": _stack(_row("hard", 9, 0)),
            "unused": _stack(_row("unused", 4, 0)),
        }
        costs = {name: area_avg_slay_cost(grouped[name]) for name in grouped}
        pool_min = min(costs.values())
        pool_max = max(costs.values())
        rng = random.Random(1)
        picked = pick_balanced_monster_areas(list(grouped), grouped, rng=rng)
        self.assertEqual(len(picked), 5)
        self.assertEqual(len(set(picked)), 5)
        weak = costs[picked[0]]
        strong = costs[picked[1]]
        self.assertLessEqual(weak, 7.0 + 0.001)
        self.assertGreaterEqual(strong, 8.1 - 0.001)
        self.assertGreater(strong, weak)

    def test_balanced_flex_counts_steer_away_from_beast_heavy_boards(self):
        grouped = {
            "easy": _area("easy", 1, minion=2, beast=1, titan=1),
            "mid_a": _area("mid_a", 5, minion=2, beast=1, titan=1),
            "mid_b": _area("mid_b", 5, minion=2, beast=1, titan=1),
            "mid_c": _area("mid_c", 6, minion=2, beast=1, titan=1),
            "hard": _area("hard", 9, minion=2, beast=1, titan=1),
            "beast_sink": _area("beast_sink", 5, beast=4),
            "beast_sink2": _area("beast_sink2", 6, beast=4),
        }
        areas = list(grouped.keys())
        beast_counts = []
        count_drifts = []
        for seed in range(40):
            picked = pick_balanced_monster_areas(areas, grouped, rng=random.Random(seed))
            counts = flex_totals_for_areas(picked, grouped)
            beast_counts.append(counts["Beast"])
            count_drifts.append(
                sum((counts[t] - CURATED_FLEX_COUNTS[t]) ** 2 for t in FLEX_TYPES)
            )
        self.assertLess(sum(beast_counts) / len(beast_counts), 11.5)
        self.assertLess(sum(count_drifts) / len(count_drifts), 12.0)

    def test_balanced_type_mix_stays_within_soft_bounds(self):
        grouped = {
            "easy": _area("easy", 1, minion=2, beast=1, titan=1),
            "mid_a": _area("mid_a", 5, minion=2, beast=1, titan=1),
            "mid_b": _area("mid_b", 5, minion=2, beast=1, titan=1),
            "mid_c": _area("mid_c", 6, minion=2, beast=1, titan=1),
            "hard": _area("hard", 9, minion=2, beast=1, titan=1),
            "beast_sink": _area("beast_sink", 5, beast=4),
            "beast_sink2": _area("beast_sink2", 6, beast=4),
        }
        areas = list(grouped.keys())

        def _drift(picked):
            ratios = flex_weight_ratios_for_areas(picked, grouped)
            return sum((ratios[t] - CURATED_WEIGHTED_RATIOS[t]) ** 2 for t in ratios)

        for seed in range(30):
            balanced = pick_balanced_monster_areas(areas, grouped, rng=random.Random(seed))
            self.assertEqual(len(balanced), 5)
            self.assertLess(_drift(balanced), 0.25)

    def test_pick_random_monster_areas_for_dealing(self):
        areas = ["a", "b", "c", "d", "e", "f"]
        grouped = {name: _stack(_row(name, i, 0)) for i, name in enumerate(areas)}
        rng = random.Random(3)
        picked = pick_random_monster_areas(areas, rng=rng)
        self.assertEqual(len(picked), 5)
        self.assertEqual(len(set(picked)), 5)

    def test_pick_random_monster_areas_matches_sample(self):
        areas = ["a", "b", "c", "d", "e", "f"]
        rng_a = random.Random(9)
        rng_b = random.Random(9)
        self.assertEqual(
            pick_random_monster_areas(areas, rng=rng_a),
            rng_b.sample(areas, 5),
        )

    def test_works_with_monster_objects(self):
        grouped = {
            "a": [SimpleNamespace(strength_cost=1, magic_cost=0, monster_type="Minion")],
            "b": [SimpleNamespace(strength_cost=3, magic_cost=0, monster_type="Minion")],
            "c": [SimpleNamespace(strength_cost=5, magic_cost=0, monster_type="Minion")],
            "d": [SimpleNamespace(strength_cost=7, magic_cost=0, monster_type="Minion")],
            "e": [SimpleNamespace(strength_cost=9, magic_cost=0, monster_type="Minion")],
        }
        picked = pick_balanced_monster_areas(list(grouped), grouped, rng=random.Random(0))
        costs = {name: float(getattr(grouped[name][0], "strength_cost", 0)) for name in grouped}
        pool_min = min(costs.values())
        pool_max = max(costs.values())
        self.assertLessEqual(costs[picked[0]], 7.0 + 0.001)
        self.assertGreaterEqual(costs[picked[1]], 8.1 - 0.001)
        self.assertGreater(costs[picked[1]], costs[picked[0]])

    def test_balanced_produces_variety_on_large_pool(self):
        grouped = {}
        names = [
            "cheap_a", "cheap_b", "low_a", "low_b", "mid_a", "mid_b",
            "high_a", "high_b", "hard_a", "hard_b",
        ]
        for i, name in enumerate(names):
            cost = 1 + (i // 2) * 2
            grouped[name] = _stack(_row(name, cost, 0))
        areas = list(grouped.keys())

        pool_min = 1 + (0 // 2) * 2
        weak_ceiling = 7.0
        strong_floor = 8.1
        unique_picks = set()
        for seed in range(40):
            picked = pick_balanced_monster_areas(areas, grouped, rng=random.Random(seed))
            self.assertEqual(len(picked), 5)
            weak_cost = 1 + (names.index(picked[0]) // 2) * 2
            strong_cost = 1 + (names.index(picked[1]) // 2) * 2
            self.assertLessEqual(weak_cost, weak_ceiling + 0.001)
            self.assertGreaterEqual(strong_cost, strong_floor - 0.001)
            self.assertGreater(strong_cost, weak_cost)
            unique_picks.add(tuple(sorted(picked)))

        self.assertGreater(len(unique_picks), 1)


if __name__ == "__main__":
    unittest.main()
