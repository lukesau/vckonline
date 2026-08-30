"""Deferred (card-resident) VP scoring.

Rulebook: "When the game is over, your score is the sum of the Total Victory
Points on all of your slain Monsters [and] built Domains [and] your player
board [and] your Duke." Printed vp_reward is therefore NOT banked into
victory_score when a monster is slain or a domain is built; it stays on the
card and is tallied at end-game scoring (EndgameEngine.card_vp_totals). That
makes card VP follow the card through steals, stack-returns, and banishes,
and closes the double-score where a returned monster could be re-slain after
its VP had already been banked.

victory_score holds board VP only: effect payouts (`choose v N`, scaling
`count ... v N` rewards), dice roll effects, relics, and VP transfers.
"""

import unittest

from cards import Domain, Monster
from game import Game
from game_models import Player


def make_monster(monster_id, name, vp_reward=0, strength_cost=1, magic_cost=0,
                 special_reward="", monster_type="Orc"):
    m = Monster(
        monster_id, name, "Cutthroats", monster_type, 1,
        strength_cost, magic_cost, vp_reward,
        0, 0, 0,
        bool(special_reward), special_reward,
        False, "",
        False, "test",
    )
    m.toggle_visibility(True)
    m.toggle_accessibility(True)
    return m


def make_domain(domain_id, name, vp_reward=0, gold_cost=0):
    d = Domain(
        domain_id, name, gold_cost,
        0, 0, 0, 0,
        vp_reward,
        False, False, "", "",
        "", "test",
    )
    d.toggle_visibility(True)
    d.toggle_accessibility(True)
    return d


def make_game(players, monster_grid=None, domain_grid=None):
    return Game({
        "game_id": "test-game",
        "preset": "base1",
        "player_list": players,
        "monster_grid": monster_grid if monster_grid is not None else [],
        "citizen_grid": [],
        "domain_grid": domain_grid if domain_grid is not None else [],
        "die_one": 1,
        "die_two": 1,
        "die_sum": 2,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
    })


class SlayDefersPrintedVpTests(unittest.TestCase):
    def test_printed_vp_stays_on_card(self):
        player = Player("p1", "Player 1")
        player.strength_score = 5
        top = make_monster(1, "Goblin", vp_reward=3, strength_cost=2)
        game = make_game([player], monster_grid=[[top]])

        game.slay_monster(player.player_id, top.monster_id, sp=2, mp=0)

        self.assertEqual(player.victory_score, 0,
                         "printed vp_reward must not be banked at slay time")
        self.assertEqual(game.endgame.card_vp_totals(player), (3, 0))
        self.assertEqual(game.endgame.effective_vp(player), 3)

    def test_special_reward_board_vp_still_banks(self):
        player = Player("p1", "Player 1")
        player.strength_score = 5
        top = make_monster(1, "Goblin", vp_reward=3, strength_cost=2,
                           special_reward="v 2")
        game = make_game([player], monster_grid=[[top]])

        game.slay_monster(player.player_id, top.monster_id, sp=2, mp=0)

        self.assertEqual(player.victory_score, 2,
                         "special-reward VP is board VP and banks immediately")
        self.assertEqual(game.endgame.effective_vp(player), 5)


class BuildDomainDefersPrintedVpTests(unittest.TestCase):
    def test_printed_vp_stays_on_card(self):
        player = Player("p1", "Player 1")
        player.gold_score = 4
        top = make_domain(1, "Keep", vp_reward=2, gold_cost=3)
        game = make_game([player], domain_grid=[[top]])

        game.player_actions.build_domain(player.player_id, top.domain_id, gp=3)

        self.assertEqual(player.victory_score, 0,
                         "printed vp_reward must not be banked at build time")
        self.assertEqual(game.endgame.card_vp_totals(player), (0, 2))
        self.assertEqual(game.endgame.effective_vp(player), 2)

    def test_granted_domain_defers_printed_vp(self):
        player = Player("p1", "Player 1")
        top = make_domain(1, "Keep", vp_reward=2)
        game = make_game([player], domain_grid=[[top]])
        game.pending_required_choice = {"source_name": "Test Effect"}

        game.payouts._apply_grant_domain_choice(player.player_id, 0)

        self.assertIn(top, player.owned_domains)
        self.assertEqual(player.victory_score, 0)
        self.assertEqual(game.endgame.card_vp_totals(player), (0, 2))


class EndgameCardVpTests(unittest.TestCase):
    def test_final_scores_sum_card_vp(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        p1.victory_score = 4  # board VP
        p1.owned_monsters.append(make_monster(1, "Goblin", vp_reward=3))
        p1.owned_domains.append(make_domain(1, "Keep", vp_reward=2))
        p2.victory_score = 8
        game = make_game([p1, p2])

        scores = game.endgame._calculate_final_scores()
        by_id = {s["player_id"]: s for s in scores}

        self.assertEqual(by_id["p1"]["base_vp"], 4)
        self.assertEqual(by_id["p1"]["monster_vp"], 3)
        self.assertEqual(by_id["p1"]["domain_vp"], 2)
        self.assertEqual(by_id["p1"]["total_vp"], 9)
        self.assertEqual(by_id["p2"]["monster_vp"], 0)
        self.assertEqual(by_id["p2"]["domain_vp"], 0)
        self.assertEqual(by_id["p2"]["total_vp"], 8)
        self.assertEqual(scores[0]["player_id"], "p1")

    def test_stolen_card_scores_for_the_thief(self):
        # The take_owned handler moves the card object between tableaus; the
        # card's printed VP must score for whoever holds it at game end.
        victim = Player("p1", "Victim")
        thief = Player("p2", "Thief")
        card = make_monster(1, "Goblin", vp_reward=3)
        victim.owned_monsters.append(card)
        game = make_game([victim, thief])

        before = {s["player_id"]: s["total_vp"]
                  for s in game.endgame._calculate_final_scores()}
        self.assertEqual(before, {"p1": 3, "p2": 0})

        victim.owned_monsters.remove(card)
        thief.owned_monsters.append(card)

        after = {s["player_id"]: s["total_vp"]
                 for s in game.endgame._calculate_final_scores()}
        self.assertEqual(after, {"p1": 0, "p2": 3})

    def test_returned_and_reslain_monster_scores_once(self):
        # Green Witch-style return: the victim keeps no banked VP, and the
        # re-slain card scores exactly once, for its new owner.
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        p1.strength_score = 5
        p2.strength_score = 5
        top = make_monster(1, "Goblin", vp_reward=3, strength_cost=2)
        game = make_game([p1, p2], monster_grid=[[top]])
        game.monster_stack_areas = ["Cutthroats"]

        game.slay_monster("p1", top.monster_id, sp=2, mp=0)
        self.assertEqual(game.endgame.effective_vp(p1), 3)

        p1.owned_monsters.remove(top)
        returned = game.domain_effects._return_monster_to_stack(top)
        self.assertTrue(returned)
        self.assertEqual(game.endgame.effective_vp(p1), 0,
                         "victim keeps no VP for a returned monster")

        game.slay_monster("p2", top.monster_id, sp=2, mp=0)
        totals = {s["player_id"]: s["total_vp"]
                  for s in game.endgame._calculate_final_scores()}
        self.assertEqual(totals, {"p1": 0, "p2": 3},
                         "a returned monster's VP must not be scored twice")


if __name__ == "__main__":
    unittest.main()
