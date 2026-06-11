"""Tests for the Crimson Seas Exekratys island.

Two behaviors are covered:

1. The game-wide 6-roll obligation: at the end of the Roll Phase, for each 6
   rolled (each die plus the dice sum, counted separately) the active player
   must place 1 of their own resources into the Exekratys pool. The prompt is
   opened during the roll-to-harvest transition and blocks harvest until drained.

2. Sailing to Exekratys: the sailing player pays 1 Map and takes ALL of one
   chosen resource type from the pool, emptying it for that resource.
"""

import unittest

from cards import Domain
from game import Game
from game_models import Player


def make_avery_hollow():
    """Domain #67 Avery Hollow: owner is exempt from the Exekratys 6-roll loss."""
    return Domain(
        67, "Avery Hollow", 5,
        0, 1, 3, 0,                       # role requirements
        1,                                # vp_reward
        0, 1,                             # has_activation / has_passive
        "roll.exekratys_immune",          # passive_effect flag
        None,                             # activation_effect
        "During your Roll Phase, you don't lose Wild on a 6.",
        "crimsonseas",
    )


def make_game(*, preset="crimsonseas", rolled=(1, 6), exekratys=None):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 5
        p.strength_score = 5
        p.magic_score = 5
        p.victory_score = 0
        p.map_score = 3
        players.append(p)
    rd1, rd2 = rolled
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
        "phase": "roll_pending",
        "actions_remaining": 0,
        "pending_roll": {"rolled_die_one": rd1, "rolled_die_two": rd2, "rolled_die_sum": rd1 + rd2},
        "exekratys_resources": dict(exekratys or {"gold": 2, "strength": 2, "magic": 2}),
    }
    if preset is not None:
        state["preset"] = preset
    game = Game(state)
    game.action_required["id"] = game.lifecycle.current_player_id()
    game.action_required["action"] = "finalize_roll"
    return game, players


class ExekratysRollSixOfferingTests(unittest.TestCase):
    def test_single_six_opens_offering_prompt(self):
        game, players = make_game(rolled=(1, 6))  # one die is a 6
        game.finalize_roll(players[0].player_id)
        game.advance_tick()

        self.assertEqual(game.pending_exekratys_offerings, 1)
        self.assertEqual(game.action_required.get("action"), "exekratys_offering")
        self.assertEqual(game.action_required.get("id"), players[0].player_id)
        prc = game.pending_required_choice
        self.assertEqual(prc.get("kind"), "exekratys_offering")
        self.assertEqual([o["resource"] for o in prc["options"]], ["gold", "strength", "magic"])

    def test_sum_of_six_counts(self):
        game, players = make_game(rolled=(2, 4))  # no individual 6, but the sum is 6
        game.finalize_roll(players[0].player_id)
        game.advance_tick()
        self.assertEqual(game.pending_exekratys_offerings, 1)
        self.assertEqual(game.action_required.get("action"), "exekratys_offering")

    def test_no_six_no_prompt(self):
        game, players = make_game(rolled=(2, 3))
        game.finalize_roll(players[0].player_id)
        game.advance_tick()
        self.assertEqual(game.pending_exekratys_offerings, 0)
        self.assertNotEqual(game.action_required.get("action"), "exekratys_offering")

    def test_placing_moves_resource_into_pool(self):
        game, players = make_game(rolled=(1, 6))
        game.finalize_roll(players[0].player_id)
        game.advance_tick()

        gold_before = int(players[0].gold_score)
        pool_before = int(game.exekratys_resources.get("gold", 0))
        game.act_on_required_action(players[0].player_id, "exekratys_offering gold")

        self.assertEqual(int(players[0].gold_score), gold_before - 1)
        self.assertEqual(int(game.exekratys_resources.get("gold", 0)), pool_before + 1)
        self.assertEqual(game.pending_exekratys_offerings, 0)
        self.assertEqual(game.action_required.get("action"), "")

    def test_double_six_requires_two_placements(self):
        game, players = make_game(rolled=(6, 6))  # two individual 6s (sum is 12)
        game.finalize_roll(players[0].player_id)
        game.advance_tick()
        self.assertEqual(game.pending_exekratys_offerings, 2)

        game.act_on_required_action(players[0].player_id, "exekratys_offering gold")
        # Still owes one more placement; prompt re-opens.
        self.assertEqual(game.pending_exekratys_offerings, 1)
        self.assertEqual(game.action_required.get("action"), "exekratys_offering")

        game.act_on_required_action(players[0].player_id, "exekratys_offering magic")
        self.assertEqual(game.pending_exekratys_offerings, 0)
        self.assertEqual(int(game.exekratys_resources.get("gold", 0)), 3)
        self.assertEqual(int(game.exekratys_resources.get("magic", 0)), 3)

    def test_no_resources_drops_obligation(self):
        game, players = make_game(rolled=(1, 6))
        players[0].gold_score = 0
        players[0].strength_score = 0
        players[0].magic_score = 0
        game.finalize_roll(players[0].player_id)
        game.advance_tick()
        # Nothing to place -> obligation dropped, no prompt.
        self.assertEqual(game.pending_exekratys_offerings, 0)
        self.assertNotEqual(game.action_required.get("action"), "exekratys_offering")

    def test_outside_crimson_seas_no_offering(self):
        game, players = make_game(preset="random", rolled=(6, 6))
        game.finalize_roll(players[0].player_id)
        game.advance_tick()
        self.assertEqual(game.pending_exekratys_offerings, 0)
        self.assertNotEqual(game.action_required.get("action"), "exekratys_offering")


class AveryHollowExemptionTests(unittest.TestCase):
    def test_owner_is_exempt_from_offering(self):
        game, players = make_game(rolled=(6, 6))  # two 6s would owe two placements
        players[0].owned_domains.append(make_avery_hollow())
        game.finalize_roll(players[0].player_id)
        game.advance_tick()
        # Avery Hollow protects the roller: no obligation, no prompt, resources kept.
        self.assertEqual(game.pending_exekratys_offerings, 0)
        self.assertNotEqual(game.action_required.get("action"), "exekratys_offering")
        self.assertEqual(int(players[0].gold_score), 5)
        self.assertEqual(int(players[0].strength_score), 5)
        self.assertEqual(int(players[0].magic_score), 5)

    def test_only_protects_the_roller_not_opponents(self):
        # The opponent owns Avery Hollow, but the active roller does not, so the
        # roller still owes the offering.
        game, players = make_game(rolled=(1, 6))
        players[1].owned_domains.append(make_avery_hollow())
        game.finalize_roll(players[0].player_id)
        game.advance_tick()
        self.assertEqual(game.pending_exekratys_offerings, 1)
        self.assertEqual(game.action_required.get("action"), "exekratys_offering")
        self.assertEqual(game.action_required.get("id"), players[0].player_id)

    def test_exempt_on_build_turn_cooldown_still_owes(self):
        # A domain bought THIS turn is on the recurring-passive cooldown, so its
        # protection does not apply yet (mirrors other roll passives).
        game, players = make_game(rolled=(1, 6))
        d = make_avery_hollow()
        d.acquired_turn_number = int(game.turn_number)
        players[0].owned_domains.append(d)
        game.finalize_roll(players[0].player_id)
        game.advance_tick()
        self.assertEqual(game.pending_exekratys_offerings, 1)
        self.assertEqual(game.action_required.get("action"), "exekratys_offering")


class SailToExekratysTests(unittest.TestCase):
    def test_drains_all_of_chosen_resource_for_one_map(self):
        game, players = make_game(exekratys={"gold": 4, "strength": 1, "magic": 2})
        game.preset = "crimsonseas"
        p = players[0]
        gold_before = int(p.gold_score)
        map_before = int(p.map_score)

        game.sail_exekratys(p.player_id, "gold")

        self.assertEqual(int(p.gold_score), gold_before + 4)
        self.assertEqual(int(p.map_score), map_before - 1)
        self.assertEqual(int(game.exekratys_resources.get("gold", 0)), 0)
        # Other resources untouched.
        self.assertEqual(int(game.exekratys_resources.get("strength", 0)), 1)
        self.assertEqual(int(game.exekratys_resources.get("magic", 0)), 2)

    def test_requires_a_map(self):
        game, players = make_game(exekratys={"gold": 4})
        players[0].map_score = 0
        with self.assertRaises(ValueError):
            game.sail_exekratys(players[0].player_id, "gold")

    def test_rejects_unknown_resource(self):
        game, players = make_game()
        with self.assertRaises(ValueError):
            game.sail_exekratys(players[0].player_id, "victory")


if __name__ == "__main__":
    unittest.main()
