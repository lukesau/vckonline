"""Tests for Brigand's Bay (Domain #69).

Activation effect: `choose <goods>` — "Immediately take 1 Goods from Araby."
The player picks one of the face-up Araby goods for free (no gold, no map) and
the Araby row refreshes (cascade down + redraw), mirroring the tome/noble
"take one face-up" rewards.
"""

import unittest

from cards import Domain
from game import Game
from game_models import Player


def make_brigands_bay():
    return Domain(
        69, "Brigand's Bay", 5,
        1, 0, 0, 1,                       # role requirements
        1,                                # vp_reward
        True, False,                      # has_activation / has_passive
        "",                               # passive_effect
        "choose <goods>",                 # activation_effect
        "Immediately take 1 Goods from Araby.",
        "crimsonseas",
    )


def make_game(*, goods_slots=None, goods_supply=None, preset="crimsonseas"):
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
        "goods_slots": goods_slots if goods_slots is not None
        else ["jewels", "spices", "fabrics"],
        "goods_supply": goods_supply if goods_supply is not None
        else ["artifacts", "jewels"],
    }
    if preset is not None:
        state["preset"] = preset
    return Game(state), players


class BrigandsBayTests(unittest.TestCase):
    def test_take_goods_opens_choice_then_refills(self):
        game, players = make_game()
        p = players[0]
        gold_before = int(p.gold_score)
        map_before = int(p.map_score)

        game.domain_effects._apply_domain_activation_effect(p, make_brigands_bay())

        self.assertEqual(game.action_required.get("action"), "choose <goods>")
        prc = game.pending_required_choice
        opts = prc.get("options")
        self.assertEqual(len(opts), 3)
        self.assertEqual([o["token"] for o in opts], ["goods.choice"] * 3)

        # Take the middle goods (slot 1 → "spices").
        game.act_on_required_action(p.player_id, "choose 2")

        self.assertEqual(p.owned_goods, ["spices"])
        # Free: no gold, no map spent.
        self.assertEqual(int(p.gold_score), gold_before)
        self.assertEqual(int(p.map_score), map_before)
        # Waterfall refill: "jewels" stays at the cheapest slot, top refilled.
        self.assertEqual(len(game.goods_slots), 3)
        self.assertNotIn(None, game.goods_slots)
        self.assertEqual(game.action_required.get("action"), "")

    def test_only_nonempty_slots_offered(self):
        game, players = make_game(goods_slots=[None, "spices", None], goods_supply=[])
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_brigands_bay())
        prc = game.pending_required_choice
        self.assertEqual(len(prc.get("options")), 1)
        self.assertEqual(prc["options"][0]["goods_type"], "spices")
        game.act_on_required_action(p.player_id, "choose 1")
        self.assertEqual(p.owned_goods, ["spices"])

    def test_no_goods_is_noop(self):
        game, players = make_game(goods_slots=[None, None, None], goods_supply=[])
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_brigands_bay())
        # Nothing to take -> no prompt opened.
        self.assertNotEqual(game.action_required.get("action"), "choose <goods>")
        self.assertEqual(p.owned_goods, [])

    def test_outside_crimson_seas_dropped(self):
        game, players = make_game(preset="random")
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_brigands_bay())
        self.assertNotEqual(game.action_required.get("action"), "choose <goods>")
        self.assertEqual(p.owned_goods, [])


if __name__ == "__main__":
    unittest.main()
