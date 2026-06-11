"""Tests for Tabula Tower (Domain #76).

Passive effect: `action.end manipulate_resources mode=self_convert pay=g:1
gain=p:1 optional=true` - "At the end of your Action Phase, you may exchange
1 Gold for 1 Map."
"""

import unittest

from cards import Domain
from game import Game
from game_models import Player


def make_tabula_tower():
    return Domain(
        76, "Tabula Tower", 11,
        2, 0, 0, 1,                       # role requirements
        3,                                # vp_reward
        False, True,                      # has_activation / has_passive
        "action.end manipulate_resources mode=self_convert pay=g:1 gain=p:1 optional=true",
        None,
        "At the end of your Action Phase, you may exchange 1 Gold for 1 Map.",
        "crimsonseas",
    )


def make_game(*, gold=2, map_score=0, turn_number=5):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = gold
        p.strength_score = 0
        p.magic_score = 0
        p.victory_score = 0
        p.map_score = map_score
        players.append(p)
    state = {
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [[], [], [], [], []],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": [[], [], [], [], []],
        "die_one": 1, "die_two": 2, "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": players[0].player_id, "action": "standard_action"},
        "game_log": [],
        "turn_index": 0,
        "turn_number": turn_number,
        "phase": "action",
        "actions_remaining": 0,
        "preset": "crimsonseas",
    }
    return Game(state), players


class TabulaTowerTests(unittest.TestCase):
    def test_end_of_action_opens_optional_gold_for_map_trade(self):
        game, players = make_game(gold=2, map_score=0)
        p = players[0]
        p.owned_domains = [make_tabula_tower()]

        game.finish_turn_if_no_actions_remaining()

        self.assertEqual(game.phase, "action_end_pending")
        self.assertEqual(game.action_required.get("id"), p.player_id)
        self.assertEqual(game.action_required.get("action"), "domain_self_convert")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "domain_self_convert")
        self.assertEqual(prc.get("domain_name"), "Tabula Tower")
        self.assertEqual(prc.get("context"), "action_end_queue")
        self.assertEqual(prc.get("kv", {}).get("pay"), "g:1")
        self.assertEqual(prc.get("kv", {}).get("gain"), "p:1")

    def test_confirm_trades_one_gold_for_one_map(self):
        game, players = make_game(gold=2, map_score=0)
        p = players[0]
        p.owned_domains = [make_tabula_tower()]
        game.finish_turn_if_no_actions_remaining()

        game.act_on_required_action(p.player_id, "confirm_self_convert")

        self.assertEqual(int(p.gold_score), 1)
        self.assertEqual(int(p.map_score), 1)
        self.assertEqual(p.harvest_delta.get("gold"), -1)
        self.assertEqual(p.harvest_delta.get("map"), 1)
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("action"), "")

    def test_decline_keeps_resources(self):
        game, players = make_game(gold=2, map_score=0)
        p = players[0]
        p.owned_domains = [make_tabula_tower()]
        game.finish_turn_if_no_actions_remaining()

        game.act_on_required_action(p.player_id, "skip")

        self.assertEqual(int(p.gold_score), 2)
        self.assertEqual(int(p.map_score), 0)
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("action"), "")

    def test_insufficient_gold_skips_prompt(self):
        game, players = make_game(gold=0, map_score=0)
        players[0].owned_domains = [make_tabula_tower()]

        game.finish_turn_if_no_actions_remaining()

        self.assertNotEqual(game.action_required.get("action"), "domain_self_convert")
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(int(players[0].map_score), 0)

    def test_build_turn_cooldown_skips_prompt(self):
        game, players = make_game(gold=2, map_score=0, turn_number=5)
        dom = make_tabula_tower()
        dom.acquired_turn_number = 5
        players[0].owned_domains = [dom]

        game.finish_turn_if_no_actions_remaining()

        self.assertNotEqual(game.action_required.get("action"), "domain_self_convert")
        self.assertIsNone(game.pending_required_choice)

    def test_turn_after_build_opens_prompt(self):
        game, players = make_game(gold=2, map_score=0, turn_number=5)
        dom = make_tabula_tower()
        dom.acquired_turn_number = 4
        players[0].owned_domains = [dom]

        game.finish_turn_if_no_actions_remaining()

        self.assertEqual(game.action_required.get("action"), "domain_self_convert")


if __name__ == "__main__":
    unittest.main()
