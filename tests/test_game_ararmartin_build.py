"""Tests for the Ararmartin Ridge (Domain #25) optional build opportunity.

Its `g 3 + build_domain` activation lets the active player build a Domain "like
getting another action that can only be used to buy a domain": Magic covers the
Gold cost as a wild and face-up Gold/Magic tomes can help. The prompt is a
two-stage pick -> pay flow (`build_domain_pick` then `build_pay g m [tg ts tm]`).
"""

import unittest

from cards import Domain, Tome
from game import Game
from game_models import Player


def make_domain(domain_id, name, gold_cost):
    d = Domain(
        domain_id, name, gold_cost,
        0, 0, 0, 0,              # role requirements
        0,                       # vp_reward
        False, False,            # has_activation/passive
        "", "", "", "crimsonseas",
    )
    d.toggle_visibility(True)
    d.toggle_accessibility(True)
    return d


def make_game(*, tomes=None, gold=10, magic=10):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = gold
        p.strength_score = 10
        p.magic_score = magic
        p.victory_score = 0
        p.map_score = 3
        p.owned_tomes = list(tomes) if (i == 0 and tomes is not None) else []
        players.append(p)
    state = {
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [[], [], [], [], []],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": [[make_domain(99, "Test Keep", 6)], [], [], [], []],
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
    }
    return Game(state), players


def face_up(player, ttype):
    return sum(1 for t in player.owned_tomes
               if getattr(t, "tome_type", None) == ttype and not t.is_flipped)


def start_pick_stage(game, player_id):
    game.payouts._execute_build_domain_activation_payout(player_id)


class AffordabilityTests(unittest.TestCase):
    def test_magic_as_wild_makes_domain_affordable(self):
        # Only 1 gold (< the 6 cost) but plenty of magic: the domain should be
        # offered because magic covers the shortfall as a wild. Before the
        # magic-as-wild fix, 1 < 6 filtered this out.
        game, players = make_game(gold=1, magic=10)
        start_pick_stage(game, players[0].player_id)
        self.assertEqual(game.action_required["action"], "choose_domain_to_build")
        opts = game.pending_required_choice["options"]
        self.assertEqual(len(opts), 1)
        self.assertEqual(opts[0]["gold_cost"], 6)

    def test_no_gold_equivalent_blocks_offer(self):
        # 0 gold and 0 magic-tomes/gold-tomes -> can't satisfy the 1-gold rule.
        game, players = make_game(gold=0, magic=10)
        # Magic is fine for the bulk, but at least 1 gold-equivalent is required.
        # With 0 gold and 0 tomes, gold_pool == 0 so the domain is filtered out.
        # (Magic-only without any gold is not a legal build.)
        players[0].magic_score = 10
        players[0].gold_score = 0
        start_pick_stage(game, players[0].player_id)
        # No affordable domain -> falls back to the +3 gold path (no prompt).
        self.assertEqual(game.action_required["action"], "")

    def test_gold_tome_provides_the_one_gold(self):
        # 0 treasury gold but a face-up gold tome supplies the gold-equivalent.
        game, players = make_game(tomes=[Tome("gold")], gold=0, magic=10)
        start_pick_stage(game, players[0].player_id)
        self.assertEqual(game.action_required["action"], "choose_domain_to_build")


class TwoStageFlowTests(unittest.TestCase):
    def test_pick_then_pay_with_magic_as_wild(self):
        game, players = make_game(gold=1, magic=5)
        p = players[0]
        start_pick_stage(game, p.player_id)

        game.player_actions.act_on_required_action(p.player_id, "build_domain_pick 1")
        self.assertEqual(game.action_required["action"], "build_domain_payment")
        self.assertEqual(game.pending_required_choice["domain_id"], 99)
        self.assertEqual(game.pending_required_choice["gold_cost"], 6)

        # 1 gold + 5 magic == 6 cost (magic as wild).
        game.player_actions.act_on_required_action(p.player_id, "build_pay 1 5 0 0 0")
        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(int(p.magic_score), 0)
        self.assertEqual(len(p.owned_domains), 1)
        self.assertEqual(p.owned_domains[0].domain_id, 99)
        # Build resolved -> no longer in a domain-build prompt.
        self.assertNotIn(game.action_required["action"],
                         ("build_domain_payment", "choose_domain_to_build"))

    def test_back_returns_to_pick_stage(self):
        game, players = make_game(gold=6, magic=0)
        p = players[0]
        start_pick_stage(game, p.player_id)
        game.player_actions.act_on_required_action(p.player_id, "build_domain_pick 1")
        self.assertEqual(game.action_required["action"], "build_domain_payment")

        game.player_actions.act_on_required_action(p.player_id, "back")
        self.assertEqual(game.action_required["action"], "choose_domain_to_build")
        self.assertEqual(len(p.owned_domains), 0)

    def test_skip_at_pay_stage_declines(self):
        game, players = make_game(gold=6, magic=0)
        p = players[0]
        start_pick_stage(game, p.player_id)
        game.player_actions.act_on_required_action(p.player_id, "build_domain_pick 1")
        game.player_actions.act_on_required_action(p.player_id, "skip")
        self.assertNotIn(game.action_required["action"],
                         ("build_domain_payment", "choose_domain_to_build"))
        self.assertEqual(len(p.owned_domains), 0)

    def test_bad_payment_keeps_prompt_open(self):
        game, players = make_game(gold=6, magic=6)
        p = players[0]
        start_pick_stage(game, p.player_id)
        game.player_actions.act_on_required_action(p.player_id, "build_domain_pick 1")
        # 1 + 1 != 6: payment does not cover the cost.
        game.player_actions.act_on_required_action(p.player_id, "build_pay 1 1 0 0 0")
        self.assertEqual(game.action_required["action"], "build_domain_payment")
        self.assertEqual(len(p.owned_domains), 0)


class TomePaymentTests(unittest.TestCase):
    def test_gold_and_magic_tomes_help_pay(self):
        # cost 6: pay 1 treasury gold + 2 magic + redeem 1 gold tome + 2 magic tomes.
        game, players = make_game(
            tomes=[Tome("gold"), Tome("magic"), Tome("magic")],
            gold=1, magic=2,
        )
        p = players[0]
        start_pick_stage(game, p.player_id)
        game.player_actions.act_on_required_action(p.player_id, "build_domain_pick 1")

        # totals: gold gp=2 (1 treasury + 1 tome), magic mp=4 (2 treasury + 2 tome) = 6
        game.player_actions.act_on_required_action(p.player_id, "build_pay 2 4 1 0 2")
        self.assertEqual(len(p.owned_domains), 1)
        self.assertEqual(int(p.gold_score), 0)
        self.assertEqual(int(p.magic_score), 0)
        self.assertEqual(face_up(p, "gold"), 0)
        self.assertEqual(face_up(p, "magic"), 0)

    def test_tome_exceeding_payment_rejected(self):
        game, players = make_game(tomes=[Tome("gold")] * 3, gold=3, magic=3)
        p = players[0]
        start_pick_stage(game, p.player_id)
        game.player_actions.act_on_required_action(p.player_id, "build_domain_pick 1")
        # Claim 3 gold tomes but only paying 2 gold -> rejected, prompt stays open.
        game.player_actions.act_on_required_action(p.player_id, "build_pay 2 4 3 0 0")
        self.assertEqual(game.action_required["action"], "build_domain_payment")
        self.assertEqual(len(p.owned_domains), 0)
        self.assertEqual(face_up(p, "gold"), 3)


if __name__ == "__main__":
    unittest.main()
