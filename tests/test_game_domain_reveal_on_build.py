"""Building a Domain reveals the next card in the stack immediately.

Base-rules step 5 of the Build a Domain action: "Reveal the next Domain by
flipping it over if there is still a Domain card in the stack." The reveal
happens as the final step of the action, not deferred to the End Phase.
"""

import unittest

from game import Game
from game_models import Player
from tests.test_game_giants_of_ostendaar import make_domain


def make_game(n_players=2):
    players = []
    for i in range(n_players):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 20
        p.strength_score = 20
        p.magic_score = 20
        p.victory_score = 0
        players.append(p)
    game = Game({
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [[], [], [], [], []],
        "citizen_grid": [[], [], [], [], [], [], [], [], [], []],
        "domain_grid": [[], [], [], [], []],
        "die_one": 1, "die_two": 2, "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "action",
        "actions_remaining": 2,
    })
    return game, players


class DomainRevealOnBuildTests(unittest.TestCase):
    def test_building_top_reveals_next_domain_immediately(self):
        game, players = make_game()
        buried = make_domain(201, "Buried Keep")            # dealt face-down
        top = make_domain(202, "Top Keep", visible=True)
        game.domain_grid[0].extend([buried, top])

        self.assertFalse(buried.is_visible)
        self.assertFalse(buried.is_accessible)

        game.build_domain(players[0].player_id, 202, gp=3)

        # The previously buried domain is now the face-up, accessible top —
        # without waiting for the End Phase.
        self.assertEqual(game.domain_grid[0], [buried])
        self.assertTrue(buried.is_visible)
        self.assertTrue(buried.is_accessible)
        self.assertEqual(game.player_list[0].owned_domains[-1].domain_id, 202)

    def test_building_last_domain_leaves_empty_stack_without_exhausted(self):
        game, players = make_game()
        only = make_domain(202, "Only Keep", visible=True)
        game.domain_grid[0].append(only)

        game.build_domain(players[0].player_id, 202, gp=3)

        self.assertEqual(game.domain_grid[0], [])


if __name__ == "__main__":
    unittest.main()
