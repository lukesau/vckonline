"""Tests for Gargan Soul Hunters (monster 147).

Special reward (`choose <citizens 3> <noble>`, i.e. "Gain 3 Citizens or 1
Noble"):

- The "3 Citizens" leg is a single prompt option. Once picked it chains three
  separate `<citizens>` picks via the payout-continuation machinery rather than
  inventing a new multi-citizen mechanic.
- The "1 Noble" leg is a Crimson Seas mechanic: it expands into one pick per
  face-up Amarynth noble. Taking one is free (no resources, no map) and the
  emptied slot refills directly from the Noble deck.
"""

import unittest

from cards import Citizen, Noble
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


def make_noble(noble_id, name):
    return Noble(
        noble_id, name,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0,
        0, None, "crimsonseas",
    )


def make_game(*, preset="crimsonseas", n_board_citizens=0, noble_slots=None, noble_supply=None):
    players = []
    for i in range(2):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 10
        p.strength_score = 10
        p.magic_score = 10
        p.victory_score = 0
        p.map_score = 3
        players.append(p)

    citizen_grid = [[] for _ in range(10)]
    for i in range(n_board_citizens):
        citizen_grid[i].append(make_citizen(300 + i, f"Board {i}"))

    if noble_slots is None:
        noble_slots = [make_noble(1, "A"), make_noble(2, "B"), make_noble(3, "C")]
    if noble_supply is None:
        noble_supply = [make_noble(4, "D"), make_noble(5, "E")]

    state = {
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [[], [], [], [], []],
        "citizen_grid": citizen_grid,
        "domain_grid": [[], [], [], [], []],
        "die_one": 1, "die_two": 2, "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "action",
        "actions_remaining": 3,
        "noble_slots": noble_slots,
        "noble_supply": noble_supply,
    }
    if preset is not None:
        state["preset"] = preset
    return Game(state), players


class GarganRewardExpansionTests(unittest.TestCase):
    def test_crimson_seas_expands_into_chain_plus_one_pick_per_noble(self):
        game, players = make_game(n_board_citizens=5)

        game.payouts.execute_special_payout(
            "choose <citizens 3> <noble>", players[0].player_id, auto_apply_single_choice=True
        )

        prc = game.pending_required_choice
        self.assertEqual(prc.get("kind"), "special_payout_choose")
        options = prc.get("options") or []
        self.assertEqual(
            [o.get("token") for o in options],
            ["citizens_chain", "noble.choice", "noble.choice", "noble.choice"],
        )
        self.assertEqual(options[0].get("amount"), 3)
        self.assertEqual([o.get("name") for o in options if o.get("token") == "noble.choice"],
                         ["A", "B", "C"])

    def test_noble_leg_dropped_when_no_face_up_noble(self):
        game, players = make_game(n_board_citizens=5, noble_slots=[None, None, None])

        game.payouts.execute_special_payout(
            "choose <citizens 3> <noble>", players[0].player_id, auto_apply_single_choice=True
        )

        # Only the chain leg survives; as the sole option it auto-applies and
        # immediately opens the first of three citizen picks.
        prc = game.pending_required_choice
        self.assertIsNotNone(prc)
        self.assertEqual(prc.get("kind"), "special_payout_choose")
        self.assertTrue(all(o.get("token") == "citizens.choice" for o in prc.get("options") or []))

    def test_outside_crimson_seas_drops_noble_keeps_chain(self):
        game, players = make_game(preset="random", n_board_citizens=5)

        game.payouts.execute_special_payout(
            "choose <citizens 3> <noble>", players[0].player_id, auto_apply_single_choice=True
        )

        # Noble leg gone; chain leg is sole option -> auto-applies into the
        # first citizen pick.
        prc = game.pending_required_choice
        self.assertIsNotNone(prc)
        self.assertTrue(all(o.get("token") == "citizens.choice" for o in prc.get("options") or []))


class GarganNobleLegTests(unittest.TestCase):
    def test_taking_noble_is_free_and_refills_from_deck(self):
        game, players = make_game(n_board_citizens=5)
        gold_before = int(players[0].gold_score)
        map_before = int(players[0].map_score)

        game.payouts.execute_special_payout(
            "choose <citizens 3> <noble>", players[0].player_id, auto_apply_single_choice=True
        )
        # Options: 1=chain, 2=noble A, 3=noble B, 4=noble C. Take noble A.
        game.act_on_required_action(players[0].player_id, "choose 2")

        self.assertEqual([n.name for n in players[0].owned_nobles], ["A"])
        self.assertEqual(int(players[0].gold_score), gold_before)
        self.assertEqual(int(players[0].map_score), map_before)
        # Slot 0 refilled directly from the deck (pop from end -> "E"); no cascade.
        self.assertEqual(game.noble_slots[0].name, "E")
        self.assertEqual(game.noble_slots[1].name, "B")
        self.assertEqual(game.noble_slots[2].name, "C")
        self.assertIsNone(game.pending_required_choice)


class GarganCitizensChainTests(unittest.TestCase):
    def test_chain_grants_three_citizens_via_three_picks(self):
        game, players = make_game(n_board_citizens=5)

        game.payouts.execute_special_payout(
            "choose <citizens 3> <noble>", players[0].player_id, auto_apply_single_choice=True
        )
        # Pick the "3 Citizens" leg.
        game.act_on_required_action(players[0].player_id, "choose 1")

        # That opens the first of three citizen picks; resolve each in turn.
        for _ in range(3):
            prc = game.pending_required_choice
            self.assertIsNotNone(prc, "expected a citizen pick prompt")
            self.assertTrue(all(o.get("token") == "citizens.choice" for o in prc.get("options") or []))
            game.act_on_required_action(players[0].player_id, "choose 1")

        self.assertEqual(len(players[0].owned_citizens), 3)
        self.assertIsNone(game.pending_required_choice)
        self.assertEqual(game.action_required.get("action"), "")

    def test_chain_stops_when_board_runs_out(self):
        # Only 2 board citizens for a 3-citizen chain: the player gains both,
        # then the chain ends with nothing left to pick.
        game, players = make_game(n_board_citizens=2, noble_slots=[None, None, None])

        game.payouts.execute_special_payout(
            "choose <citizens 3> <noble>", players[0].player_id, auto_apply_single_choice=True
        )
        # Sole chain leg auto-applied; first citizen pick is open (2 options).
        game.act_on_required_action(players[0].player_id, "choose 1")
        # Second pick now has a single option -> auto-applied, so no prompt left.
        self.assertEqual(len(players[0].owned_citizens), 2)
        self.assertIsNone(game.pending_required_choice)


class GarganDatabaseTests(unittest.TestCase):
    def test_live_db_monster_has_reward_string(self):
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
            cur.execute("SELECT * FROM monsters WHERE id_monsters = 147")
            row = cur.fetchone()
        finally:
            conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(int(row.get("has_special_reward")), 1)
        self.assertEqual(row.get("special_reward"), "choose <citizens 3> <noble>")
        self.assertEqual(row.get("special_reward_text"), "Gain 3 Citizens or 1 Noble.")


if __name__ == "__main__":
    unittest.main()
