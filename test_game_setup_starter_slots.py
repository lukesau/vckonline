"""Tests for third starter slot selection in game setup."""

import contextlib
import importlib.util
import io
import random
import socket
import unittest

from cards import Starter
from game_models import LobbyMember
from game_setup import (
    DEFAULT_SLOT_STARTER_ID,
    _choose_slot_starter,
    _is_slot_starter,
    _is_slot_starter_row,
    load_game_data,
)


def _db_ready():
    if importlib.util.find_spec("mariadb") is None:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        return sock.connect_ex(("127.0.0.1", 3306)) == 0
    finally:
        sock.close()


def _make_starter(starter_id, name, rm1, rm2, expansion="base", activation_trigger=""):
    return Starter(
        starter_id, name, rm1, rm2,
        0, 0, 0, 0, 0, 0,
        False, False, "", "",
        expansion, activation_trigger,
    )


class StarterSlotPredicateTests(unittest.TestCase):
    def test_slot_row_predicate(self):
        self.assertTrue(_is_slot_starter_row({"roll_match1": -1, "roll_match2": -1}))
        self.assertFalse(_is_slot_starter_row({"roll_match1": 5, "roll_match2": -1}))
        self.assertFalse(_is_slot_starter_row({"roll_match1": 6, "roll_match2": 0}))

    def test_slot_card_predicate(self):
        herald = _make_starter(3, "Herald", -1, -1, activation_trigger="doubles_or_no_payout")
        peasant = _make_starter(1, "Peasant", 5, -1)
        self.assertTrue(_is_slot_starter(herald))
        self.assertFalse(_is_slot_starter(peasant))


class ChooseSlotStarterTests(unittest.TestCase):
    def setUp(self):
        self.herald = _make_starter(3, "Herald", -1, -1, activation_trigger="doubles_or_no_payout")
        self.margrave = _make_starter(4, "Margrave", -1, -1, expansion="margraves",
                                      activation_trigger="doubles_or_no_payout")
        self.pool = [self.herald, self.margrave]

    def test_named_preset_defaults_to_herald(self):
        chosen = _choose_slot_starter(self.pool, "base")
        self.assertEqual(chosen.starter_id, DEFAULT_SLOT_STARTER_ID)

    def test_draft_selection_overrides_default(self):
        chosen = _choose_slot_starter(self.pool, "draft", {"starter_id": 4})
        self.assertEqual(chosen.name, "Margrave")

    def test_random_picks_from_pool(self):
        random.seed(0)
        ids = {_choose_slot_starter(self.pool, "random").starter_id for _ in range(20)}
        self.assertTrue(ids.issubset({3, 4}))
        self.assertGreater(len(ids), 1)


def _slot_starter_ids(player):
    return [
        int(s.starter_id)
        for s in player.owned_starters
        if _is_slot_starter(s)
    ]


@unittest.skipUnless(
    _db_ready(),
    "requires active DB tunnel and mariadb module; run source ./activate_with_env.sh first",
)
class StarterSlotIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.players = [
            LobbyMember("Player 1", "p1"),
            LobbyMember("Player 2", "p2"),
        ]

    def _load(self, preset, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_game_data(f"starter-slot-{preset}", preset, self.players, **kwargs)

    def test_named_preset_grants_three_starters_with_herald_only(self):
        state = self._load("base")
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_starters), 3)
            names = {s.name for s in player.owned_starters}
            self.assertIn("Peasant", names)
            self.assertIn("Knight", names)
            self.assertIn("Herald", names)
            self.assertNotIn("Margrave", names)
            self.assertEqual(_slot_starter_ids(player), [DEFAULT_SLOT_STARTER_ID])

    def test_draft_selection_grants_margrave_slot(self):
        from game_setup import load_draft_card_pool

        monsters_by_area, citizens_by_roll, _starter_rows = load_draft_card_pool(2)
        areas = list(monsters_by_area.keys())[:5]
        self.assertEqual(len(areas), 5)
        citizen_picks = {}
        for roll in (1, 2, 3, 4, 5, 6, 7, 8, 9, 11):
            pool = citizens_by_roll.get(roll) or []
            self.assertTrue(pool, f"missing citizens for roll {roll}")
            citizen_picks[roll] = int(pool[0]["id_citizens"])

        state = self._load(
            "draft",
            draft_selections={
                "monster_areas": areas,
                "citizens": citizen_picks,
                "starter_id": 4,
            },
        )
        for player in state["player_list"]:
            self.assertEqual(_slot_starter_ids(player), [4])
            self.assertEqual(
                [s.name for s in player.owned_starters if _is_slot_starter(s)],
                ["Margrave"],
            )

    def test_random_preset_grants_at_most_one_slot_starter(self):
        from game_setup import load_draft_card_pool

        # The random preset can grant any -1/-1 slot starter that passes
        # keep_for_random (implemented + has art), so derive the allowed id set
        # from the live DB instead of hard-coding it — new expansion slot
        # starters (e.g. Coxswain) shouldn't break this test.
        _m, _c, starter_rows = load_draft_card_pool(2)
        allowed_slot_ids = {int(r["id_starters"]) for r in starter_rows}
        self.assertTrue(allowed_slot_ids, "expected at least one keep_for_random slot starter")

        random.seed(42)
        state = self._load("random")
        for player in state["player_list"]:
            slot_ids = _slot_starter_ids(player)
            self.assertEqual(len(slot_ids), 1)
            self.assertIn(slot_ids[0], allowed_slot_ids)


if __name__ == "__main__":
    unittest.main()
