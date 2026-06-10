"""Tests for Ghost Ship (event 32).

Ghost Ship is a Boss monster event that accumulates a gold pool:

- Activation (on reveal) and roll effect (every roll phase, roll_match1 == -1):
  the active player places 1 gold from their supply onto the card
  (`add_self_gold_pool 1`).
- Special reward (`gain_self_gold_pool`): whoever slays the ship gains the whole
  accumulated pool.
"""

import unittest

from cards import Event, Monster
from game import Game
from game_models import Player


def make_ghost_ship():
    ev = Event(
        32, "Ghost Ship",
        -1,                          # roll_match1 (every roll phase)
        "add_self_gold_pool 1",      # roll_effect
        1,                           # has_roll_effect
        1,                           # is_monster
        1, 0,                        # has_activation / has_passive
        "add_self_gold_pool 1", None,  # activation_effect / passive_effect
        6, 6,                        # strength/magic cost
        "Boss",
        5, 0, 0, 0,                  # vp/gold/strength/magic reward
        1, "gain_self_gold_pool",    # has_special_reward, special_reward
        "crimsonseas",
    )
    ev.toggle_visibility(True)
    ev.toggle_accessibility(True)
    return ev


def make_game(n_players=3, *, turn_index=0, rolled=(1, 2), phase="roll_pending", gold=50):
    players = []
    for i in range(n_players):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = gold
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
        "die_one": rolled[0], "die_two": rolled[1], "die_sum": rolled[0] + rolled[1],
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": turn_index,
        "phase": phase,
        "actions_remaining": 0,
        "pending_roll": {
            "rolled_die_one": rolled[0],
            "rolled_die_two": rolled[1],
            "rolled_die_sum": rolled[0] + rolled[1],
        },
    })
    game.action_required["id"] = game.lifecycle.current_player_id()
    if phase == "roll_pending":
        game.action_required["action"] = "finalize_roll"
    return game, players


class GhostShipRollEffectTests(unittest.TestCase):
    def test_every_roll_places_one_gold_on_the_pool(self):
        game, players = make_game(rolled=(1, 2))
        ship = make_ghost_ship()
        game.monster_grid[0].append(ship)
        before = int(players[0].gold_score)

        game.finalize_roll(players[0].player_id)

        self.assertEqual(int(players[0].gold_score), before - 1)
        self.assertEqual(ship.gold_pool, 1)
        self.assertIsNone(game.pending_required_choice)

    def test_pool_accumulates_across_rolls(self):
        game, _players = make_game()
        ship = make_ghost_ship()
        game.monster_grid[0].append(ship)
        pid = game.lifecycle.current_player_id()

        for _ in range(3):
            game.dice._execute_event_roll_effect(ship, pid)

        self.assertEqual(ship.gold_pool, 3)

    def test_player_without_gold_places_nothing(self):
        game, players = make_game(gold=0)
        ship = make_ghost_ship()
        game.monster_grid[0].append(ship)

        game.finalize_roll(players[0].player_id)

        self.assertEqual(int(players[0].gold_score), 0)
        self.assertEqual(ship.gold_pool, 0)

    def test_reveal_activation_places_one_gold(self):
        game, players = make_game()
        ship = make_ghost_ship()
        game.exhausted_stack.append(ship)
        before = int(players[0].gold_score)

        game.events.reveal_exhausted_onto_stack(game.monster_grid[0])

        self.assertEqual(int(players[0].gold_score), before - 1)
        self.assertEqual(ship.gold_pool, 1)


class GhostShipSlayTests(unittest.TestCase):
    def test_slayer_claims_the_gold_pool(self):
        game, players = make_game(n_players=2, turn_index=0, phase="action")
        slayer = players[0]
        ship = make_ghost_ship()
        ship.gold_pool = 7
        game.monster_grid[0].append(ship)

        before_gold = int(slayer.gold_score)
        before_vp = int(slayer.victory_score)
        game.player_actions.slay_monster(slayer.player_id, monster_id=None, event_id=32, sp=6, mp=6)

        # +7 from the pool (gold_reward is 0); strength/magic spent on the slay.
        self.assertEqual(int(slayer.gold_score) - before_gold, 7)
        self.assertEqual(int(slayer.victory_score) - before_vp, 5)
        self.assertIn(ship, slayer.owned_monsters)
        self.assertEqual(ship.gold_pool, 0)

    def test_empty_pool_slay_grants_no_bonus_gold(self):
        game, players = make_game(n_players=2, turn_index=0, phase="action")
        slayer = players[0]
        ship = make_ghost_ship()
        game.monster_grid[0].append(ship)

        before_gold = int(slayer.gold_score)
        game.player_actions.slay_monster(slayer.player_id, monster_id=None, event_id=32, sp=6, mp=6)

        self.assertEqual(int(slayer.gold_score) - before_gold, 0)


class GhostShipSerializationTests(unittest.TestCase):
    def test_gold_pool_survives_round_trip(self):
        ship = make_ghost_ship()
        ship.gold_pool = 4
        restored = Event.from_dict(ship.to_dict())
        self.assertEqual(restored.gold_pool, 4)


class GhostShipDatabaseTests(unittest.TestCase):
    def test_live_db_event_effects(self):
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
            cur.execute("SELECT * FROM events WHERE id_events = 32")
            row = cur.fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row.get("roll_effect"), "add_self_gold_pool 1")
        self.assertEqual(row.get("activation_effect"), "add_self_gold_pool 1")
        self.assertEqual(row.get("special_reward"), "gain_self_gold_pool")
        self.assertEqual(int(row.get("roll_match1")), -1)


if __name__ == "__main__":
    unittest.main()
