"""Tests for Solo's Haven (Domain #75).

Activation effect: `refresh_tomes` - "Immediately flip all of your Tomes
face-up." Tomes spent earlier this turn (flipped face-down to pay) come back
face-up, so they can be reused for another purchase in the same turn. The
marquee combo: pay for Solo's Haven itself with Tomes, then reuse those same
Tomes to buy something else before the turn ends.
"""

import unittest

from cards import Domain, Tome
from game import Game
from game_models import Player


def make_solos_haven(roles=(0, 0, 0, 0), gold_cost=6):
    d = Domain(
        75, "Solo's Haven", gold_cost,
        roles[0], roles[1], roles[2], roles[3],
        3,                                # vp_reward
        True, False,                      # has_activation / has_passive
        "",                               # passive_effect
        "refresh_tomes",                  # activation_effect
        "Immediately flip all of your Tomes face-up.",
        "crimsonseas",
    )
    d.toggle_visibility(True)
    d.toggle_accessibility(True)
    return d


def make_game(*, gold_tomes=7, gold=0, preset="crimsonseas",
              with_solos_haven=True):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = gold
        p.strength_score = 5
        p.magic_score = 5
        p.victory_score = 0
        p.map_score = 3
        p.owned_tomes = [Tome("gold") for _ in range(gold_tomes)] if i == 0 else []
        players.append(p)
    domain_grid = [[make_solos_haven()] if with_solos_haven else [], [], [], [], []]
    state = {
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [[], [], [], [], []],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": domain_grid,
        "die_one": 1, "die_two": 2, "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "turn_number": 3,
        "phase": "action",
        "actions_remaining": 3,
        "goods_slots": ["jewels", "spices", "fabrics"],
        "goods_supply": [],
    }
    if preset is not None:
        state["preset"] = preset
    return Game(state), players


def face_up_gold(player):
    return sum(1 for t in player.owned_tomes
               if t.tome_type == "gold" and not t.is_flipped)


class SolosHavenActivationTests(unittest.TestCase):
    def test_activation_flips_all_tomes_face_up(self):
        game, players = make_game(gold_tomes=4)
        p = players[0]
        for t in p.owned_tomes:  # all spent earlier this turn
            t.is_flipped = True

        game.domain_effects._apply_domain_activation_effect(p, make_solos_haven())

        self.assertEqual(face_up_gold(p), 4)
        self.assertTrue(all(not t.is_flipped for t in p.owned_tomes))

    def test_no_tomes_is_noop(self):
        game, players = make_game(gold_tomes=0)
        p = players[0]
        # Should not raise; nothing to flip.
        game.domain_effects._apply_domain_activation_effect(p, make_solos_haven())
        self.assertEqual(p.owned_tomes, [])

    def test_outside_crimson_seas_dropped(self):
        game, players = make_game(gold_tomes=2, preset="random")
        p = players[0]
        for t in p.owned_tomes:
            t.is_flipped = True
        game.domain_effects._apply_domain_activation_effect(p, make_solos_haven())
        # `refresh_tomes` is a no-op outside Crimson Seas: tomes stay face-down.
        self.assertEqual(face_up_gold(p), 0)


class SolosHavenReuseComboTests(unittest.TestCase):
    def test_buy_solos_haven_with_tomes_then_reuse_same_turn(self):
        # Player holds 7 gold tomes and no treasury gold. They pay for Solo's
        # Haven (cost 6) entirely with tomes; building flips those 6 down, then
        # the activation flips ALL tomes back face-up.
        game, players = make_game(gold_tomes=7, gold=0)
        p = players[0]
        pa = game.player_actions

        # --- Buy Solo's Haven, paying 6 with gold tomes (server's redeem-early
        # flow: redeem the tome portion to treasury, then build spends it). ---
        redeemed = pa.redeem_tomes_to_score(p.player_id, {"gold": 6})
        self.assertEqual(redeemed["gold"], 6)
        self.assertEqual(int(p.gold_score), 6)        # tomes redeemed to treasury
        self.assertEqual(face_up_gold(p), 1)          # 6 flipped down for payment
        game.build_domain(p.player_id, 75, gp=6)

        # Build spent the 6 gold; Solo's Haven activation flipped every tome
        # back face-up, so all 7 are reusable again this turn.
        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(len(p.owned_domains), 1)
        self.assertEqual(p.owned_domains[0].name, "Solo's Haven")
        self.assertEqual(face_up_gold(p), 7)

        # --- Reuse the refreshed tomes to buy Goods (slot 2 costs 2) in the
        # same turn, paying with 2 gold tomes again. ---
        pa.buy_goods(p.player_id, [2], tome_payment={"gold": 2, "strength": 0, "magic": 0})

        self.assertEqual(len(p.owned_goods), 1)
        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(face_up_gold(p), 5)          # 2 freshly spent
        self.assertEqual(int(p.map_score), 2)         # 1 map spent sailing


if __name__ == "__main__":
    unittest.main()
