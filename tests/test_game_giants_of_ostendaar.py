"""Tests for Giants of Ostendaar (event 33) roll effect.

While Giants of Ostendaar is in play, rolling a 5 lets the active player banish
one face-up domain from the center stacks and reveal the next domain beneath.
The card text says "may", so the prompt is optional.
"""

import unittest

from cards import Domain, Event
from game import Game
from game_models import Player


def make_domain(domain_id, name="Keep", gold_cost=3, *, visible=False):
    d = Domain(
        domain_id, name, gold_cost,
        0, 0, 0, 0,              # role requirements
        0,                       # vp_reward
        False, False,            # has_activation/passive
        "", "", "", "test",
    )
    if visible:
        d.toggle_visibility(True)
        d.toggle_accessibility(True)
    return d


def make_giants_event(roll_effect="banish_center_domain optional"):
    ev = Event(
        33, "Giants of Ostendaar",
        5,                       # roll_match1
        roll_effect,
        1,                       # has_roll_effect
        1,                       # is_monster
        0, 0,                    # has_activation/passive
        None, None,
        10, 2,                   # strength/magic cost
        "Titan",
        3, 0, 0, 0,              # vp/gold/strength/magic reward
        1, "<domains>",          # has_special_reward, special_reward
        "crimsonseas",
    )
    ev.toggle_visibility(True)
    ev.toggle_accessibility(True)
    return ev


def make_game(n_players=3, *, turn_index=0, rolled=(2, 3)):
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
        "pending_roll": {
            "rolled_die_one": rolled[0],
            "rolled_die_two": rolled[1],
            "rolled_die_sum": rolled[0] + rolled[1],
        },
    })
    game.action_required["id"] = game.lifecycle.current_player_id()
    game.action_required["action"] = "finalize_roll"
    return game, players


class GiantsOfOstendaarRollEffectTests(unittest.TestCase):
    def test_roll_containing_five_opens_optional_center_domain_prompt(self):
        game, players = make_game(rolled=(2, 3))  # sum 5
        hidden = make_domain(101, "Hidden Keep")
        top = make_domain(102, "Top Keep", visible=True)
        game.domain_grid[0].extend([hidden, top])
        game.monster_grid[0].append(make_giants_event())

        game.finalize_roll(players[0].player_id)

        self.assertEqual(game.phase, "harvest")
        self.assertEqual(game.action_required.get("id"), players[0].player_id)
        self.assertEqual(game.action_required.get("action"), "choose_owned_card")
        prc = game.pending_required_choice
        self.assertEqual(prc.get("kind"), "banish_center_card")
        self.assertEqual(prc.get("card_kind"), "domain")
        self.assertTrue(prc.get("allow_skip"))
        self.assertEqual(prc["options"][0]["name"], "Top Keep")

    def test_banish_removes_top_domain_and_reveals_next(self):
        game, players = make_game(rolled=(5, 1))
        hidden = make_domain(101, "Hidden Keep")
        top = make_domain(102, "Top Keep", visible=True)
        game.domain_grid[0].extend([hidden, top])
        game.monster_grid[0].append(make_giants_event())

        game.finalize_roll(players[0].player_id)
        game.act_on_required_action(players[0].player_id, "choose_owned_card 1")

        self.assertEqual(game.domain_grid[0], [hidden])
        self.assertIn(top, game.banish_pile)
        self.assertTrue(hidden.is_visible)
        self.assertTrue(hidden.is_accessible)
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("id"), game.game_id)
        self.assertEqual(game.action_required.get("action"), "")

    def test_banish_last_domain_empties_stack_when_no_exhausted(self):
        game, players = make_game(rolled=(5, 1))
        only = make_domain(102, "Only Keep", visible=True)
        game.domain_grid[0].append(only)
        game.monster_grid[0].append(make_giants_event())

        game.finalize_roll(players[0].player_id)
        game.act_on_required_action(players[0].player_id, "choose_owned_card 1")

        self.assertEqual(game.domain_grid[0], [])
        self.assertIn(only, game.banish_pile)

    def test_optional_skip_leaves_domains_in_play(self):
        game, players = make_game(rolled=(5, 1))
        top = make_domain(102, "Top Keep", visible=True)
        game.domain_grid[0].append(top)
        game.monster_grid[0].append(make_giants_event())

        game.finalize_roll(players[0].player_id)
        game.act_on_required_action(players[0].player_id, "skip")

        self.assertEqual(game.domain_grid[0], [top])
        self.assertEqual(game.banish_pile, [])
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("action"), "")

    def test_roll_without_five_does_not_prompt(self):
        game, players = make_game(rolled=(2, 4))  # sum 6, no 5
        game.domain_grid[0].append(make_domain(102, "Top Keep", visible=True))
        game.monster_grid[0].append(make_giants_event())

        game.finalize_roll(players[0].player_id)

        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("action"), "")

    def test_face_down_domain_top_is_not_a_target(self):
        game, players = make_game(rolled=(5, 1))
        # Domain present but its top is still face-down (not yet revealed).
        face_down = make_domain(102, "Face Down Keep")
        game.domain_grid[0].append(face_down)
        game.monster_grid[0].append(make_giants_event())

        game.finalize_roll(players[0].player_id)

        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.domain_grid[0], [face_down])
        self.assertEqual(game.banish_pile, [])
        self.assertEqual(game.action_required.get("action"), "")


class GiantsOfOstendaarDatabaseTests(unittest.TestCase):
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
            cur.execute("SELECT * FROM events WHERE id_events = 33")
            row = cur.fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row.get("roll_effect"), "banish_center_domain optional")

        from card_filters import keep_for_random
        self.assertTrue(keep_for_random("event", row))


if __name__ == "__main__":
    unittest.main()
