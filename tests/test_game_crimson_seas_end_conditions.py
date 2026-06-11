"""Crimson Seas: three new end-game conditions.

The rulebook adds three end conditions to the Crimson Seas game: it ends if a
Goods, Tome, or Noble slot row "must be replenished, but there are not enough
tokens to fill in all 3 slots." After a take, an unfillable slot is left empty
(None), so a falsy entry in a 3-slot row means a required replenish could not
complete. These checks are scoped to the Crimson Seas preset.
"""

import unittest

from cards import Domain, Monster, Noble
from game import Game
from game_models import Player


def make_monster():
    return Monster(
        1, "Goblin", 1, "Minion", 1,
        1, 0, 1, 0, 0, 0,
        False, "", False, "",
        False, "crimsonseas",
    )


def make_domain():
    d = Domain(1, "Keep", 5, 0, 0, 0, 0, 0, False, False, "", "", "", "crimsonseas")
    d.toggle_visibility(True)
    d.toggle_accessibility(True)
    return d


def make_noble(noble_id, name):
    return Noble(
        noble_id, name, 0, 0, 1, 0,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0, "", "crimsonseas",
    )


def make_game(*, goods=None, tomes=None, nobles=None, goods_supply=None,
              preset="crimsonseas", gold=10, map_score=3):
    """Build a Crimson Seas game with one live monster + domain (so the only
    reachable end condition is the supply-exhaustion one under test)."""
    p1 = Player("p1", "Player 1")
    p1.gold_score = gold
    p1.strength_score = 10
    p1.magic_score = 10
    p1.victory_score = 0
    p1.map_score = map_score
    p2 = Player("p2", "Player 2")
    state = {
        "game_id": "test-game",
        "player_list": [p1, p2],
        "monster_grid": [[make_monster()], [], [], [], []],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": [[make_domain()], [], [], [], []],
        "die_one": 1, "die_two": 2, "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "turn_number": 1,
        "phase": "action",
        "actions_remaining": 3,
        "preset": preset,
        "goods_slots": goods if goods is not None else [],
        "goods_supply": goods_supply if goods_supply is not None else [],
        "tome_slots": tomes if tomes is not None else [],
        "noble_slots": nobles if nobles is not None else [],
    }
    return Game(state), p1


FULL_GOODS = ["jewels", "spices", "fabrics"]
FULL_TOMES = ["gold", "strength", "magic"]


def full_nobles():
    return [make_noble(1, "A"), make_noble(2, "B"), make_noble(3, "C")]


class CrimsonSeasEndConditionTests(unittest.TestCase):
    def test_full_board_has_no_supply_end_condition(self):
        game, _ = make_game(goods=FULL_GOODS, tomes=FULL_TOMES, nobles=full_nobles())
        self.assertIsNone(game.endgame._check_end_game_condition())

    def test_unfillable_goods_slot_ends_game(self):
        game, _ = make_game(goods=[None, "spices", "fabrics"], tomes=FULL_TOMES, nobles=full_nobles())
        self.assertEqual(game.endgame._check_end_game_condition(), "goods supply exhausted")

    def test_unfillable_tome_slot_ends_game(self):
        game, _ = make_game(goods=FULL_GOODS, tomes=["gold", None, "magic"], nobles=full_nobles())
        self.assertEqual(game.endgame._check_end_game_condition(), "tome supply exhausted")

    def test_unfillable_noble_slot_ends_game(self):
        game, _ = make_game(goods=FULL_GOODS, tomes=FULL_TOMES,
                            nobles=[make_noble(1, "A"), make_noble(2, "B"), None])
        self.assertEqual(game.endgame._check_end_game_condition(), "noble supply exhausted")

    def test_non_crimson_preset_ignores_empty_slots(self):
        # Outside Crimson Seas these slot rows are unused, so even an explicitly
        # empty row must not end the game.
        game, _ = make_game(goods=[None, None, None], tomes=[None, None, None],
                            nobles=[None, None, None], preset="base")
        self.assertIsNone(game.endgame._check_end_game_condition())

    def test_buy_goods_with_empty_supply_triggers_end_condition(self):
        # Integration: a real purchase that forces an unfillable refill leaves a
        # None slot, which the end-game check then detects.
        game, p = make_game(goods=list(FULL_GOODS), goods_supply=[],
                            tomes=FULL_TOMES, nobles=full_nobles())
        self.assertIsNone(game.endgame._check_end_game_condition())
        game.player_actions.buy_goods("p1", [2], gp=2)
        self.assertIn(None, game.goods_slots)
        self.assertEqual(game.endgame._check_end_game_condition(), "goods supply exhausted")


if __name__ == "__main__":
    unittest.main()
