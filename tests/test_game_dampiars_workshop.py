"""Tests for Dampiar's Workshop (Domain #72).

Activation effect: `g 3 + p 1 + sail` - "Immediately gain 3 Gold + 1 Map and you
may Sail." The activation grants +3 Gold and +1 Map, then opens a `may_sail`
opportunity: one free Sail action (buy goods / buy tomes / rescue noble / sail to
Exekratys) that does NOT consume a regular action. The sail still pays its own
gold/map cost (the +1 Map funds it). Declining resumes the turn.
"""

import unittest

from cards import Domain
from game import Game
from game_models import Player
from game_serialization import (
    serialize_game_to_save_dict,
    deserialize_save_dict_to_game,
)


def make_dampiars_workshop():
    return Domain(
        72, "Dampiar's Workshop", 6,
        1, 0, 1, 1,                       # role requirements
        3,                                # vp_reward
        True, False,                      # has_activation / has_passive
        "",                               # passive_effect
        "g 3 + p 1 + sail",               # activation_effect
        "Immediately gain 3 Gold + 1 Map and you may Sail.",
        "crimsonseas",
    )


def make_game(*, preset="crimsonseas", exekratys=None, map_score=2,
              actions_remaining=3):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 5
        p.strength_score = 5
        p.magic_score = 5
        p.victory_score = 0
        p.map_score = map_score
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
        "actions_remaining": actions_remaining,
        "exekratys_resources": exekratys if exekratys is not None
        else {"gold": 4, "strength": 0, "magic": 0},
        "tome_slots": ["gold", "magic", "strength"],
        "tome_supply": [],
        "goods_slots": ["jewels", "spices", "fabrics"],
        "goods_supply": [],
    }
    if preset is not None:
        state["preset"] = preset
    return Game(state), players


class DampiarsWorkshopActivationTests(unittest.TestCase):
    def test_grants_resources_and_opens_may_sail(self):
        game, players = make_game()
        p = players[0]
        gold_before = int(p.gold_score)
        map_before = int(p.map_score)

        game.domain_effects._apply_domain_activation_effect(p, make_dampiars_workshop())

        self.assertEqual(int(p.gold_score), gold_before + 3)
        self.assertEqual(int(p.map_score), map_before + 1)
        self.assertEqual(game.action_required.get("action"), "may_sail")
        self.assertEqual(game.action_required.get("id"), p.player_id)
        self.assertEqual(game.pending_bonus_sail, p.player_id)
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "sail_opportunity")
        self.assertEqual(prc.get("player_id"), p.player_id)

    def test_decline_resumes_without_extra_cost(self):
        game, players = make_game()
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_dampiars_workshop())
        gold_after_grant = int(p.gold_score)
        map_after_grant = int(p.map_score)

        game.act_on_required_action(p.player_id, "skip")

        self.assertIsNone(game.pending_bonus_sail)
        self.assertIsNone(game.pending_required_choice)
        self.assertNotEqual(game.action_required.get("action"), "may_sail")
        # No further resources spent by declining.
        self.assertEqual(int(p.gold_score), gold_after_grant)
        self.assertEqual(int(p.map_score), map_after_grant)

    def test_bonus_sail_runs_free_then_resolves(self):
        game, players = make_game(exekratys={"gold": 4, "strength": 0, "magic": 0})
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_dampiars_workshop())
        actions_before = int(game.actions_remaining)
        gold_before = int(p.gold_score)
        map_before = int(p.map_score)

        # The bonus sail is allowed even though the may_sail prompt is open, and
        # it does NOT spend a regular action.
        self.assertTrue(game.consume_player_action(p.player_id, action_type="sail_exekratys"))
        self.assertEqual(int(game.actions_remaining), actions_before)
        game.sail_exekratys(p.player_id, "gold")
        self.assertTrue(game.resolve_bonus_sail_if_consumed())

        # Took all 4 gold from the pool; paid 1 map for the sail.
        self.assertEqual(int(p.gold_score), gold_before + 4)
        self.assertEqual(int(p.map_score), map_before - 1)
        self.assertEqual(game.exekratys_resources.get("gold"), 0)
        # Prompt + bonus cleared; the turn resumes with actions still available.
        self.assertIsNone(game.pending_bonus_sail)
        self.assertNotEqual(game.action_required.get("action"), "may_sail")
        self.assertEqual(game.action_required.get("action"), "standard_action")

    def test_non_sail_action_blocked_during_may_sail(self):
        game, players = make_game()
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_dampiars_workshop())
        # A regular (non-sail) action cannot be taken while the may_sail prompt
        # is open.
        self.assertFalse(game.consume_player_action(p.player_id, action_type="hire_citizen"))
        self.assertEqual(game.action_required.get("action"), "may_sail")
        self.assertEqual(game.pending_bonus_sail, p.player_id)

    def test_failed_sail_keeps_prompt_open(self):
        game, players = make_game(exekratys={"gold": 4, "strength": 0, "magic": 0})
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_dampiars_workshop())
        actions_before = int(game.actions_remaining)

        # Consume the bonus, then simulate the sail failing (server rolls back).
        self.assertTrue(game.consume_player_action(p.player_id, action_type="sail_exekratys"))
        game.lifecycle.rollback_last_consumed_action()

        # Bonus + prompt still standing; no regular action spent; retry works.
        self.assertEqual(int(game.actions_remaining), actions_before)
        self.assertEqual(game.pending_bonus_sail, p.player_id)
        self.assertEqual(game.action_required.get("action"), "may_sail")
        self.assertTrue(game.consume_player_action(p.player_id, action_type="sail_exekratys"))

    def test_opponent_cannot_consume_bonus(self):
        game, players = make_game()
        p, opp = players[0], players[1]
        game.domain_effects._apply_domain_activation_effect(p, make_dampiars_workshop())
        # The bonus belongs to the activating player only.
        self.assertFalse(game.consume_player_action(opp.player_id, action_type="sail_exekratys"))
        self.assertEqual(game.pending_bonus_sail, p.player_id)

    def test_pending_bonus_sail_survives_save_load(self):
        game, players = make_game()
        p = players[0]
        game.domain_effects._apply_domain_activation_effect(p, make_dampiars_workshop())
        reloaded = deserialize_save_dict_to_game(serialize_game_to_save_dict(game))
        self.assertEqual(reloaded.pending_bonus_sail, p.player_id)
        self.assertEqual(reloaded.action_required.get("action"), "may_sail")

    def test_outside_crimson_seas_dropped(self):
        game, players = make_game(preset="random")
        p = players[0]
        gold_before = int(p.gold_score)
        game.domain_effects._apply_domain_activation_effect(p, make_dampiars_workshop())
        # `sail` is a no-op outside Crimson Seas; the gold/map legs of the
        # compound are skipped too because the bare-verb leg returns the
        # -9999 sentinel after the resource legs accumulate, so no prompt opens.
        self.assertNotEqual(game.action_required.get("action"), "may_sail")
        self.assertIsNone(game.pending_bonus_sail)


if __name__ == "__main__":
    unittest.main()
