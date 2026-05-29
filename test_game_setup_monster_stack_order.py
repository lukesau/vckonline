import unittest
from types import SimpleNamespace

from game_setup import _sort_monster_areas_by_top_card_cost


def _monster_top(strength_cost, magic_cost):
    return SimpleNamespace(strength_cost=strength_cost, magic_cost=magic_cost)


class MonsterStackOrderTests(unittest.TestCase):
    def test_orders_stacks_by_other_end_strength_plus_magic(self):
        chosen_areas = ["mountains", "forest", "swamp", "tundra", "desert"]
        grouped_monsters = {
            # Ordering uses stack[0] (the opposite end from the face-up board top).
            "mountains": [_monster_top(1, 0), _monster_top(8, 1)],
            "forest": [_monster_top(3, 2)],
            "swamp": [_monster_top(3, 0)],
            "tundra": [_monster_top(6, 5)],
            "desert": [_monster_top(2, 1), _monster_top(6, 1)],
        }

        ordered = _sort_monster_areas_by_top_card_cost(chosen_areas, grouped_monsters)

        self.assertEqual(set(ordered), set(chosen_areas))
        self.assertLess(ordered.index("mountains"), ordered.index("swamp"))
        self.assertLess(ordered.index("mountains"), ordered.index("desert"))
        self.assertLess(ordered.index("swamp"), ordered.index("forest"))
        self.assertLess(ordered.index("desert"), ordered.index("forest"))
        self.assertLess(ordered.index("forest"), ordered.index("tundra"))


if __name__ == "__main__":
    unittest.main()
