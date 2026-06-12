import unittest
from types import SimpleNamespace

from server import (
    _clear_game_rejoin_codes,
    _init_game_rejoin_codes,
    _mint_rejoin_code,
    _normalize_rejoin_code,
    game_rejoin_registry,
)


class TestRejoinCodes(unittest.TestCase):
    def test_normalize_strips_and_uppercases(self):
        self.assertEqual(_normalize_rejoin_code("blue-fox-42"), "BLUEFOX42")
        self.assertEqual(_normalize_rejoin_code(" BLUE FOX 42 "), "BLUEFOX42")

    def test_mint_unique_codes(self):
        taken = set()
        a, ka = _mint_rejoin_code(taken)
        b, kb = _mint_rejoin_code(taken)
        taken.add(ka)
        self.assertNotEqual(ka, kb)
        self.assertIn("-", a)
        self.assertEqual(ka, _normalize_rejoin_code(a))

    def test_init_game_rejoin_codes_per_player(self):
        game_id = "test-game-rejoin"
        _clear_game_rejoin_codes(game_id)
        game = SimpleNamespace(
            player_list=[
                SimpleNamespace(player_id="p1"),
                SimpleNamespace(player_id="p2"),
            ]
        )
        _init_game_rejoin_codes(game_id, game)
        reg = game_rejoin_registry.get(game_id)
        self.assertIsNotNone(reg)
        self.assertEqual(len(reg["by_player"]), 2)
        self.assertEqual(len(reg["by_code"]), 2)
        for pid, display in reg["by_player"].items():
            key = _normalize_rejoin_code(display)
            self.assertEqual(reg["by_code"][key], pid)
        _clear_game_rejoin_codes(game_id)


if __name__ == "__main__":
    unittest.main()
