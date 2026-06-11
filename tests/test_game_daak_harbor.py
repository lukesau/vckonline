"""Tests for Daak Harbor (Domain #71).

Activation effect: `choose t 1` - "Immediately take 1 Tome from Nae Aerie."
The player picks one face-up Nae Aerie Tome for free (no gold, no map), receives
it as a flippable Tome object, and the Tome row refreshes (cascade + redraw).
"""

import unittest

from cards import Domain
from game import Game
from game_models import Player


def make_daak_harbor():
    return Domain(
        71, "Daak Harbor", 6,
        0, 2, 2, 0,                       # role requirements
        1,                                # vp_reward
        True, False,                      # has_activation / has_passive
        "",                               # passive_effect
        "choose t 1",                     # activation_effect
        "Immediately take 1 Tome from Nae Aerie.",
        "crimsonseas",
    )


def make_game(*, tome_slots=None, tome_supply=None, preset="crimsonseas"):
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
        "tome_slots": tome_slots if tome_slots is not None
        else ["gold", "magic", "strength"],
        "tome_supply": tome_supply if tome_supply is not None
        else ["gold", "strength"],
    }
    if preset is not None:
        state["preset"] = preset
    return Game(state), players


class DaakHarborTests(unittest.TestCase):
    def test_take_tome_opens_choice_then_refills(self):
        game, players = make_game()
        p = players[0]
        gold_before = int(p.gold_score)
        map_before = int(p.map_score)

        game.domain_effects._apply_domain_activation_effect(p, make_daak_harbor())

        self.assertEqual(game.action_required.get("action"), "choose t 1")
        prc = game.pending_required_choice
        opts = prc.get("options")
        self.assertEqual(len(opts), 3)
        self.assertEqual([o["token"] for o in opts], ["tome.choice"] * 3)

        # Take the middle Tome (slot 1 -> magic).
        game.act_on_required_action(p.player_id, "choose 2")

        self.assertEqual(len(p.owned_tomes), 1)
        self.assertEqual(p.owned_tomes[0].tome_type, "magic")
        self.assertFalse(p.owned_tomes[0].is_flipped)
        # Free: no gold, no map spent.
        self.assertEqual(int(p.gold_score), gold_before)
        self.assertEqual(int(p.map_score), map_before)
        # Waterfall refill keeps 3 visible slots while supply remains.
        self.assertEqual(len(game.tome_slots), 3)
        self.assertNotIn(None, game.tome_slots)
        self.assertEqual(game.action_required.get("action"), "")

    def test_only_nonempty_slots_offered(self):
        game, players = make_game(tome_slots=[None, "magic", None], tome_supply=[])
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_daak_harbor())
        prc = game.pending_required_choice
        self.assertEqual(len(prc.get("options")), 1)
        self.assertEqual(prc["options"][0]["tome_type"], "magic")
        game.act_on_required_action(p.player_id, "choose 1")
        self.assertEqual(len(p.owned_tomes), 1)
        self.assertEqual(p.owned_tomes[0].tome_type, "magic")

    def test_no_tomes_is_noop(self):
        game, players = make_game(tome_slots=[None, None, None], tome_supply=[])
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_daak_harbor())
        # Nothing to take -> no prompt opened.
        self.assertNotEqual(game.action_required.get("action"), "choose t 1")
        self.assertEqual(p.owned_tomes, [])

    def test_outside_crimson_seas_dropped(self):
        game, players = make_game(preset="random")
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_daak_harbor())
        self.assertNotEqual(game.action_required.get("action"), "choose t 1")
        self.assertEqual(p.owned_tomes, [])


if __name__ == "__main__":
    unittest.main()
