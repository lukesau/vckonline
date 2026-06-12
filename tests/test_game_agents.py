"""Tests for the Agents optional module (setup gating + engage/recycle)."""

import contextlib
import importlib.util
import io
import socket
import unittest
from unittest.mock import patch

from cards import Agent
from game import Game
from game_models import LobbyMember, Player
from game_setup import (
    AGENT_SLOT_COUNT,
    _should_include_agents,
    load_game_data,
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


def _make_action_game(agents_slots, agents_deck=None, player_resources=None):
    p1 = Player("p1", "Player 1")
    if player_resources:
        for k, v in player_resources.items():
            setattr(p1, k, v)
    return Game({
        "game_id": "test-agents",
        "preset": "base",
        "include_agents": True,
        "player_list": [p1],
        "monster_grid": [[] for _ in range(5)],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": [[] for _ in range(5)],
        "agents_slots": list(agents_slots),
        "agents_deck": list(agents_deck or []),
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
        "action_required": {"id": "p1", "action": "standard_action"},
        "game_log": [],
        "turn_index": 0,
        "phase": "action",
        "actions_remaining": 2,
    })


class ShouldIncludeAgentsTests(unittest.TestCase):
    def test_debug_non_crimsonseas_includes(self):
        self.assertTrue(_should_include_agents("base", debug_mode=True))
        self.assertTrue(_should_include_agents("random", debug_mode=True))

    def test_debug_crimsonseas_excludes(self):
        self.assertFalse(_should_include_agents("crimsonseas", debug_mode=True))

    def test_draft_follows_vote(self):
        self.assertTrue(_should_include_agents("draft", draft_selections={"include_agents": True}))
        self.assertFalse(_should_include_agents("draft", draft_selections={"include_agents": False}))
        self.assertFalse(_should_include_agents("draft", draft_selections={}))

    @patch("game_setup.random.random", return_value=0.1)
    def test_random_includes_on_low_roll(self, _mock):
        self.assertTrue(_should_include_agents("random"))

    @patch("game_setup.random.random", return_value=0.9)
    def test_random_excludes_on_high_roll(self, _mock):
        self.assertFalse(_should_include_agents("random"))

    def test_base_preset_excludes(self):
        self.assertFalse(_should_include_agents("base"))


@unittest.skipUnless(
    _db_ready(),
    "requires active DB tunnel and mariadb module; run source ./activate_with_env.sh first",
)
class AgentsSetupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.players = [LobbyMember("Player 1", "p1"), LobbyMember("Player 2", "p2")]

    def _load(self, preset, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_game_data(f"agents-setup-{preset}", preset, self.players, **kwargs)

    def test_debug_base_deals_agents(self):
        state = self._load("base", debug_mode=True)
        self.assertTrue(state.get("include_agents"))
        self.assertEqual(len(state.get("agents_slots") or []), AGENT_SLOT_COUNT)
        self.assertTrue(len(state.get("agents_deck") or []) > 0)

    def test_debug_crimsonseas_skips_agents(self):
        state = self._load("crimsonseas", debug_mode=True)
        self.assertFalse(state.get("agents_slots"))
        self.assertFalse(state.get("agents_deck"))

    @patch("game_setup.random.random", return_value=0.1)
    def test_random_includes_agents(self, _mock):
        state = self._load("random")
        self.assertTrue(state.get("include_agents"))
        self.assertEqual(len(state.get("agents_slots") or []), AGENT_SLOT_COUNT)

    def test_base_without_debug_skips_agents(self):
        state = self._load("base", debug_mode=False)
        self.assertFalse(state.get("include_agents"))
        self.assertFalse(state.get("agents_slots"))


class EngageAgentTests(unittest.TestCase):
    def _captain(self):
        return Agent(
            6, "Captain",
            "manipulate_resources mode=self_convert pay=s:10 gain=v:5",
            "Pay 10 Strength to gain 5 Victory Points.",
        )

    def _stub(self):
        return Agent(1, "Abbot", None, "Not implemented.")

    def test_unaffordable_engage_rejected(self):
        game = _make_action_game([self._captain()], player_resources={"strength_score": 5})
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_unimplemented_engage_rejected(self):
        game = _make_action_game([self._stub()], player_resources={"strength_score": 100})
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_captain_pays_and_recycles(self):
        captain = self._captain()
        next_agent = Agent(7, "Prefect", "manipulate_resources mode=self_convert pay=m:10 gain=v:5", "")
        deck = [next_agent]
        game = _make_action_game([captain], deck, player_resources={
            "strength_score": 10,
            "gold_score": 0,
            "magic_score": 0,
            "victory_score": 0,
        })

        game.engage_agent("p1", 0)

        p1 = game.player_list[0]
        self.assertEqual(p1.strength_score, 0)
        self.assertEqual(p1.victory_score, 5)
        self.assertIs(game.agents_slots[0], next_agent)
        self.assertEqual(game.agents_deck[0], captain)
        self.assertEqual(len(game.agents_deck), 1)

    def test_treasurer_pays_gold(self):
        treasurer = Agent(
            15, "Treasurer",
            "manipulate_resources mode=self_convert pay=g:10 gain=v:5",
            "Pay 10 Gold to gain 5 Victory Points.",
        )
        replacement = Agent(99, "Replacement", None, "")
        game = _make_action_game([treasurer], [replacement], player_resources={
            "gold_score": 10,
            "strength_score": 0,
            "magic_score": 0,
            "victory_score": 0,
        })
        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 0)
        self.assertEqual(p1.victory_score, 5)


if __name__ == "__main__":
    unittest.main()
