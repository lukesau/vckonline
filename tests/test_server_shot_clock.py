"""Display-only action shot clock (no auto-play)."""

import time
import unittest

import server
from game import Game
from game_models import Player


def _make_action_phase_game(game_id):
    p1 = Player("p1", "Player 1")
    p2 = Player("p2", "Player 2")
    return Game({
        "game_id": game_id,
        "player_list": [p1, p2],
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "p1", "action": "standard_action"},
        "game_log": [],
        "turn_index": 0,
        "phase": "action",
        "actions_remaining": 2,
    })


class ShotClockTests(unittest.TestCase):
    def test_arms_during_standard_action(self):
        game = _make_action_phase_game("sc-1")
        self.assertTrue(server._shot_clock_should_run(game))

    def test_off_during_payment_prompt(self):
        game = _make_action_phase_game("sc-2")
        game.action_required = {"id": "p1", "action": "build_domain_payment"}
        self.assertFalse(server._shot_clock_should_run(game))

    def test_serialized_remaining_never_negative(self):
        game = _make_action_phase_game("sc-3")
        game.hurry_up_deadline = time.time() - 30
        state = server._serialize_game_for_player(game, "p1")
        self.assertEqual(state["hurry_up_seconds_remaining"], 0.0)

    def test_reset_arms_fresh_deadline(self):
        game = _make_action_phase_game("sc-4")
        server.games["sc-4"] = game
        try:
            before = time.time()
            server._shot_clock_reset("sc-4")
            self.assertGreater(game.hurry_up_deadline, before)
        finally:
            server.games.pop("sc-4", None)


if __name__ == "__main__":
    unittest.main()
