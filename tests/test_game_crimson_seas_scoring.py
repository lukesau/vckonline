"""Crimson Seas end-game scoring: Tomes, Goods, and Nobles.

- Tomes: 1 VP each.
- Goods: scored per type in four independent waves with a rising tier table
  (1=2, 2=4, 3=7, 4=12, 5=18, 6=25 VP).
- Nobles: score like Dukes (multipliers + `special_duke_payout`), evaluated
  alongside the Duke. Role-icon multipliers count icons across Citizens,
  Domains, AND Nobles.
"""

import unittest

from cards import Citizen, Domain, Duke, Monster, Noble, Tome
from game import Game
from game_models import Player


def make_citizen(citizen_id, name, shadow=0, holy=0, soldier=0, worker=0):
    return Citizen(
        citizen_id, name, 2, 3, 0,
        shadow, holy, soldier, worker,
        0, 0, 0, 0, 0, 0, 0, 0,
        False, False, "", "", False, "crimsonseas",
    )


def make_domain(domain_id, name, shadow=0, holy=0, soldier=0, worker=0):
    return Domain(
        domain_id, name, 0, shadow, holy, soldier, worker, 0,
        False, False, "", "", "", "crimsonseas",
    )


def make_monster(monster_id, name, mtype):
    return Monster(
        monster_id, name, "Goblins", mtype, 1,
        0, 0, 0, 0, 0, 0, False, "", False, "", False, "crimsonseas",
    )


def make_noble(noble_id, name, *, shadow=0, holy=0, soldier=0, worker=0,
               shadow_mult=0, holy_mult=0, soldier_mult=0, worker_mult=0,
               monster_mult=0, citizen_mult=0, domain_mult=0,
               boss_mult=0, minion_mult=0, beast_mult=0, titan_mult=0,
               goods_mult=0, special=""):
    return Noble(
        noble_id, name,
        shadow, holy, soldier, worker,
        shadow_mult, holy_mult, soldier_mult, worker_mult,
        monster_mult, citizen_mult, domain_mult, boss_mult,
        minion_mult, beast_mult, titan_mult, goods_mult,
        1 if special else 0, special, "crimsonseas",
    )


def make_game(preset="crimsonseas"):
    p1 = Player("p1", "Player 1")
    p2 = Player("p2", "Player 2")
    for p in (p1, p2):
        p.gold_score = 0
        p.strength_score = 0
        p.magic_score = 0
        p.victory_score = 0
        p.owned_citizens = []
        p.owned_domains = []
        p.owned_monsters = []
        p.owned_dukes = []
        p.owned_goods = []
        p.owned_tomes = []
        p.owned_nobles = []
    state = {
        "game_id": "test-game",
        "player_list": [p1, p2],
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
        "preset": preset,
    }
    return Game(state), p1, p2


def score_for(game, player_id):
    return next(s for s in game.endgame._calculate_final_scores() if s["player_id"] == player_id)


class TomeScoringTests(unittest.TestCase):
    def test_one_vp_per_tome(self):
        game, p1, _ = make_game()
        p1.owned_tomes = [Tome("gold"), Tome("magic"), Tome("strength")]
        s = score_for(game, "p1")
        self.assertEqual(s["tome_vp"], 3)
        self.assertEqual(s["total_vp"], 3)

    def test_no_tomes_no_vp(self):
        game, p1, _ = make_game()
        s = score_for(game, "p1")
        self.assertEqual(s["tome_vp"], 0)


class GoodsScoringTests(unittest.TestCase):
    def test_single_type_tiers(self):
        cases = {1: 2, 2: 4, 3: 7, 4: 12, 5: 18, 6: 25}
        for count, expected in cases.items():
            game, p1, _ = make_game()
            p1.owned_goods = ["jewels"] * count
            s = score_for(game, "p1")
            self.assertEqual(s["goods_vp"], expected, f"{count} jewels should be {expected} VP")

    def test_types_scored_independently_in_waves(self):
        # 1 of each of the 4 types = 2 VP per type = 8 VP, not tiered together.
        game, p1, _ = make_game()
        p1.owned_goods = ["jewels", "spices", "fabrics", "artifacts"]
        s = score_for(game, "p1")
        self.assertEqual(s["goods_vp"], 8)

    def test_mixed_counts(self):
        # 3 jewels (7) + 2 spices (4) + 1 fabrics (2) = 13.
        game, p1, _ = make_game()
        p1.owned_goods = ["jewels", "jewels", "jewels", "spices", "spices", "fabrics"]
        s = score_for(game, "p1")
        self.assertEqual(s["goods_vp"], 13)


class NobleMultiplierScoringTests(unittest.TestCase):
    def test_role_multiplier_counts_citizens_domains_and_nobles(self):
        # Augur Kawleen style: 2 VP per Shadow icon. Player has 1 shadow on a
        # citizen, 1 on a domain, plus the Noble's own 1 shadow icon = 3 shadow.
        game, p1, _ = make_game()
        p1.owned_citizens = [make_citizen(1, "C", shadow=1)]
        p1.owned_domains = [make_domain(1, "D", shadow=1)]
        p1.owned_nobles = [make_noble(1, "Augur", shadow=1, shadow_mult=2)]
        s = score_for(game, "p1")
        self.assertEqual(s["noble_vp"], 6)  # 3 shadow icons * 2

    def test_goods_multiplier(self):
        # Sir Robert: 1 VP per goods token owned (any type).
        game, p1, _ = make_game()
        p1.owned_goods = ["jewels", "spices", "spices"]
        p1.owned_nobles = [make_noble(1, "Robert", shadow=1, goods_mult=1)]
        s = score_for(game, "p1")
        # 3 goods * 1 = 3 noble VP (goods tier scoring is separate).
        self.assertEqual(s["noble_vp"], 3)

    def test_tableau_count_multipliers(self):
        game, p1, _ = make_game()
        p1.owned_citizens = [make_citizen(1, "C1"), make_citizen(2, "C2")]
        p1.owned_domains = [make_domain(1, "D1")]
        p1.owned_nobles = [make_noble(1, "Jilko", worker=1, citizen_mult=1)]
        s = score_for(game, "p1")
        self.assertEqual(s["noble_vp"], 2)  # 2 citizens * 1

    def test_monster_type_multiplier(self):
        game, p1, _ = make_game()
        p1.owned_monsters = [make_monster(1, "B1", "Boss"), make_monster(2, "B2", "Boss")]
        p1.owned_nobles = [make_noble(1, "Kiko", holy=1, boss_mult=5)]
        s = score_for(game, "p1")
        self.assertEqual(s["noble_vp"], 10)  # 2 bosses * 5


class NobleSpecialPayoutTests(unittest.TestCase):
    def test_floor_div_gold(self):
        game, p1, _ = make_game()
        p1.gold_score = 7
        p1.owned_nobles = [make_noble(1, "Mikal", worker=1, special="floor_div gold 3 1")]
        s = score_for(game, "p1")
        self.assertEqual(s["noble_vp"], 2)  # 7 // 3 * 1

    def test_wild_choose_picks_best_resource(self):
        game, p1, _ = make_game()
        p1.gold_score = 3
        p1.strength_score = 9
        p1.magic_score = 4
        p1.owned_nobles = [make_noble(1, "Dray", shadow=1, special="wild_choose 2 1")]
        s = score_for(game, "p1")
        self.assertEqual(s["noble_vp"], 4)  # best = 9 strength; 9 // 2 * 1


class AggregateScoringTests(unittest.TestCase):
    def test_total_combines_all_sources(self):
        game, p1, _ = make_game()
        p1.victory_score = 5
        p1.owned_dukes = [Duke(1, "VP Duke", 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, "base")]
        p1.owned_citizens = [make_citizen(1, "C1"), make_citizen(2, "C2")]  # citizen_mult duke = 2
        p1.owned_tomes = [Tome("gold")]                       # +1
        p1.owned_goods = ["jewels", "jewels"]                 # +4
        p1.owned_nobles = [make_noble(1, "Jilko", worker=1, citizen_mult=1)]  # 2 citizens * 1 = 2
        s = score_for(game, "p1")
        self.assertEqual(s["base_vp"], 5)
        self.assertEqual(s["duke_vp"], 2)
        self.assertEqual(s["tome_vp"], 1)
        self.assertEqual(s["goods_vp"], 4)
        self.assertEqual(s["noble_vp"], 2)
        self.assertEqual(s["total_vp"], 5 + 2 + 1 + 4 + 2)
        labels = [l["label"] for l in s["crimson_vp_breakdown"]]
        self.assertIn("Tomes", labels)
        self.assertIn("Goods: Jewels", labels)
        self.assertTrue(any(l.startswith("Noble:") for l in labels))

    def test_nobles_count_toward_tableau_size(self):
        game, p1, _ = make_game()
        p1.owned_nobles = [make_noble(1, "A", shadow=1), make_noble(2, "B", shadow=1)]
        s = score_for(game, "p1")
        self.assertEqual(s["tableau_size"], 2)


class NonCrimsonModeTests(unittest.TestCase):
    def test_base_preset_ignores_crimson_scoring(self):
        game, p1, _ = make_game(preset="base")
        # Even if data somehow had these, base preset must not score them.
        p1.owned_tomes = [Tome("gold")]
        p1.owned_goods = ["jewels", "jewels"]
        p1.owned_nobles = [make_noble(1, "A", shadow=1, shadow_mult=2)]
        p1.victory_score = 4
        s = score_for(game, "p1")
        self.assertEqual(s["tome_vp"], 0)
        self.assertEqual(s["goods_vp"], 0)
        self.assertEqual(s["noble_vp"], 0)
        self.assertEqual(s["crimson_vp_breakdown"], [])
        self.assertEqual(s["total_vp"], 4)


if __name__ == "__main__":
    unittest.main()
