"""Tests for Leviathan (event 34) roll effect + special reward.

While Leviathan is in play, rolling a 6 adds a Strength token to the card,
raising its own slay cost (printed + tokens), capped at +10. Slaying it grants
1 VP per owned Monster.
"""

import unittest

from cards import Event, Monster
from game import Game
from game_models import Player


def make_monster(monster_id, name="Goblin", *, area="Forest", monster_type="Minion",
                 strength_cost=1, magic_cost=0):
    return Monster(
        monster_id, name, area, monster_type, 1,
        strength_cost, magic_cost,
        0, 0, 0, 0,              # vp/gold/strength/magic rewards
        False, None, False, None,
        False, "test",
    )


def make_leviathan(roll_effect="add_self_slay_cost s 1 max=10",
                   special_reward="count owned_monsters v 1"):
    ev = Event(
        34, "Leviathan",
        6,                       # roll_match1
        roll_effect,
        1,                       # has_roll_effect
        1,                       # is_monster
        0, 0,                    # has_activation/passive
        None, None,
        6, 16,                   # strength/magic cost
        "Boss",
        6, 0, 0, 0,              # vp/gold/strength/magic reward
        1, special_reward,       # has_special_reward, special_reward
        "crimsonseas",
    )
    ev.toggle_visibility(True)
    ev.toggle_accessibility(True)
    return ev


def make_game(n_players=3, *, turn_index=0, rolled=(1, 2)):
    players = []
    for i in range(n_players):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 50
        p.strength_score = 50
        p.magic_score = 50
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


class LeviathanRollEffectTests(unittest.TestCase):
    def test_roll_with_six_adds_one_strength_token(self):
        game, players = make_game(rolled=(6, 2))
        lev = make_leviathan()
        game.monster_grid[0].append(lev)

        game.finalize_roll(players[0].player_id)

        self.assertEqual(lev.extra_strength_cost, 1)
        # No prompt: the accrual is automatic.
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("action"), "")

    def test_roll_via_sum_of_six_triggers(self):
        game, players = make_game(rolled=(2, 4))  # sum 6
        lev = make_leviathan()
        game.monster_grid[0].append(lev)

        game.finalize_roll(players[0].player_id)

        self.assertEqual(lev.extra_strength_cost, 1)

    def test_roll_without_six_does_not_accrue(self):
        game, players = make_game(rolled=(2, 3))  # 2,3 sum 5 — no 6
        lev = make_leviathan()
        game.monster_grid[0].append(lev)

        game.finalize_roll(players[0].player_id)

        self.assertEqual(lev.extra_strength_cost, 0)

    def test_tokens_capped_at_ten(self):
        game, _players = make_game()
        lev = make_leviathan()
        lev.extra_strength_cost = 10
        game.monster_grid[0].append(lev)

        game.dice._execute_event_roll_effect(lev, game.lifecycle.current_player_id())

        self.assertEqual(lev.extra_strength_cost, 10)

    def test_accrual_steps_up_to_cap(self):
        game, _players = make_game()
        lev = make_leviathan()
        game.monster_grid[0].append(lev)
        pid = game.lifecycle.current_player_id()
        for _ in range(12):
            game.dice._execute_event_roll_effect(lev, pid)
        self.assertEqual(lev.extra_strength_cost, 10)


class LeviathanSlayTests(unittest.TestCase):
    def test_effective_slay_cost_includes_tokens(self):
        game, players = make_game(n_players=2, turn_index=0)
        game.phase = "action"
        lev = make_leviathan()
        lev.extra_strength_cost = 3   # printed 6 + 3 tokens = 9 strength
        game.monster_grid[0].append(lev)
        slayer = players[0]

        # Paying only the printed strength (6) is now insufficient.
        with self.assertRaises(ValueError):
            game.player_actions.slay_monster(slayer.player_id, monster_id=None, event_id=34, sp=6, mp=16)

        game.player_actions.slay_monster(slayer.player_id, monster_id=None, event_id=34, sp=9, mp=16)
        self.assertIn(lev, slayer.owned_monsters)

    def test_special_reward_grants_vp_per_owned_monster(self):
        game, players = make_game(n_players=2, turn_index=0)
        game.phase = "action"
        slayer = players[0]
        slayer.owned_monsters.append(make_monster(201))
        slayer.owned_monsters.append(make_monster(202))
        lev = make_leviathan()
        game.monster_grid[0].append(lev)

        before_vp = slayer.victory_score
        game.player_actions.slay_monster(slayer.player_id, monster_id=None, event_id=34, sp=6, mp=16)

        # owned_monsters now = 2 pre-owned + Leviathan = 3 -> 3 VP from
        # `count owned_monsters v 1`, plus the printed vp_reward of 6.
        self.assertEqual(slayer.victory_score - before_vp, 3 + 6)
        self.assertEqual(len(slayer.owned_monsters), 3)


class LeviathanDatabaseTests(unittest.TestCase):
    def test_live_db_event_effects_and_random_ready(self):
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
            cur.execute("SELECT * FROM events WHERE id_events = 34")
            row = cur.fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row.get("roll_effect"), "add_self_slay_cost s 1 max=10")
        self.assertEqual(row.get("special_reward"), "count owned_monsters v 1")

        from card_filters import keep_for_random
        self.assertTrue(keep_for_random("event", row))


if __name__ == "__main__":
    unittest.main()
