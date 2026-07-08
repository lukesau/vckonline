"""Tests for Flaming Devourer (event 31) roll effect.

While Flaming Devourer is in play, rolling a 4 lets the active player banish
one citizen from the center stacks. The card text says "may", so the prompt is
optional.
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


def make_flaming_devourer(roll_effect="banish_center_citizen optional"):
    ev = Event(
        31, "Flaming Devourer",
        4,                       # roll_match1
        roll_effect,
        1,                       # has_roll_effect
        1,                       # is_monster
        0, 0,                    # has_activation/passive
        None, None,
        5, 5,                    # strength/magic cost
        "Boss",
        3, 0, 0, 0,              # vp/gold/strength/magic reward
        0, None,
        "crimsonseas",
    )
    ev.toggle_visibility(True)
    ev.toggle_accessibility(True)
    return ev


def make_game(n_players=3, *, turn_index=0):
    players = []
    for i in range(n_players):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 10
        p.strength_score = 10
        p.magic_score = 10
        p.victory_score = 0
        players.append(p)
    game = Game({
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
    })
    game.action_required["id"] = game.lifecycle.current_player_id()
    game.action_required["action"] = "finalize_roll"
    return game, players


class FlamingDevourerRollEffectTests(unittest.TestCase):
    def test_roll_containing_four_opens_optional_center_banish_prompt(self):
        game, players = make_game()
        target = make_citizen(201, "Target")
        game.citizen_grid[0].append(target)
        game.monster_grid[0].append(make_flaming_devourer())

        game.finalize_roll(players[0].player_id)

        self.assertEqual(game.phase, "harvest")
        self.assertEqual(game.action_required.get("id"), players[0].player_id)
        self.assertEqual(game.action_required.get("action"), "choose_owned_card")
        self.assertEqual(game.pending_required_choice.get("kind"), "banish_center_card")
        self.assertEqual(game.pending_required_choice.get("card_kind"), "citizen")
        self.assertTrue(game.pending_required_choice.get("allow_skip"))
        self.assertEqual(game.pending_required_choice["options"][0]["name"], "Target")

    def test_banish_choice_removes_center_citizen_to_banish_pile(self):
        game, players = make_game()
        target = make_citizen(201, "Target")
        game.citizen_grid[0].append(target)
        game.monster_grid[0].append(make_flaming_devourer())

        game.finalize_roll(players[0].player_id)
        game.act_on_required_action(players[0].player_id, "choose_owned_card 1")

        self.assertEqual(game.citizen_grid[0], [])
        self.assertIn(target, game.banish_pile)
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("id"), game.game_id)
        self.assertEqual(game.action_required.get("action"), "")

    def test_optional_skip_leaves_center_citizen_in_play(self):
        game, players = make_game()
        target = make_citizen(201, "Target")
        game.citizen_grid[0].append(target)
        game.monster_grid[0].append(make_flaming_devourer())

        game.finalize_roll(players[0].player_id)
        game.act_on_required_action(players[0].player_id, "skip")

        self.assertEqual(game.citizen_grid[0], [target])
        self.assertEqual(game.banish_pile, [])
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("id"), game.game_id)
        self.assertEqual(game.action_required.get("action"), "")

    def test_roll_without_four_does_not_prompt(self):
        game, players = make_game()
        game.pending_roll = {"rolled_die_one": 2, "rolled_die_two": 3, "rolled_die_sum": 5}
        game.citizen_grid[0].append(make_citizen(201, "Target"))
        game.monster_grid[0].append(make_flaming_devourer())

        game.finalize_roll(players[0].player_id)

        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("id"), game.game_id)
        self.assertEqual(game.action_required.get("action"), "")

    def test_no_accessible_center_citizens_auto_skips(self):
        game, players = make_game()
        inaccessible = make_citizen(201, "Hidden")
        inaccessible.toggle_accessibility(False)
        game.citizen_grid[0].append(inaccessible)
        game.monster_grid[0].append(make_flaming_devourer())

        game.finalize_roll(players[0].player_id)

        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.citizen_grid[0], [inaccessible])
        self.assertEqual(game.banish_pile, [])
        self.assertEqual(game.action_required.get("id"), game.game_id)
        self.assertEqual(game.action_required.get("action"), "")


class FlamingDevourerDatabaseTests(unittest.TestCase):
    def test_live_db_event_has_optional_roll_effect_and_is_random_ready(self):
        try:
            import mariadb
        except ImportError as exc:
            raise unittest.SkipTest("mariadb connector is not installed") from exc

        try:
            from db_config import connect

            conn = connect()
        except mariadb.Error as exc:
            raise unittest.SkipTest(f"database unavailable: {exc}") from exc

        try:
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM events WHERE id_events = 31")
            row = cur.fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row.get("roll_effect"), "banish_center_citizen optional")

        from card_filters import keep_for_random
        self.assertTrue(keep_for_random("event", row))


if __name__ == "__main__":
    unittest.main()
