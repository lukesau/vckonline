import unittest
from types import SimpleNamespace

from game_setup import _sort_monster_areas_by_top_card_cost


def _monster_top(strength_cost, magic_cost):
    return SimpleNamespace(strength_cost=strength_cost, magic_cost=magic_cost)


class MonsterStackOrderTests(unittest.TestCase):
    def test_orders_stacks_by_top_strength_then_magic(self):
        chosen_areas = ["mountains", "forest", "swamp", "tundra", "desert"]
        grouped_monsters = {
            # Top card is always stack[-1], matching game setup behavior.
            "mountains": [_monster_top(8, 1)],
            "forest": [_monster_top(3, 2)],
            "swamp": [_monster_top(3, 0)],
            "tundra": [_monster_top(6, 5)],
            "desert": [_monster_top(6, 1)],
        }

        ordered = _sort_monster_areas_by_top_card_cost(chosen_areas, grouped_monsters)

        self.assertEqual(ordered, ["swamp", "forest", "desert", "tundra", "mountains"])


if __name__ == "__main__":
    unittest.main()
