import unittest

from cards import Citizen
from game import Game
from game_models import Player


def make_wizard(citizen_id=100):
    citizen = Citizen(
        citizen_id,
        "Wizard",
        4,
        6,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        0,
        False,
        False,
        "",
        "",
        False,
        "test",
    )
    citizen.toggle_visibility(True)
    citizen.toggle_accessibility(True)
    return citizen


def make_game(player, citizen):
    return Game({
        "game_id": "test-game",
        "player_list": [player],
        "monster_grid": [],
        "citizen_grid": [[citizen]],
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


class CitizenCostTests(unittest.TestCase):
    def test_flipped_duplicate_citizen_does_not_increase_hire_cost(self):
        player = Player("p1", "Player 1")
        player.gold_score = 4
        owned_wizard = make_wizard(1)
        player.owned_citizens.append(owned_wizard)
        target_wizard = make_wizard(2)
        game = make_game(player, target_wizard)
        game._citizen_set_flipped(owned_wizard, True)

        game.hire_citizen(player.player_id, target_wizard.citizen_id, gp=4)

        self.assertEqual(player.gold_score, 0)
        self.assertEqual(len(player.owned_citizens), 2)
        self.assertEqual(game.citizen_grid[0], [])

    def test_face_up_duplicate_citizen_still_increases_hire_cost(self):
        player = Player("p1", "Player 1")
        player.gold_score = 4
        player.owned_citizens.append(make_wizard(1))
        target_wizard = make_wizard(2)
        game = make_game(player, target_wizard)

        with self.assertRaises(ValueError):
            game.hire_citizen(player.player_id, target_wizard.citizen_id, gp=4)


if __name__ == "__main__":
    unittest.main()
