"""Tests for Murat Reis (Domain #73).

Passive: "During your Action Phase, ignore +Wild cost when rescuing a Noble."
Rescuing a Noble normally costs `9 + (nobles already in your tableau)` of one
resource type (+ 1 map). Murat Reis waives that per-Noble "+Wild" surcharge so
the owner always pays a flat 9 — the noble-rescue analog of Emerald Stronghold's
citizen `+` waiver. Subject to the recurring-passive build-turn cooldown.
"""

import unittest

from cards import Domain, Noble
from game import Game
from game_models import Player


def make_noble(noble_id, name):
    return Noble(
        noble_id, name,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0,
        0, None, "crimsonseas",
    )


def make_murat_reis():
    return Domain(
        73, "Murat Reis", 9,
        0, 2, 0, 2,                       # role requirements
        2,                                # vp_reward
        False, True,                      # has_activation / has_passive
        "effect.add action.muratreis",    # passive_effect
        None,                             # activation_effect
        "During your Action Phase, ignore +Wild cost when rescuing a Noble.",
        "crimsonseas",
    )


def make_game(*, preset="crimsonseas", slots=None, supply=None):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 30
        p.strength_score = 30
        p.magic_score = 30
        p.victory_score = 0
        p.map_score = 3
        players.append(p)
    noble_slots = slots if slots is not None else [make_noble(1, "A"), make_noble(2, "B"), make_noble(3, "C")]
    noble_supply = supply if supply is not None else [make_noble(4, "D"), make_noble(5, "E")]
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
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "turn_number": 5,
        "phase": "action",
        "actions_remaining": 3,
        "noble_slots": noble_slots,
        "noble_supply": noble_supply,
    }
    if preset is not None:
        state["preset"] = preset
    return Game(state), players


class MuratReisTests(unittest.TestCase):
    def test_owner_pays_flat_9_ignoring_surcharge(self):
        game, players = make_game()
        p = players[0]
        p.owned_nobles = [make_noble(9, "X"), make_noble(10, "Y")]  # holds 2 -> normally +2
        p.owned_domains = [make_murat_reis()]
        gold_before = int(p.gold_score)

        game.rescue_noble(p.player_id, 0, "gold")  # flat 9, surcharge waived

        self.assertEqual(int(p.gold_score), gold_before - 9)
        self.assertEqual(len(p.owned_nobles), 3)

    def test_non_owner_still_escalates(self):
        game, players = make_game()
        p = players[0]
        p.owned_nobles = [make_noble(9, "X"), make_noble(10, "Y")]  # holds 2
        strength_before = int(p.strength_score)

        game.rescue_noble(p.player_id, 1, "strength")  # 9 + 2 = 11

        self.assertEqual(int(p.strength_score), strength_before - 11)

    def test_flat_9_with_no_nobles_owned_is_unchanged(self):
        game, players = make_game()
        p = players[0]
        p.owned_domains = [make_murat_reis()]
        gold_before = int(p.gold_score)
        game.rescue_noble(p.player_id, 0, "gold")
        self.assertEqual(int(p.gold_score), gold_before - 9)

    def test_build_turn_cooldown_keeps_surcharge(self):
        game, players = make_game()
        p = players[0]
        p.owned_nobles = [make_noble(9, "X")]  # holds 1 -> normally +1
        dom = make_murat_reis()
        dom.acquired_turn_number = game.turn_number  # built this turn -> on cooldown
        p.owned_domains = [dom]
        gold_before = int(p.gold_score)

        game.rescue_noble(p.player_id, 0, "gold")  # 9 + 1 = 10 (waiver not active yet)

        self.assertEqual(int(p.gold_score), gold_before - 10)

    def test_waiver_active_turn_after_build(self):
        game, players = make_game()
        p = players[0]
        p.owned_nobles = [make_noble(9, "X")]  # holds 1
        dom = make_murat_reis()
        dom.acquired_turn_number = game.turn_number - 1  # built last turn -> active
        p.owned_domains = [dom]
        gold_before = int(p.gold_score)

        game.rescue_noble(p.player_id, 0, "gold")  # flat 9

        self.assertEqual(int(p.gold_score), gold_before - 9)


if __name__ == "__main__":
    unittest.main()
