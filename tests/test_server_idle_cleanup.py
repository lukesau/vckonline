"""Idle-game pruning based on real client audience."""

import time
import unittest

import server
from game import Game
from game_models import Player


def _make_idle_test_game(game_id):
    p1 = Player("p1", "Player 1")
    p2 = Player("p2", "Player 2")
    game = Game({
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
        "action_required": {"id": "p1", "action": "build_domain_payment"},
        "game_log": [],
        "turn_index": 10,
        "phase": "action",
        "actions_remaining": 1,
    })
    server._touch_game_audience(game)
    return game


class PruneIdleGamesTests(unittest.TestCase):
    def test_prunes_game_with_stale_audience(self):
        game = _make_idle_test_game("idle-1")
        game.last_audience_time = time.time() - server._GAME_IDLE_TIMEOUT_S - 10
        game.last_active_time = time.time()
        server.games["idle-1"] = game
        try:
            removed = server._prune_idle_games(now=time.time())
            self.assertEqual(removed, ["idle-1"])
            self.assertNotIn("idle-1", server.games)
        finally:
            server.games.pop("idle-1", None)

    def test_keeps_game_with_recent_audience(self):
        game = _make_idle_test_game("idle-2")
        server.games["idle-2"] = game
        try:
            removed = server._prune_idle_games(now=time.time())
            self.assertEqual(removed, [])
            self.assertIn("idle-2", server.games)
        finally:
            server.games.pop("idle-2", None)

    def test_prunes_game_stuck_on_prompt_without_audience(self):
        game = _make_idle_test_game("idle-3")
        game.last_audience_time = time.time() - server._GAME_IDLE_TIMEOUT_S - 1
        server.games["idle-3"] = game
        try:
            removed = server._prune_idle_games(now=time.time())
            self.assertEqual(removed, ["idle-3"])
        finally:
            server.games.pop("idle-3", None)


class TouchAudienceTests(unittest.TestCase):
    def test_player_in_game_check(self):
        game = _make_idle_test_game("idle-4")
        self.assertTrue(server._player_in_game(game, "p1"))
        self.assertFalse(server._player_in_game(game, "p9"))


if __name__ == "__main__":
    unittest.main()
