"""Crimson Seas: Nobles count toward Domain build role-icon requirements.

The rulebook modifies the "Build a Domain" step so that "the Citizens and/or
Nobles in your tableau must have Citizen Role icons that match those on the
Domain card." Nobles carry the same shadow/holy/soldier/worker counts as
Citizens, so they satisfy (and stack with Citizens toward) a Domain's role
prerequisites.
"""

import unittest

from cards import Citizen, Domain, Noble
from game import Game
from game_models import Player


def make_domain(domain_id, name, gold_cost, shadow=0, holy=0, soldier=0, worker=0):
    d = Domain(
        domain_id, name, gold_cost,
        shadow, holy, soldier, worker,
        0,                       # vp_reward
        False, False,            # has_activation/passive
        "", "", "", "crimsonseas",
    )
    d.toggle_visibility(True)
    d.toggle_accessibility(True)
    return d


def make_noble(noble_id, name, shadow=0, holy=0, soldier=0, worker=0):
    return Noble(
        noble_id, name,
        shadow, holy, soldier, worker,
        0, 0, 0, 0,              # role multipliers
        0, 0, 0, 0,              # monster/citizen/domain/boss multipliers
        0, 0, 0, 0,              # minion/beast/titan/goods multipliers
        0, "",                   # has_special_duke_payout, special_duke_payout
        "crimsonseas",
    )


def make_citizen(citizen_id, name, shadow=0, holy=0, soldier=0, worker=0):
    return Citizen(
        citizen_id, name,
        2,                       # gold_cost
        3, 0,                    # roll_match1/2
        shadow, holy, soldier, worker,
        0, 0, 0, 0, 0, 0, 0, 0,  # gold/strength/magic/vp payouts on/off
        False, False, "", "",    # special payout flags/strings
        False, "crimsonseas",
    )


def make_game(domain):
    p1 = Player("p1", "Player 1")
    p1.gold_score = 10
    p1.strength_score = 10
    p1.magic_score = 10
    p1.victory_score = 0
    p2 = Player("p2", "Player 2")
    state = {
        "game_id": "test-game",
        "player_list": [p1, p2],
        "monster_grid": [[], [], [], [], []],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": [[domain], [], [], [], []],
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
    return Game(state), p1


class NobleBuildRoleTests(unittest.TestCase):
    def test_noble_alone_satisfies_role_requirement(self):
        game, p = make_game(make_domain(99, "Keep", 0, soldier=1))
        p.owned_nobles = [make_noble(1, "Sir Test", soldier=1)]
        game.player_actions.build_domain("p1", 99)
        self.assertEqual(len(p.owned_domains), 1)
        self.assertEqual(p.owned_domains[0].name, "Keep")

    def test_missing_role_without_noble_raises(self):
        game, p = make_game(make_domain(99, "Keep", 0, soldier=1))
        with self.assertRaises(ValueError):
            game.player_actions.build_domain("p1", 99)
        self.assertEqual(len(p.owned_domains), 0)

    def test_citizen_and_noble_combine_for_multiple_icons(self):
        # Domain needs 2 soldier icons; one Citizen + one Noble together cover it.
        game, p = make_game(make_domain(99, "Keep", 0, soldier=2))
        p.owned_citizens = [make_citizen(50, "Footman", soldier=1)]
        p.owned_nobles = [make_noble(1, "Sir Test", soldier=1)]
        game.player_actions.build_domain("p1", 99)
        self.assertEqual(len(p.owned_domains), 1)

    def test_two_nobles_satisfy_double_requirement(self):
        game, p = make_game(make_domain(99, "Keep", 0, soldier=2))
        p.owned_nobles = [
            make_noble(1, "Sir A", soldier=1),
            make_noble(2, "Sir B", soldier=1),
        ]
        game.player_actions.build_domain("p1", 99)
        self.assertEqual(len(p.owned_domains), 1)

    def test_noble_with_wrong_role_does_not_satisfy(self):
        # Domain needs a holy icon; the Noble only has a soldier icon.
        game, p = make_game(make_domain(99, "Keep", 0, holy=1))
        p.owned_nobles = [make_noble(1, "Sir Test", soldier=1)]
        with self.assertRaises(ValueError):
            game.player_actions.build_domain("p1", 99)
        self.assertEqual(len(p.owned_domains), 0)

    def test_noble_satisfies_ararmartin_build_offer(self):
        # The Ararmartin Ridge "may build a Domain" offer uses the same role
        # gate, so a Noble should make an otherwise role-gated domain eligible.
        game, p = make_game(make_domain(99, "Keep", 0, soldier=1))
        p.owned_nobles = [make_noble(1, "Sir Test", soldier=1)]
        game.payouts._execute_build_domain_activation_payout("p1")
        prc = game.pending_required_choice or {}
        opts = prc.get("options") or []
        self.assertTrue(any(int(o.get("domain_id", -1)) == 99 for o in opts),
                        "Domain should be offered because the Noble covers its role")


if __name__ == "__main__":
    unittest.main()
