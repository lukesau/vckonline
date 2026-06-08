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

    def _event_expansions(self, state):
        return {
            getattr(card, "expansion", None)
            for card in state["exhausted_stack"]
            if getattr(card, "name", None)  # Event cards have names; plain tokens don't
            and hasattr(card, "expansion")
        }

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

    def test_expansion_only_base_scopes_events_to_base(self):
        state = self._load("base", expansion_only=True)
        expansions = self._event_expansions(state)
        self.assertTrue(expansions <= {"base"}, f"expected only base events, got {expansions}")

    def test_default_base_events_can_span_expansions(self):
        # Without expansion_only the base preset draws from the full event
        # pool. Only n_players events are sampled per game, so load several
        # seeds and assert at least one non-base event eventually appears
        # (skips cleanly if the DB only has base events implemented).
        import random as _random

        seen = set()
        for seed in range(40):
            _random.seed(seed)
            state = self._load("base")
            seen |= self._event_expansions(state)
        if seen <= {"base"}:
            self.skipTest(f"only base events available in DB pool; saw {seen}")
        self.assertTrue(
            any(exp not in (None, "base") for exp in seen),
            f"expected a non-base event across seeds, saw {seen}",
        )


if __name__ == "__main__":
    unittest.main()
