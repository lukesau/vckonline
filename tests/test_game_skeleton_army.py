"""Tests for Skeleton Army (event 36).

Two behaviors are covered:

1. Roll effect (`flip_citizen targeted optional`): while Skeleton Army is in
   play, rolling a 3 lets the active player flip one citizen on an opponent's
   tableau face-down for the rest of the game. The card text says "may", so the
   prompt is optional and reuses the monster reward's targeted-flip flow.

2. Special reward (`choose g 4 t 1`, i.e. "Gain 4 Gold or 1 Tome"): tomes are a
   Crimson Seas mechanic that isn't implemented yet. Outside Crimson Seas the
   tome leg is dropped so the player simply takes the gold; inside Crimson Seas
   the tome option is offered but selecting it raises an explicit error.
"""

import unittest

from cards import Citizen, Event
from game import Game
from game_models import Player


def make_citizen(citizen_id, name=None):
    c = Citizen(
        citizen_id, name or f"Citizen {citizen_id}",
        2,                       # gold_cost
        1, 0,                    # roll_match1, roll_match2
        0, 0, 0, 1,              # shadow/holy/soldier/worker
        1, 0,                    # gold payout on/off
        0, 0,                    # strength payout on/off
        0, 0,                    # magic payout on/off
        0, 0,                    # vp payout on/off
        False, False, "", "",
        False, "test",
    )
    c.toggle_visibility(True)
    c.toggle_accessibility(True)
    return c


def make_skeleton_army(roll_effect="flip_citizen targeted optional"):
    ev = Event(
        36, "Skeleton Army",
        3,                       # roll_match1
        roll_effect,
        1,                       # has_roll_effect
        1,                       # is_monster
        0, 0,                    # has_activation/passive
        None, None,
        7, 5,                    # strength/magic cost
        "Minion",
        4, 0, 0, 0,              # vp/gold/strength/magic reward
        1, "choose g 4 t 1",     # has_special_reward, special_reward
        "crimsonseas",
    )
    ev.toggle_visibility(True)
    ev.toggle_accessibility(True)
    return ev


def make_game(n_players=3, *, turn_index=0, preset=None):
    players = []
    for i in range(n_players):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 10
        p.strength_score = 10
        p.magic_score = 10
        p.victory_score = 0
        players.append(p)
    state = {
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [[], [], [], [], []],
        "citizen_grid": [[], [], [], [], [], [], [], [], [], []],
        "domain_grid": [[], [], [], [], []],
        "die_one": 1, "die_two": 2, "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": turn_index,
        "phase": "roll_pending",
        "actions_remaining": 0,
        "pending_roll": {"rolled_die_one": 1, "rolled_die_two": 3, "rolled_die_sum": 4},
    }
    if preset is not None:
        state["preset"] = preset
    game = Game(state)
    game.action_required["id"] = game.lifecycle.current_player_id()
    game.action_required["action"] = "finalize_roll"
    return game, players


class SkeletonArmyRollEffectTests(unittest.TestCase):
    def test_roll_containing_three_opens_optional_flip_prompt(self):
        game, players = make_game()
        players[1].owned_citizens.append(make_citizen(201, "Victim"))
        game.monster_grid[0].append(make_skeleton_army())

        game.finalize_roll(players[0].player_id)

        self.assertEqual(game.phase, "harvest")
        self.assertEqual(game.action_required.get("id"), players[0].player_id)
        self.assertEqual(game.action_required.get("action"), "choose_player")
        prc = game.pending_required_choice
        self.assertEqual(prc.get("kind"), "monster_flip_citizen_targeted")
        self.assertTrue(prc.get("allow_skip"))
        self.assertEqual([o["player_id"] for o in prc["options"]], [players[1].player_id])

    def test_flip_choice_flips_opponent_citizen_face_down(self):
        game, players = make_game()
        victim = make_citizen(201, "Victim")
        players[1].owned_citizens.append(victim)
        game.monster_grid[0].append(make_skeleton_army())

        game.finalize_roll(players[0].player_id)
        game.act_on_required_action(players[0].player_id, "choose_player 1")
        game.act_on_required_action(players[0].player_id, "choose_owned_card 1")

        self.assertTrue(victim.is_flipped)
        self.assertIn(victim, players[1].owned_citizens)
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("id"), game.game_id)
        self.assertEqual(game.action_required.get("action"), "")

    def test_optional_skip_leaves_citizens_unflipped(self):
        game, players = make_game()
        victim = make_citizen(201, "Victim")
        players[1].owned_citizens.append(victim)
        game.monster_grid[0].append(make_skeleton_army())

        game.finalize_roll(players[0].player_id)
        game.act_on_required_action(players[0].player_id, "skip")

        self.assertFalse(victim.is_flipped)
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("action"), "")

    def test_roll_without_three_does_not_prompt(self):
        game, players = make_game()
        game.pending_roll = {"rolled_die_one": 2, "rolled_die_two": 4, "rolled_die_sum": 6}
        players[1].owned_citizens.append(make_citizen(201, "Victim"))
        game.monster_grid[0].append(make_skeleton_army())

        game.finalize_roll(players[0].player_id)

        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("id"), game.game_id)
        self.assertEqual(game.action_required.get("action"), "")

    def test_no_eligible_opponent_citizens_auto_skips(self):
        game, players = make_game()
        # Active player owns a citizen, but no opponent does -> nothing to flip.
        players[0].owned_citizens.append(make_citizen(201, "Mine"))
        game.monster_grid[0].append(make_skeleton_army())

        game.finalize_roll(players[0].player_id)

        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("action"), "")


class SkeletonArmyTomeRewardTests(unittest.TestCase):
    def test_outside_crimson_seas_drops_tome_and_grants_gold(self):
        game, players = make_game(preset="random")
        before = int(players[0].gold_score)

        payout = game.payouts.execute_special_payout(
            "choose g 4 t 1", players[0].player_id, auto_apply_single_choice=True
        )

        # Only the gold "out" survives, so it auto-applies with no prompt.
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(int(players[0].gold_score), before + 4)

    def test_crimson_seas_offers_both_options(self):
        game, players = make_game(preset="crimsonseas")

        game.payouts.execute_special_payout(
            "choose g 4 t 1", players[0].player_id, auto_apply_single_choice=True
        )

        prc = game.pending_required_choice
        self.assertEqual(prc.get("kind"), "special_payout_choose")
        tokens = [o.get("token") for o in prc.get("options") or []]
        self.assertEqual(tokens, ["g", "t"])

    def test_crimson_seas_taking_gold_works(self):
        game, players = make_game(preset="crimsonseas")
        before = int(players[0].gold_score)

        game.payouts.execute_special_payout(
            "choose g 4 t 1", players[0].player_id, auto_apply_single_choice=True
        )
        game.act_on_required_action(players[0].player_id, "choose 1")

        self.assertEqual(int(players[0].gold_score), before + 4)
        self.assertIsNone(game.pending_required_choice)

    def test_crimson_seas_taking_tome_raises(self):
        game, players = make_game(preset="crimsonseas")

        game.payouts.execute_special_payout(
            "choose g 4 t 1", players[0].player_id, auto_apply_single_choice=True
        )

        with self.assertRaises(ValueError):
            game.act_on_required_action(players[0].player_id, "choose 2")


class SkeletonArmyDatabaseTests(unittest.TestCase):
    def test_live_db_event_has_flip_roll_effect(self):
        try:
            import mariadb
        except ImportError as exc:
            raise unittest.SkipTest("mariadb connector is not installed") from exc

        try:
            conn = mariadb.connect(
                user="vckonline",
                password="vckonline",
                host="127.0.0.1",
                port=3306,
                database="vckonline",
            )
        except mariadb.Error as exc:
            raise unittest.SkipTest(f"database unavailable: {exc}") from exc

        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM events WHERE id_events = 36")
            row = cur.fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row.get("roll_effect"), "flip_citizen targeted optional")
        self.assertEqual(int(row.get("roll_match1")), 3)
        self.assertEqual(row.get("special_reward"), "choose g 4 t 1")


if __name__ == "__main__":
    unittest.main()
