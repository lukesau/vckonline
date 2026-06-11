"""Tests for spending Crimson Seas Tomes on resource-cost actions.

Tomes are spent by the "redeem early" model: the chosen face-up tomes are
flipped face-down and their value credited to the player's score up front, so
the normal (unchanged) payment path simply spends them. This covers the shared
`redeem_tomes_to_score` / `refund_tomes_from_score` helpers plus the Sail
purchases (buy_goods / buy_tomes / rescue_noble) that redeem internally.
"""

import unittest

from cards import Domain, Noble, Tome
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


def make_browncoat():
    return Domain(
        70, "Browncoat's Sanctum", 10,
        0, 1, 1, 2,
        2,
        0, 1,
        "effect.add action.browncoatssanctum",
        None,
        "During your Action Phase, Tomes cost 1 Gold less to buy.",
        "crimsonseas",
    )


def make_port_of_drake():
    return Domain(
        74, "Port of Drake", 12,
        1, 0, 0, 2,
        3,
        0, 1,
        "effect.add action.portofdrake",
        None,
        "During your Action Phase, Goods cost 1 Gold less to buy.",
        "crimsonseas",
    )


def make_game(*, preset="crimsonseas", tomes=None):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 10
        p.strength_score = 10
        p.magic_score = 10
        p.victory_score = 0
        p.map_score = 3
        p.owned_tomes = list(tomes) if (i == 0 and tomes is not None) else []
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
        "phase": "action",
        "actions_remaining": 3,
        "goods_slots": ["jewels", "spices", "fabrics"],
        "goods_supply": ["artifacts", "jewels", "spices"],
        "tome_slots": ["gold", "magic", "strength"],
        "tome_supply": ["gold", "strength", "magic"],
        "noble_slots": [make_noble(1, "A"), make_noble(2, "B"), make_noble(3, "C")],
        "noble_supply": [make_noble(4, "D"), make_noble(5, "E")],
    }
    if preset is not None:
        state["preset"] = preset
    return Game(state), players


def face_up(player, ttype):
    return sum(1 for t in player.owned_tomes
               if getattr(t, "tome_type", None) == ttype and not t.is_flipped)


class RedeemHelperTests(unittest.TestCase):
    def test_redeem_flips_and_credits_score(self):
        game, players = make_game(tomes=[Tome("gold"), Tome("gold"), Tome("magic")])
        p = players[0]
        gold_before, magic_before = int(p.gold_score), int(p.magic_score)

        applied = game.redeem_tomes_to_score(p.player_id, {"gold": 2, "magic": 1})

        self.assertEqual(applied, {"gold": 2, "strength": 0, "magic": 1})
        self.assertEqual(int(p.gold_score), gold_before + 2)
        self.assertEqual(int(p.magic_score), magic_before + 1)
        self.assertEqual(face_up(p, "gold"), 0)
        self.assertEqual(face_up(p, "magic"), 0)

    def test_refund_reverses_redeem(self):
        game, players = make_game(tomes=[Tome("gold"), Tome("strength")])
        p = players[0]
        gold_before, str_before = int(p.gold_score), int(p.strength_score)

        applied = game.redeem_tomes_to_score(p.player_id, {"gold": 1, "strength": 1})
        game.refund_tomes_from_score(p.player_id, applied)

        self.assertEqual(int(p.gold_score), gold_before)
        self.assertEqual(int(p.strength_score), str_before)
        self.assertEqual(face_up(p, "gold"), 1)
        self.assertEqual(face_up(p, "strength"), 1)

    def test_redeem_more_than_available_raises(self):
        game, players = make_game(tomes=[Tome("gold")])
        with self.assertRaises(ValueError):
            game.redeem_tomes_to_score(players[0].player_id, {"gold": 2})

    def test_flipped_tomes_are_not_available(self):
        flipped = Tome("gold", is_flipped=True)
        game, players = make_game(tomes=[flipped, Tome("gold")])
        # Only 1 face-up gold tome, so asking for 2 fails.
        with self.assertRaises(ValueError):
            game.redeem_tomes_to_score(players[0].player_id, {"gold": 2})


class BuyGoodsTomeTests(unittest.TestCase):
    def test_gold_tomes_cover_part_of_goods_cost(self):
        # Slot 0 costs 6 gold. Pay 3 with gold tomes, 3 from treasury.
        game, players = make_game(tomes=[Tome("gold"), Tome("gold"), Tome("gold")])
        p = players[0]
        p.gold_score = 3
        map_before = int(p.map_score)

        game.buy_goods(p.player_id, [0], tome_payment={"gold": 3})

        self.assertEqual(int(p.gold_score), 0)            # 3 + 3(tome) - 6
        self.assertEqual(int(p.map_score), map_before - 1)
        self.assertEqual(p.owned_goods, ["jewels"])
        self.assertEqual(face_up(p, "gold"), 0)           # all 3 flipped

    def test_magic_tomes_pay_goods_cost_as_wild(self):
        # Magic is wild for the gold cost: 1 magic tome + 5 treasury gold = 6.
        game, players = make_game(tomes=[Tome("magic")])
        p = players[0]
        p.gold_score = 5
        p.magic_score = 0

        game.buy_goods(p.player_id, [0], tome_payment={"magic": 1})

        self.assertEqual(int(p.gold_score), 0)            # 5 - 5 treasury gold
        self.assertEqual(int(p.magic_score), 0)           # +1 redeemed, -1 spent
        self.assertEqual(p.owned_goods, ["jewels"])
        self.assertEqual(face_up(p, "magic"), 0)          # magic tome flipped

    def test_treasury_magic_pays_goods_cost_as_wild(self):
        # No tomes: 1 treasury gold + 5 treasury magic covers the 6 gold cost.
        game, players = make_game()
        p = players[0]
        p.gold_score = 1
        p.magic_score = 5

        game.buy_goods(p.player_id, [0])

        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(int(p.magic_score), 0)
        self.assertEqual(p.owned_goods, ["jewels"])

    def test_pure_magic_payment_requires_at_least_one_gold(self):
        # Slot 2 costs 2 gold; with 0 gold and only magic, the wild rule blocks it.
        game, players = make_game()
        p = players[0]
        p.gold_score = 0
        p.magic_score = 10
        with self.assertRaises(ValueError):
            game.buy_goods(p.player_id, [2])

    def test_strength_tomes_rejected_for_goods(self):
        # Strength is not wild for the gold cost.
        game, players = make_game(tomes=[Tome("strength")])
        with self.assertRaises(ValueError):
            game.buy_goods(players[0].player_id, [0], tome_payment={"strength": 1})

    def test_more_tomes_than_cost_rejected(self):
        game, players = make_game(tomes=[Tome("gold")] * 8)
        # Slot 2 costs 2 gold; can't apply 3 gold tomes.
        with self.assertRaises(ValueError):
            game.buy_goods(players[0].player_id, [2], tome_payment={"gold": 3})


class BuyTomesTomeTests(unittest.TestCase):
    def test_gold_tomes_cover_part_of_tome_cost(self):
        # Slot 2 costs 3 gold.
        game, players = make_game(tomes=[Tome("gold"), Tome("gold")])
        p = players[0]
        p.gold_score = 1
        game.buy_tomes(p.player_id, [2], tome_payment={"gold": 2})
        self.assertEqual(int(p.gold_score), 0)            # 1 + 2(tome) - 3
        self.assertEqual(face_up(p, "gold"), 0)
        # Bought a strength tome (slot 2) into the tableau as a Tome object.
        self.assertTrue(any(getattr(t, "tome_type", None) == "strength" for t in p.owned_tomes))

    def test_browncoat_sanctum_discounts_tome_costs(self):
        # Slot 2 normally costs 3 gold; Browncoat's Sanctum reduces it to 2.
        game, players = make_game()
        p = players[0]
        p.owned_domains.append(make_browncoat())
        p.gold_score = 2
        map_before = int(p.map_score)

        game.buy_tomes(p.player_id, [2])

        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(int(p.map_score), map_before - 1)
        self.assertTrue(any(getattr(t, "tome_type", None) == "strength" for t in p.owned_tomes))

    def test_browncoat_discount_applies_to_each_selected_tome(self):
        # Slots 0 and 2 normally cost 7 + 3; discounted cost is 6 + 2.
        game, players = make_game()
        p = players[0]
        p.owned_domains.append(make_browncoat())
        p.gold_score = 8

        game.buy_tomes(p.player_id, [0, 2])

        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(len(p.owned_tomes), 2)

    def test_browncoat_discount_reduces_max_gold_tomes_applied(self):
        # Slot 2 costs 2 after discount, so 3 Gold tomes is too many.
        game, players = make_game(tomes=[Tome("gold")] * 3)
        p = players[0]
        p.owned_domains.append(make_browncoat())
        with self.assertRaises(ValueError):
            game.buy_tomes(p.player_id, [2], tome_payment={"gold": 3})

    def test_browncoat_discount_waits_until_after_build_turn(self):
        game, players = make_game()
        p = players[0]
        d = make_browncoat()
        d.acquired_turn_number = int(game.turn_number)
        p.owned_domains.append(d)
        p.gold_score = 2
        p.magic_score = 0  # no wild fallback, so the full cost must bite
        # Slot 2 still costs 3 on the turn Browncoat's Sanctum was bought.
        with self.assertRaises(ValueError):
            game.buy_tomes(p.player_id, [2])


class BuyGoodsDiscountTests(unittest.TestCase):
    def test_port_of_drake_discounts_goods_costs(self):
        # Slot 0 normally costs 6 gold; Port of Drake reduces it to 5.
        game, players = make_game()
        p = players[0]
        p.owned_domains.append(make_port_of_drake())
        p.gold_score = 5
        map_before = int(p.map_score)

        game.buy_goods(p.player_id, [0])

        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(int(p.map_score), map_before - 1)
        self.assertEqual(p.owned_goods, ["jewels"])

    def test_port_of_drake_discount_applies_per_selected_good(self):
        # Slots 0 and 2 normally cost 6 + 2; discounted cost is 5 + 1.
        game, players = make_game()
        p = players[0]
        p.owned_domains.append(make_port_of_drake())
        p.gold_score = 6

        game.buy_goods(p.player_id, [0, 2])

        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(len(p.owned_goods), 2)

    def test_port_of_drake_discount_reduces_max_gold_tomes_applied(self):
        # Slot 2 costs 1 after discount, so 2 Gold tomes is too many.
        game, players = make_game(tomes=[Tome("gold")] * 2)
        p = players[0]
        p.owned_domains.append(make_port_of_drake())
        with self.assertRaises(ValueError):
            game.buy_goods(p.player_id, [2], tome_payment={"gold": 2})

    def test_port_of_drake_discount_waits_until_after_build_turn(self):
        game, players = make_game()
        p = players[0]
        d = make_port_of_drake()
        d.acquired_turn_number = int(game.turn_number)
        p.owned_domains.append(d)
        p.gold_score = 5
        p.magic_score = 0  # no wild fallback, so the full cost must bite
        # Slot 0 still costs 6 on the turn Port of Drake was bought.
        with self.assertRaises(ValueError):
            game.buy_goods(p.player_id, [0])


class RescueNobleTomeTests(unittest.TestCase):
    def test_matching_type_tomes_help_pay_rescue(self):
        # Cost 9 gold; pay 5 with gold tomes + 4 treasury.
        game, players = make_game(tomes=[Tome("gold")] * 5)
        p = players[0]
        p.gold_score = 4
        game.rescue_noble(p.player_id, 0, "gold", tome_payment={"gold": 5})
        self.assertEqual(int(p.gold_score), 0)            # 4 + 5(tome) - 9
        self.assertEqual(len(p.owned_nobles), 1)
        self.assertEqual(face_up(p, "gold"), 0)

    def test_wrong_type_tomes_rejected_for_rescue(self):
        game, players = make_game(tomes=[Tome("magic")])
        with self.assertRaises(ValueError):
            game.rescue_noble(players[0].player_id, 0, "gold", tome_payment={"magic": 1})


if __name__ == "__main__":
    unittest.main()
