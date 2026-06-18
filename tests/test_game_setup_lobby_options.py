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

    def test_rotating_preset_uses_fixed_areas_and_citizens(self):
        from game_setup import JUNE_2026_MONSTER_AREAS, JUNE_2026_CITIZEN_IDS

        for preset in ("june2026", "current"):
            state = self._load(preset)
            board_areas = set(state["monster_stack_areas"]) - {"Undead Samurai"}
            self.assertEqual(board_areas, set(JUNE_2026_MONSTER_AREAS))
            dealt_citizen_ids = {
                int(stack[0].citizen_id)
                for stack in state["citizen_grid"]
                if stack
            }
            self.assertEqual(dealt_citizen_ids, set(JUNE_2026_CITIZEN_IDS))

    def test_rotating_preset_excludes_crimson_seas_domains(self):
        state = self._load("current")
        for domain in self._board_domains(state):
            self.assertNotEqual(domain.expansion, "crimsonseas")

    def test_expansion_only_base_scopes_dukes_to_base(self):
        state = self._load("base", expansion_only=True)
        for player in state["player_list"]:
            for duke in player.owned_dukes:
                self.assertEqual(duke.expansion, "base")

    def test_expansion_only_base_scopes_domains_to_base(self):
        state = self._load("base", expansion_only=True)
        domains = self._board_domains(state)
        self.assertTrue(domains, "expected domains on the board")
        for domain in domains:
            self.assertEqual(domain.expansion, "base")

    def test_expansion_only_base_scopes_events_to_base(self):
        state = self._load("base", expansion_only=True)
        expansions = self._event_expansions(state)
        self.assertTrue(expansions <= {"base"}, f"expected only base events, got {expansions}")

    def test_default_base_domains_can_span_expansions(self):
        # Without expansion_only the base preset draws domains from the same
        # all-playable pool as the expansion presets. Only 15 domains are dealt
        # per game, so load several seeds and assert a non-base domain appears
        # eventually (skips cleanly if the DB only has base domains available).
        import random as _random

        seen = set()
        for seed in range(40):
            _random.seed(seed)
            state = self._load("base")
            seen |= {domain.expansion for domain in self._board_domains(state)}
        if seen <= {"base"}:
            self.skipTest(f"only base domains available in DB pool; saw {seen}")
        self.assertTrue(
            any(exp not in (None, "base") for exp in seen),
            f"expected a non-base domain across seeds, saw {seen}",
        )

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

    def _load_with_players(self, preset, players, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_game_data(f"lobby-opt-{preset}", preset, players, **kwargs)

    @staticmethod
    def _crimson_domain_count(domains):
        return sum(1 for d in domains if d.expansion == "crimsonseas")

    def test_crimsonseas_all_deals_every_crimson_domain_plus_random_fill(self):
        # "All" mode (expansion_only off): all 10 Crimson Seas domains, then
        # 5 more (2-4 players) drawn from the full implemented pool.
        state = self._load("crimsonseas")
        domains = self._board_domains(state)
        self.assertEqual(len(domains), 15)
        self.assertEqual(self._crimson_domain_count(domains), 10)

    def test_crimsonseas_all_fill_can_span_expansions(self):
        # The 5 (or 10) fill slots come from the whole implemented pool, so a
        # non-crimson, non-base domain should eventually appear across seeds.
        import random as _random

        fill_expansions = set()
        for seed in range(40):
            _random.seed(seed)
            state = self._load("crimsonseas")
            fill_expansions |= {
                d.expansion for d in self._board_domains(state) if d.expansion != "crimsonseas"
            }
        if fill_expansions <= {"base"}:
            self.skipTest(f"only base domains available to fill; saw {fill_expansions}")
        self.assertTrue(
            any(exp not in (None, "base", "crimsonseas") for exp in fill_expansions),
            f"expected a non-base fill domain across seeds, saw {fill_expansions}",
        )

    def test_crimsonseas_expansion_fills_remaining_from_base_only(self):
        # "Expansion" mode: all 10 Crimson Seas domains, remaining 5 from base.
        state = self._load("crimsonseas", expansion_only=True)
        domains = self._board_domains(state)
        self.assertEqual(len(domains), 15)
        self.assertEqual(self._crimson_domain_count(domains), 10)
        for d in domains:
            self.assertIn(d.expansion, ("crimsonseas", "base"))

    def test_crimsonseas_five_players_deals_twenty_domains(self):
        players = [LobbyMember(f"Player {i}", f"p{i}") for i in range(1, 6)]
        for expansion_only in (False, True):
            state = self._load_with_players(
                "crimsonseas", players, expansion_only=expansion_only
            )
            domains = self._board_domains(state)
            self.assertEqual(len(domains), 20)
            self.assertEqual(self._crimson_domain_count(domains), 10)
            if expansion_only:
                for d in domains:
                    self.assertIn(d.expansion, ("crimsonseas", "base"))

    def test_crimsonseas_expansion_only_scopes_events_to_crimsonseas(self):
        state = self._load("crimsonseas", expansion_only=True)
        expansions = self._event_expansions(state)
        self.assertTrue(
            expansions <= {"crimsonseas"},
            f"expected only crimsonseas events, got {expansions}",
        )

    def test_crimsonseas_all_events_can_span_expansions(self):
        import random as _random

        seen = set()
        for seed in range(40):
            _random.seed(seed)
            state = self._load("crimsonseas")
            seen |= self._event_expansions(state)
        if seen <= {"crimsonseas"}:
            self.skipTest(f"only crimsonseas events available in DB pool; saw {seen}")
        self.assertTrue(
            any(exp not in (None, "crimsonseas") for exp in seen),
            f"expected a non-crimsonseas event across seeds, saw {seen}",
        )

    def test_crimsonseas_dukes_use_full_pool_both_modes(self):
        # Crimson Seas ships no dukes, so both modes draw from the full pool.
        import random as _random

        for expansion_only in (False, True):
            seen = set()
            for seed in range(20):
                _random.seed(seed)
                state = self._load("crimsonseas", expansion_only=expansion_only)
                for player in state["player_list"]:
                    seen |= {duke.expansion for duke in player.owned_dukes}
            self.assertTrue(
                any(exp not in (None, "base") for exp in seen),
                f"expected dukes beyond base (expansion_only={expansion_only}), saw {seen}",
            )


if __name__ == "__main__":
    unittest.main()
