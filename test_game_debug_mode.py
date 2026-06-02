import json
import unittest

from game import Game
from game_models import Player
from game_setup import DEBUG_DIE_ONE_VALUES, DEBUG_DIE_TWO_VALUES


def make_debug_roll_game():
    p1 = Player("p1", "Player 1")
    return Game({
        "game_id": "test-debug-game",
        "player_list": [p1],
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-debug-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "roll",
        "debug_mode": True,
    })


class DebugModeRollTests(unittest.TestCase):
    def test_debug_mode_roll_phase_uses_constrained_dice(self):
        game = make_debug_roll_game()

        self.assertTrue(game.advance_tick())

        self.assertEqual(game.phase, "roll_pending")
        self.assertIn(game.rolled_die_one, DEBUG_DIE_ONE_VALUES)
        self.assertIn(game.rolled_die_two, DEBUG_DIE_TWO_VALUES)
        self.assertEqual(game.rolled_die_sum, game.rolled_die_one + game.rolled_die_two)
        self.assertEqual(game.pending_roll["rolled_die_sum"], game.rolled_die_sum)


class BrokenStateGame:
    phase = "roll"
    shutdown = None
    last_active_time = 0

    def advance_tick(self):
        raise RuntimeError("boom")


class StateEndpointErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_endpoint_returns_json_when_auto_advance_fails(self):
        import server

        server.games["test-broken-game"] = BrokenStateGame()
        try:
            response = await server.get_game_state("test-broken-game", player_id="p1")
        finally:
            server.games.pop("test-broken-game", None)

        self.assertEqual(response.status_code, 500)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["detail"], "State advance failed: boom")
        self.assertEqual(payload["error"], "State advance failed: boom")


if __name__ == "__main__":
    unittest.main()
