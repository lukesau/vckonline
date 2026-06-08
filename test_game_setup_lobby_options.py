"""Tests for lobby-driven game setup options (duke count, expansion-only pools)."""

import contextlib
import importlib.util
import io
import socket
import unittest

from game_models import LobbyMember
from game_setup import load_game_data


def _db_ready():
    if importlib.util.find_spec("mariadb") is None:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        return sock.connect_ex(("127.0.0.1", 3306)) == 0
    finally:
        sock.close()


class DukeSelectCountValidationTests(unittest.TestCase):
    def test_rejects_invalid_duke_select_count(self):
        players = [LobbyMember("Player 1", "p1")]
        with self.assertRaises(ValueError):
            load_game_data("bad-duke-count", "base", players, duke_select_count=4)


@unittest.skipUnless(
    _db_ready(),
    "requires active DB tunnel and mariadb module; run source ./activate_with_env.sh first",
)
class LobbyOptionsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.players = [
            LobbyMember("Player 1", "p1"),
            LobbyMember("Player 2", "p2"),
        ]

    def _load(self, preset, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_game_data(f"lobby-opt-{preset}", preset, self.players, **kwargs)

    def _board_domains(self, state):
        domains = []
        for stack in state["domain_grid"]:
            domains.extend(stack)
        return domains

    def test_duke_select_count_three_deals_three_per_player(self):
        state = self._load("base", duke_select_count=3)
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_dukes), 3)

    def test_expansion_only_flamesandfrost_scopes_domains_and_dukes(self):
        state = self._load("flamesandfrost", expansion_only=True)
        domains = self._board_domains(state)
        self.assertTrue(domains, "expected domains on the board")
        for domain in domains:
            self.assertEqual(domain.expansion, "flamesandfrost")
        for player in state["player_list"]:
            for duke in player.owned_dukes:
                self.assertIn(duke.expansion, ("base", "flamesandfrost"))

    def test_expansion_only_base_scopes_dukes_to_base(self):
        state = self._load("base", expansion_only=True)
        for player in state["player_list"]:
            for duke in player.owned_dukes:
                self.assertEqual(duke.expansion, "base")


if __name__ == "__main__":
    unittest.main()
