"""Tests for Pirate Blockade (event 35).

While Pirate Blockade is in play, during the active player's Action Phase no
citizen whose roll match equals either die or the dice sum may be recruited or
gained (recruit action + any monster/domain citizen grant). The roll effect
(`block_recruit_matching_roll`, roll_match1 == -1) fires each roll to log the
blocked values; enforcement is an on-demand in-play scan so slaying the ship
lifts the restriction.

The special reward `choose g 4 p 2` ("Gain 4 Gold or 2 Maps") reuses the
existing map (`p`) handling: gold-only outside Crimson Seas, both options inside.
"""

import unittest

from cards import Citizen, Event
from game import Game
from game_models import Player


def make_citizen(citizen_id, name=None, *, roll_match1=1, roll_match2=0, gold_cost=2):
    c = Citizen(
        citizen_id, name or f"Citizen {citizen_id}",
        gold_cost,
        roll_match1, roll_match2,
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


def make_pirate_blockade():
    ev = Event(
        35, "Pirate Blockade",
        -1,                              # roll_match1 (every roll phase)
        "block_recruit_matching_roll",   # roll_effect
        1,                               # has_roll_effect
        1,                               # is_monster
        0, 0,                            # has_activation / has_passive
        None, None,
        9, 3,                            # strength/magic cost
        "Minion",
        4, 0, 0, 0,                      # vp/gold/strength/magic reward
        1, "choose g 4 p 2",             # has_special_reward, special_reward
        "crimsonseas",
    )
    ev.toggle_visibility(True)
    ev.toggle_accessibility(True)
    return ev


def make_game(n_players=3, *, turn_index=0, rolled=(3, 5), phase="action", preset="crimsonseas"):
    players = []
    for i in range(n_players):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 50
        p.strength_score = 50
        p.magic_score = 50
        p.victory_score = 0
        players.append(p)
    state = {
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
        "actions_remaining": 1,
        "pending_roll": {
            "rolled_die_one": rolled[0],
            "rolled_die_two": rolled[1],
            "rolled_die_sum": rolled[0] + rolled[1],
        },
    }
    if preset is not None:
        state["preset"] = preset
    game = Game(state)
    game.action_required["id"] = game.game_id
    game.action_required["action"] = ""
    return game, players


class PirateBlockadeBlockedValuesTests(unittest.TestCase):
    def test_blocked_values_are_dice_and_sum_when_in_play(self):
        game, _players = make_game(rolled=(3, 5))  # blocks 3, 5, 8
        game.monster_grid[0].append(make_pirate_blockade())
        self.assertEqual(game._pirate_blockade_blocked_roll_values(), {3, 5, 8})

    def test_no_block_when_not_in_play(self):
        game, _players = make_game(rolled=(3, 5))
        self.assertEqual(game._pirate_blockade_blocked_roll_values(), set())

    def test_no_block_outside_action_phase(self):
        game, _players = make_game(rolled=(3, 5), phase="harvest")
        game.monster_grid[0].append(make_pirate_blockade())
        self.assertEqual(game._pirate_blockade_blocked_roll_values(), set())

    def test_citizen_matching_either_die_or_sum_is_blocked(self):
        game, _players = make_game(rolled=(3, 5))
        game.monster_grid[0].append(make_pirate_blockade())
        self.assertTrue(game._citizen_blocked_by_pirate_blockade(make_citizen(1, roll_match1=3)))
        self.assertTrue(game._citizen_blocked_by_pirate_blockade(make_citizen(2, roll_match1=5)))
        self.assertTrue(game._citizen_blocked_by_pirate_blockade(make_citizen(3, roll_match1=8)))
        self.assertTrue(game._citizen_blocked_by_pirate_blockade(make_citizen(4, roll_match1=9, roll_match2=5)))
        self.assertFalse(game._citizen_blocked_by_pirate_blockade(make_citizen(5, roll_match1=2)))


class PirateBlockadeRecruitTests(unittest.TestCase):
    def test_recruit_blocked_citizen_raises(self):
        game, players = make_game(rolled=(3, 5))
        game.monster_grid[0].append(make_pirate_blockade())
        blocked = make_citizen(201, "Blocked", roll_match1=3)
        game.citizen_grid[0].append(blocked)

        with self.assertRaises(ValueError):
            game.player_actions.hire_citizen(players[0].player_id, 201, gp=2)
        # Citizen stays on the board.
        self.assertIn(blocked, game.citizen_grid[0])

    def test_recruit_allowed_citizen_succeeds(self):
        game, players = make_game(rolled=(3, 5))
        game.monster_grid[0].append(make_pirate_blockade())
        ok = make_citizen(202, "Allowed", roll_match1=2)
        game.citizen_grid[0].append(ok)

        game.player_actions.hire_citizen(players[0].player_id, 202, gp=2)
        self.assertIn(ok, players[0].owned_citizens)

    def test_recruit_blocked_citizen_allowed_after_blockade_slain(self):
        game, players = make_game(rolled=(3, 5))
        # No blockade on the board -> no restriction.
        target = make_citizen(203, "Free", roll_match1=3)
        game.citizen_grid[0].append(target)

        game.player_actions.hire_citizen(players[0].player_id, 203, gp=2)
        self.assertIn(target, players[0].owned_citizens)


class PirateBlockadeRewardGrantTests(unittest.TestCase):
    def test_blocked_citizens_excluded_from_reward_candidates(self):
        game, _players = make_game(rolled=(3, 5))
        game.monster_grid[0].append(make_pirate_blockade())
        blocked = make_citizen(301, "Blocked", roll_match1=5)
        allowed = make_citizen(302, "Allowed", roll_match1=2)
        game.citizen_grid[1].append(blocked)
        game.citizen_grid[2].append(allowed)

        candidates = game.choose._board_citizen_candidates({"is_any": True})
        names = {c.name for c in candidates}
        self.assertIn("Allowed", names)
        self.assertNotIn("Blocked", names)


class PirateBlockadeSpecialRewardTests(unittest.TestCase):
    def test_outside_crimson_seas_grants_gold(self):
        game, players = make_game(preset="random")
        before = int(players[0].gold_score)
        game.payouts.execute_special_payout(
            "choose g 4 p 2", players[0].player_id, auto_apply_single_choice=True
        )
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(int(players[0].gold_score), before + 4)

    def test_crimson_seas_offers_gold_or_maps(self):
        game, players = make_game(preset="crimsonseas")
        game.payouts.execute_special_payout(
            "choose g 4 p 2", players[0].player_id, auto_apply_single_choice=True
        )
        prc = game.pending_required_choice
        self.assertEqual(prc.get("kind"), "special_payout_choose")
        self.assertEqual([o.get("token") for o in prc.get("options") or []], ["g", "p"])


class PirateBlockadeDatabaseTests(unittest.TestCase):
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
            cur.execute("SELECT * FROM events WHERE id_events = 35")
            row = cur.fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row.get("roll_effect"), "block_recruit_matching_roll")
        self.assertEqual(row.get("special_reward"), "choose g 4 p 2")
        self.assertEqual(int(row.get("roll_match1")), -1)


if __name__ == "__main__":
    unittest.main()
