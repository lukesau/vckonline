"""Reactive slay passives: Raven's Outpost (`action.on_opponent_slay`).

Two rules are exercised here:

1. Phase gating. Reactive slay passives fire only during the ACTION phase.
   A harvest-phase slay -- e.g. the Dragoon's bonus Slay a Monster action --
   must NOT activate them. The rulebook is explicit: "Any Domain or Event
   cards that specify a trigger during the Action Phase do not activate when
   you take this bonus Slay a Monster action. For example, Raven's Outpost
   would not activate since it only triggers during an Action Phase."

2. Audience. Raven's Outpost "is only activated when one of your opponents
   slays a Monster, not when you slay a Monster" -- so `action.on_opponent_slay`
   pays every owner EXCEPT the slayer. The legacy `action.on_any_slay` verb
   still pays everyone (slayer included).

These tests build minimal in-memory Game objects and do not touch the DB.
"""

import unittest

from cards import Domain, Monster
from game import Game
from game_models import Player


def make_monster(monster_id, name, *, strength_cost=2, magic_cost=0):
    m = Monster(
        monster_id, name, "Forest", "Minion", 1,
        strength_cost, magic_cost,
        0, 0, 0, 0,              # vp/gold/strength/magic reward
        False, None,             # has_special_reward, special_reward
        False, None,             # has_special_cost, special_cost
        False, "test",
    )
    m.toggle_visibility(True)
    m.toggle_accessibility(True)
    return m


def make_domain(domain_id, name, passive_effect):
    return Domain(
        domain_id, name, 8,
        2, 1, 3, 1,              # role requirements
        1,                       # vp_reward
        False, True,             # has_activation, has_passive
        passive_effect, "", "", "shadowvale",
    )


def make_game(*, phase, monster):
    p1 = Player("p1", "Player 1")
    p2 = Player("p2", "Player 2")
    p3 = Player("p3", "Player 3")
    for p in (p1, p2, p3):
        p.gold_score = 10
        p.strength_score = 10
        p.magic_score = 10
        p.victory_score = 0
    game = Game({
        "game_id": "test-game",
        "player_list": [p1, p2, p3],
        "monster_grid": [[monster]],
        "monster_stack_areas": ["Forest"],
        "citizen_grid": [[], [], [], [], [], [], [], [], [], []],
        "domain_grid": [[], [], [], [], []],
        "die_one": 1, "die_two": 2, "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": phase,
        "actions_remaining": 2,
    })
    return game, (p1, p2, p3)


class RavensOutpostSlayTests(unittest.TestCase):
    def test_opponent_slay_fires_for_opponents_only_in_action_phase(self):
        """p1 slays; only the opponents who own Raven's Outpost gain +1s."""
        monster = make_monster(900, "Test Goblin", strength_cost=2)
        game, (p1, p2, p3) = make_game(phase="action", monster=monster)
        # Both opponents own the outpost; the slayer also owns a copy (which
        # must stay silent because they are the one slaying).
        p1.owned_domains.append(make_domain(61, "Raven's Outpost", "action.on_opponent_slay s 1"))
        p2.owned_domains.append(make_domain(61, "Raven's Outpost", "action.on_opponent_slay s 1"))
        p3.owned_domains.append(make_domain(61, "Raven's Outpost", "action.on_opponent_slay s 1"))

        s1_before = p1.strength_score
        s2_before = p2.strength_score
        s3_before = p3.strength_score

        game.player_actions.slay_monster(p1.player_id, 900, sp=2)

        # Slayer paid 2s for the monster and gains nothing from the outpost.
        self.assertEqual(p1.strength_score, s1_before - 2,
            "slayer must not gain from their own Raven's Outpost")
        # Opponents each gain +1s from their outpost.
        self.assertEqual(p2.strength_score, s2_before + 1)
        self.assertEqual(p3.strength_score, s3_before + 1)

    def test_on_opponent_slay_silent_during_harvest_phase(self):
        """A harvest-phase slay (Dragoon's bonus action) triggers nothing.

        This mirrors the Dragoon `special_payout_on_turn = "slay"` flow, which
        resolves a slay while `game.phase == "harvest"`.
        """
        monster = make_monster(900, "Test Goblin", strength_cost=2)
        game, (p1, p2, p3) = make_game(phase="harvest", monster=monster)
        p2.owned_domains.append(make_domain(61, "Raven's Outpost", "action.on_opponent_slay s 1"))
        p3.owned_domains.append(make_domain(61, "Raven's Outpost", "action.on_opponent_slay s 1"))

        s2_before = p2.strength_score
        s3_before = p3.strength_score

        game.player_actions.slay_monster(p1.player_id, 900, sp=2)

        self.assertEqual(p2.strength_score, s2_before,
            "Raven's Outpost must not fire on a harvest-phase (Dragoon bonus) slay")
        self.assertEqual(p3.strength_score, s3_before,
            "Raven's Outpost must not fire on a harvest-phase (Dragoon bonus) slay")

    def test_on_any_slay_legacy_fires_for_everyone(self):
        """The legacy `action.on_any_slay` verb still pays the slayer too."""
        monster = make_monster(900, "Test Goblin", strength_cost=2)
        game, (p1, p2, p3) = make_game(phase="action", monster=monster)
        p1.owned_domains.append(make_domain(99, "Legacy Outpost", "action.on_any_slay s 1"))
        p2.owned_domains.append(make_domain(99, "Legacy Outpost", "action.on_any_slay s 1"))

        s1_before = p1.strength_score
        s2_before = p2.strength_score

        game.player_actions.slay_monster(p1.player_id, 900, sp=2)

        # Slayer: -2s (payment) +1s (on_any_slay) = net -1s.
        self.assertEqual(p1.strength_score, s1_before - 2 + 1,
            "action.on_any_slay must still pay the slayer")
        self.assertEqual(p2.strength_score, s2_before + 1)

    def test_reactive_passive_helper_phase_gate_direct(self):
        """Direct unit check of the chokepoint helper's phase gate + audience."""
        monster = make_monster(900, "Test Goblin", strength_cost=2)
        game, (p1, p2, p3) = make_game(phase="action", monster=monster)
        p2.owned_domains.append(make_domain(61, "Raven's Outpost", "action.on_opponent_slay s 1"))

        # Action phase, p1 is the slayer -> p2 (opponent) gains.
        s2_before = p2.strength_score
        game.harvest._apply_reactive_slay_passives(slayer_id=p1.player_id)
        self.assertEqual(p2.strength_score, s2_before + 1)

        # Same call but with p2 as the slayer -> p2's own copy stays silent.
        s2_before = p2.strength_score
        game.harvest._apply_reactive_slay_passives(slayer_id=p2.player_id)
        self.assertEqual(p2.strength_score, s2_before)

        # Harvest phase -> nothing fires regardless of slayer.
        game.phase = "harvest"
        s2_before = p2.strength_score
        game.harvest._apply_reactive_slay_passives(slayer_id=p1.player_id)
        self.assertEqual(p2.strength_score, s2_before)


if __name__ == "__main__":
    unittest.main()
