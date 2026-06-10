"""Tests for the Crimson Seas Amarynth "rescue Noble" Sail action.

Rescuing costs 1 Map plus 9 of a single chosen Resource type (Wild), with an
additional 1 of that same resource for each Noble already in the player's
tableau. Only one noble may be rescued per visit, and the emptied slot is
refilled directly from the Noble deck (no cascade).
"""

import unittest

from cards import Noble
from game import Game
from game_models import Player


def make_noble(noble_id, name):
    return Noble(
        noble_id, name,
        0, 0, 0, 0,              # role counts
        0, 0, 0, 0,              # role multipliers
        0, 0, 0, 0, 0, 0, 0, 0,  # monster/citizen/domain/boss/minion/beast/titan/goods mult
        0, None, "crimsonseas",  # has_special_duke_payout, special_duke_payout, expansion
    )


def make_game(*, preset="crimsonseas", slots=None, supply=None):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 20
        p.strength_score = 20
        p.magic_score = 20
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
        "phase": "action",
        "actions_remaining": 3,
        "noble_slots": noble_slots,
        "noble_supply": noble_supply,
    }
    if preset is not None:
        state["preset"] = preset
    return Game(state), players


class RescueNobleTests(unittest.TestCase):
    def test_rescue_costs_9_and_one_map_when_no_nobles_owned(self):
        game, players = make_game()
        p = players[0]
        gold_before, map_before = int(p.gold_score), int(p.map_score)

        game.rescue_noble(p.player_id, 0, "gold")

        self.assertEqual(int(p.gold_score), gold_before - 9)
        self.assertEqual(int(p.map_score), map_before - 1)
        self.assertEqual(len(p.owned_nobles), 1)
        self.assertEqual(p.owned_nobles[0].name, "A")
        # Emptied slot refilled directly from the deck (no cascade): the top of
        # the deck (last element, via pop) fills slot 0; B and C stay put.
        self.assertEqual(game.noble_slots[0].name, "E")
        self.assertEqual(game.noble_slots[1].name, "B")
        self.assertEqual(game.noble_slots[2].name, "C")

    def test_cost_escalates_by_owned_nobles(self):
        game, players = make_game()
        p = players[0]
        p.owned_nobles = [make_noble(9, "X"), make_noble(10, "Y")]  # already holds 2
        strength_before = int(p.strength_score)

        game.rescue_noble(p.player_id, 1, "strength")  # cost = 9 + 2 = 11

        self.assertEqual(int(p.strength_score), strength_before - 11)
        self.assertEqual(len(p.owned_nobles), 3)
        self.assertEqual(p.owned_nobles[-1].name, "B")

    def test_insufficient_resource_raises_and_does_not_mutate(self):
        game, players = make_game()
        p = players[0]
        p.magic_score = 8  # need 9
        with self.assertRaises(ValueError):
            game.rescue_noble(p.player_id, 0, "magic")
        self.assertEqual(len(p.owned_nobles), 0)
        self.assertEqual(game.noble_slots[0].name, "A")

    def test_requires_a_map(self):
        game, players = make_game()
        players[0].map_score = 0
        with self.assertRaises(ValueError):
            game.rescue_noble(players[0].player_id, 0, "gold")

    def test_empty_slot_raises(self):
        game, players = make_game(slots=[make_noble(1, "A"), None, make_noble(3, "C")])
        with self.assertRaises(ValueError):
            game.rescue_noble(players[0].player_id, 1, "gold")

    def test_deck_exhausted_leaves_slot_empty(self):
        game, players = make_game(slots=[make_noble(1, "A"), make_noble(2, "B"), make_noble(3, "C")], supply=[])
        game.rescue_noble(players[0].player_id, 2, "gold")
        self.assertIsNone(game.noble_slots[2])
        self.assertEqual(len(players[0].owned_nobles), 1)

    def test_rejects_unknown_resource(self):
        game, players = make_game()
        with self.assertRaises(ValueError):
            game.rescue_noble(players[0].player_id, 0, "victory")

    def test_outside_crimson_seas_rejected(self):
        game, players = make_game(preset="random")
        with self.assertRaises(ValueError):
            game.rescue_noble(players[0].player_id, 0, "gold")


if __name__ == "__main__":
    unittest.main()
