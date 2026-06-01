import unittest

from cards import Monster
from game import Game
from game_models import Player


def make_gold_golem():
    monster = Monster(
        54,
        "Gold Golem",
        "Ruins",
        "Construct",
        1,
        7,
        3,
        5,
        0,
        0,
        0,
        False,
        "",
        False,
        "",
        False,
        "base",
    )
    monster.toggle_visibility(True)
    monster.toggle_accessibility(True)
    return monster


def make_game(player, monster):
    return Game({
        "game_id": "test-game",
        "player_list": [player],
        "monster_grid": [[monster]],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 1,
        "die_sum": 2,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
    })


class MonsterPaymentTests(unittest.TestCase):
    def test_mixed_strength_magic_monster_payment_accepts_magic_above_minimum_as_wild(self):
        player = Player("p1", "Player 1")
        player.strength_score = 1
        player.magic_score = 9
        monster = make_gold_golem()
        game = make_game(player, monster)

        game.slay_monster(player.player_id, monster.monster_id, 1, 9, 0)

        self.assertEqual(player.strength_score, 0)
        self.assertEqual(player.magic_score, 0)
        self.assertEqual(player.owned_monsters[0].name, "Gold Golem")
        self.assertEqual(game.monster_grid[0], [])

    def test_event_added_gold_slay_cost_requires_exact_gold(self):
        player = Player("p1", "Player 1")
        player.gold_score = 1
        player.strength_score = 7
        player.magic_score = 3
        monster = make_gold_golem()
        monster.extra_gold_cost = 1
        game = make_game(player, monster)

        game.slay_monster(player.player_id, monster.monster_id, 7, 3, 1)

        self.assertEqual(player.gold_score, 0)
        self.assertEqual(player.strength_score, 0)
        self.assertEqual(player.magic_score, 0)
        self.assertEqual(player.owned_monsters[0].name, "Gold Golem")

    def test_immediate_slay_options_include_event_added_costs(self):
        player = Player("p1", "Player 1")
        monster = make_gold_golem()
        monster.extra_gold_cost = 1
        monster.extra_strength_cost = 2
        monster.extra_magic_cost = 1
        game = make_game(player, monster)

        options = game.slay._immediate_slay_monster_options()

        self.assertEqual(options[0]["gold_cost"], 1)
        self.assertEqual(options[0]["strength_cost"], 9)
        self.assertEqual(options[0]["magic_cost"], 4)


if __name__ == "__main__":
    unittest.main()
