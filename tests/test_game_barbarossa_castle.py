"""Tests for Barbarossa Castle (Domain #68).

Activation effect: `banish_center noble + choose g 3 s 3 m 3` — "Immediately gain
3 Wild and Banish a Noble from Amarynth." The banish leg extends the existing
banish-from-center machinery to the Crimson Seas Amarynth noble slots, then the
emptied slot is refilled directly from the noble deck (no cascading).
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


def make_barbarossa():
    return Domain(
        68, "Barbarossa Castle", 6,
        1, 0, 3, 0,                                   # role requirements
        2,                                            # vp_reward
        True, False,                                  # has_activation / has_passive
        "",                                           # passive_effect
        "banish_center noble + choose g 3 s 3 m 3",   # activation_effect
        "Immediately gain 3 Wild and Banish a Noble from Amarynth.",
        "crimsonseas",
    )


def make_game(*, noble_slots=None, noble_supply=None):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 5
        p.strength_score = 5
        p.magic_score = 5
        p.victory_score = 0
        p.map_score = 3
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
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "turn_number": 1,
        "phase": "action",
        "actions_remaining": 3,
        "preset": "crimsonseas",
        "noble_slots": noble_slots if noble_slots is not None
        else [make_noble(1, "A"), make_noble(2, "B"), make_noble(3, "C")],
        "noble_supply": noble_supply if noble_supply is not None
        else [make_noble(4, "D"), make_noble(5, "E")],
    }
    return Game(state), players


class BarbarossaCastleTests(unittest.TestCase):
    def test_banish_then_choose_wild(self):
        game, players = make_game()
        p = players[0]
        gold_before = int(p.gold_score)

        game.domain_effects._apply_domain_activation_effect(p, make_barbarossa())

        # Leg 1 opens the noble banish prompt.
        self.assertEqual(game.action_required.get("action"), "choose_owned_card")
        prc = game.pending_required_choice
        self.assertEqual(prc.get("kind"), "banish_center_card")
        self.assertEqual(prc.get("card_kind"), "noble")
        self.assertEqual(len(prc.get("options")), 3)

        # Banish the first noble (slot 0 → "A").
        banished = game.noble_slots[0]
        game.act_on_required_action(p.player_id, "choose_owned_card 1")

        self.assertIn(banished, game.banish_pile)
        # Slot 0 refilled from the top of the deck (last appended → "E").
        self.assertIsNotNone(game.noble_slots[0])
        self.assertEqual(game.noble_slots[0].noble_id, 5)
        self.assertEqual(len(game.noble_supply), 1)

        # Leg 2 (the continuation) now opens the choose prompt.
        self.assertEqual(game.action_required.get("action"), "choose g 3 s 3 m 3")

        # Pick option 1 (gold 3).
        game.act_on_required_action(p.player_id, "choose 1")
        self.assertEqual(int(p.gold_score), gold_before + 3)
        self.assertEqual(game.action_required.get("action"), "")

    def test_choose_magic_branch(self):
        game, players = make_game()
        p = players[0]
        magic_before = int(p.magic_score)
        game.domain_effects._apply_domain_activation_effect(p, make_barbarossa())
        game.act_on_required_action(p.player_id, "choose_owned_card 1")
        # Option 3 is magic 3.
        game.act_on_required_action(p.player_id, "choose 3")
        self.assertEqual(int(p.magic_score), magic_before + 3)

    def test_empty_supply_leaves_slot_empty(self):
        game, players = make_game(
            noble_slots=[make_noble(1, "A"), make_noble(2, "B"), make_noble(3, "C")],
            noble_supply=[],
        )
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_barbarossa())
        game.act_on_required_action(p.player_id, "choose_owned_card 1")
        # No deck left → slot becomes empty, but the rest of the effect still runs.
        self.assertIsNone(game.noble_slots[0])
        self.assertEqual(game.action_required.get("action"), "choose g 3 s 3 m 3")
        game.act_on_required_action(p.player_id, "choose 1")
        self.assertEqual(game.action_required.get("action"), "")

    def test_only_nonempty_slots_are_targetable(self):
        game, players = make_game(
            noble_slots=[None, make_noble(2, "B"), None],
            noble_supply=[make_noble(9, "Z")],
        )
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_barbarossa())
        prc = game.pending_required_choice
        self.assertEqual(len(prc.get("options")), 1)
        self.assertEqual(prc["options"][0]["idx"], 1)


if __name__ == "__main__":
    unittest.main()
