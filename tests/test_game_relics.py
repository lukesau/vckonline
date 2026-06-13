"""Tests for the optional Relics module: inclusion gating, dealing, and the
post-duke relic-selection concurrent gate.

These mirror the Agents tests (`tests/test_game_agents.py`). The selection-flow
tests build minimal in-memory games and need no DB; the dealing tests load
canonical relic rows from the live DB and skip when the tunnel is down."""

import contextlib
import importlib.util
import io
import socket
import unittest
from unittest.mock import patch

from cards import Duke, Relic
from game import Game
from game_models import LobbyMember, Player
from game_serialization import (
    serialize_game_to_save_dict,
    deserialize_save_dict_to_game,
)
from game_setup import (
    load_game_data,
    _should_include_relics,
    _relic_count_per_player,
)


def _db_ready():
    if importlib.util.find_spec("mariadb") is None:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        return sock.connect_ex(("127.0.0.1", 3306)) == 0
    finally:
        sock.close()


def _make_duke(duke_id, name="Duke"):
    return Duke(duke_id, name, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "base")


def _make_relic(relic_id, name="Relic"):
    return Relic(relic_id, name, None, f"{name} power text.")


def _make_setup_game(*, relics_per_player=2, dukes_per_player=2, include_relics=True,
                     n_players=2):
    """A fresh game sitting in setup with each player holding several dukes and
    (optionally) relics, so Game.__init__ opens the choose_duke gate."""
    players = []
    for i in range(1, n_players + 1):
        p = Player(f"p{i}", f"Player {i}")
        p.owned_dukes = [_make_duke(100 * i + j, f"Duke{i}-{j}") for j in range(dukes_per_player)]
        p.owned_relics = [_make_relic(10 * i + j, f"Relic{i}-{j}") for j in range(relics_per_player)]
        players.append(p)
    return Game({
        "game_id": "relics-setup",
        "preset": "base",
        "include_relics": include_relics,
        "player_list": players,
        "monster_grid": [[] for _ in range(5)],
        "monster_stack_areas": [],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": [[] for _ in range(5)],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
        "action_required": {"id": "relics-setup", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "setup",
        "actions_remaining": 0,
    })


class ShouldIncludeRelicsTests(unittest.TestCase):
    def test_debug_non_crimsonseas_includes(self):
        self.assertTrue(_should_include_relics("base", debug_mode=True))
        self.assertTrue(_should_include_relics("random", debug_mode=True))

    def test_debug_crimsonseas_excludes(self):
        self.assertFalse(_should_include_relics("crimsonseas", debug_mode=True))

    def test_draft_follows_vote(self):
        self.assertTrue(_should_include_relics("draft", draft_selections={"include_relics": True}))
        self.assertFalse(_should_include_relics("draft", draft_selections={"include_relics": False}))
        self.assertFalse(_should_include_relics("draft", draft_selections={}))

    def test_draft_relics_independent_of_agents(self):
        # An agents-yes vote must not implicitly enable relics.
        self.assertFalse(_should_include_relics("draft", draft_selections={"include_agents": True}))

    @patch("game_setup.random.random", return_value=0.1)
    def test_random_includes_on_low_roll(self, _mock):
        self.assertTrue(_should_include_relics("random"))

    @patch("game_setup.random.random", return_value=0.9)
    def test_random_excludes_on_high_roll(self, _mock):
        self.assertFalse(_should_include_relics("random"))

    def test_base_preset_excludes(self):
        self.assertFalse(_should_include_relics("base"))


class RelicCountPerPlayerTests(unittest.TestCase):
    def test_matches_duke_count_below_five_players(self):
        self.assertEqual(_relic_count_per_player(2, 2), 2)
        self.assertEqual(_relic_count_per_player(3, 4), 3)
        self.assertEqual(_relic_count_per_player(3, 4, available_relics=12), 3)

    def test_falls_back_to_two_when_bans_make_three_impossible(self):
        self.assertEqual(_relic_count_per_player(3, 4, available_relics=11), 2)
        self.assertEqual(_relic_count_per_player(3, 3, available_relics=8), 2)

    def test_capped_at_two_for_five_players(self):
        self.assertEqual(_relic_count_per_player(3, 5), 2)
        self.assertEqual(_relic_count_per_player(2, 5), 2)
        self.assertEqual(_relic_count_per_player(3, 5, available_relics=9), 0)

    def test_disables_when_less_than_two_each_available(self):
        self.assertEqual(_relic_count_per_player(3, 4, available_relics=7), 0)


class RelicSelectionFlowTests(unittest.TestCase):
    def test_relic_gate_opens_after_duke_selection(self):
        game = _make_setup_game()
        self.assertEqual(game.concurrent_action.get("kind"), "choose_duke")

        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")

        # Duke selection done -> relic selection is now the active gate.
        self.assertIsNotNone(game.concurrent_action)
        self.assertEqual(game.concurrent_action.get("kind"), "choose_relic")
        self.assertEqual(set(game.concurrent_action.get("pending")), {"p1", "p2"})

    def test_keeping_one_relic_discards_the_rest(self):
        game = _make_setup_game(relics_per_player=2)
        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")

        keep_ids = {}
        for p in game.player_list:
            keep = p.owned_relics[1]
            keep_ids[p.player_id] = keep.relic_id
            game.submit_concurrent_action(p.player_id, str(keep.relic_id), kind="choose_relic")

        self.assertIsNone(game.concurrent_action)
        for p in game.player_list:
            self.assertEqual(len(p.owned_relics), 1)
            self.assertEqual(p.owned_relics[0].relic_id, keep_ids[p.player_id])

    def test_invalid_relic_choice_rejected(self):
        game = _make_setup_game()
        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")
        with self.assertRaises(ValueError):
            game.submit_concurrent_action("p1", "99999", kind="choose_relic")

    def test_no_relic_gate_when_module_disabled(self):
        game = _make_setup_game(include_relics=False, relics_per_player=0)
        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")
        # No relics dealt -> no relic gate; setup proceeds.
        self.assertIsNone(game.concurrent_action)

    def test_save_load_round_trip_across_relic_gate(self):
        game = _make_setup_game()
        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")
        # Mid relic-selection: persist and rehydrate.
        reloaded = deserialize_save_dict_to_game(serialize_game_to_save_dict(game))
        self.assertTrue(reloaded.include_relics)
        self.assertTrue(reloaded.relics_enabled())
        self.assertEqual(reloaded.concurrent_action.get("kind"), "choose_relic")
        for p in reloaded.player_list:
            self.assertEqual(len(p.owned_relics), 2)
        for p in reloaded.player_list:
            reloaded.submit_concurrent_action(p.player_id, str(p.owned_relics[0].relic_id), kind="choose_relic")
        self.assertIsNone(reloaded.concurrent_action)


@unittest.skipUnless(
    _db_ready(),
    "requires active DB tunnel and mariadb module; run source ./activate_with_env.sh first",
)
class RelicsSetupIntegrationTests(unittest.TestCase):
    def _players(self, n):
        return [LobbyMember(f"Player {i}", f"p{i}") for i in range(1, n + 1)]

    def _load(self, preset, players, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_game_data(f"relics-setup-{preset}", preset, players, **kwargs)

    def test_debug_base_deals_relics(self):
        state = self._load("base", self._players(2), debug_mode=True, duke_select_count=2)
        self.assertTrue(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 2)

    def test_duke_count_three_deals_three_relics(self):
        state = self._load("base", self._players(2), debug_mode=True, duke_select_count=3)
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 3)

    def test_five_players_capped_at_two_relics(self):
        state = self._load("base", self._players(5), debug_mode=True, duke_select_count=3)
        self.assertTrue(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 2)

    @patch("game_setup.banned_relic_ids", return_value={1, 2})
    def test_four_players_with_relic_bans_falls_back_to_two(self, _mock):
        state = self._load("base", self._players(4), debug_mode=True, duke_select_count=3)
        self.assertTrue(state.get("include_relics"))
        seen_ids = set()
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 2)
            seen_ids |= {r.relic_id for r in player.owned_relics}
        self.assertNotIn(1, seen_ids)
        self.assertNotIn(2, seen_ids)

    def test_debug_crimsonseas_skips_relics(self):
        state = self._load("crimsonseas", self._players(2), debug_mode=True)
        self.assertFalse(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 0)

    def test_base_without_debug_skips_relics(self):
        state = self._load("base", self._players(2), debug_mode=False)
        self.assertFalse(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 0)

    @patch("game_setup.random.random", return_value=0.1)
    def test_random_includes_relics(self, _mock):
        state = self._load("random", self._players(2))
        self.assertTrue(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 2)


if __name__ == "__main__":
    unittest.main()
