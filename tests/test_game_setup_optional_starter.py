"""Tests for optional (-1/-1 doubles-or-no-payout) starter selection in setup.

Every player always gets the mandatory "core" starters (Peasant/Knight). At
most one "optional" -1/-1 starter (Herald/Margrave/Coxswain) is granted, chosen
by the preset's configured expansion; if none matches, the game plays without a
doubles/no-payout trigger.
"""

import contextlib
import importlib.util
import io
import random
import socket
import unittest

from cards import Starter
from game_models import LobbyMember
from game_setup import (
    _choose_optional_starter,
    _is_optional_starter,
    _is_optional_starter_row,
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


class OptionalStarterPredicateTests(unittest.TestCase):
    def test_optional_row_predicate(self):
        self.assertTrue(_is_optional_starter_row({"roll_match1": -1, "roll_match2": -1}))
        self.assertFalse(_is_optional_starter_row({"roll_match1": 5, "roll_match2": -1}))
        self.assertFalse(_is_optional_starter_row({"roll_match1": 6, "roll_match2": 0}))

    def test_optional_card_predicate(self):
        herald = _make_starter(3, "Herald", -1, -1, activation_trigger="doubles_or_no_payout")
        peasant = _make_starter(1, "Peasant", 5, -1)
        self.assertTrue(_is_optional_starter(herald))
        self.assertFalse(_is_optional_starter(peasant))


class ChooseOptionalStarterTests(unittest.TestCase):
    def setUp(self):
        self.herald = _make_starter(3, "Herald", -1, -1, expansion="base",
                                    activation_trigger="doubles_or_no_payout")
        self.margrave = _make_starter(4, "Margrave", -1, -1, expansion="margraves",
                                      activation_trigger="doubles_or_no_payout")
        self.pool = [self.herald, self.margrave]

    def test_expansion_selects_matching_starter(self):
        self.assertEqual(_choose_optional_starter(self.pool, "base", "base").name, "Herald")
        self.assertEqual(_choose_optional_starter(self.pool, "june2026", "margraves").name, "Margrave")

    def test_no_matching_expansion_returns_none(self):
        # An expansion with no -1/-1 starter in the pool yields no optional
        # starter (Herald is NOT a fallback).
        self.assertIsNone(_choose_optional_starter(self.pool, "shadowvale", "shadowvale"))

    def test_empty_pool_returns_none(self):
        self.assertIsNone(_choose_optional_starter([], "base", "base"))

    def test_none_expansion_returns_none(self):
        self.assertIsNone(_choose_optional_starter(self.pool, "base", None))

    def test_draft_selection_picks_by_id(self):
        chosen = _choose_optional_starter(self.pool, "draft", None, {"starter_id": 4})
        self.assertEqual(chosen.name, "Margrave")

    def test_draft_without_selection_returns_none(self):
        self.assertIsNone(_choose_optional_starter(self.pool, "draft", None, {}))

    def test_random_picks_from_pool(self):
        random.seed(0)
        ids = {_choose_optional_starter(self.pool, "random", None).starter_id for _ in range(20)}
        self.assertTrue(ids.issubset({3, 4}))
        self.assertGreater(len(ids), 1)


def _optional_starter_ids(player):
    return [
        int(s.starter_id)
        for s in player.owned_starters
        if _is_optional_starter(s)
    ]


@unittest.skipUnless(
    _db_ready(),
    "requires active DB tunnel and mariadb module; run source ./activate_with_env.sh first",
)
class OptionalStarterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.players = [
            LobbyMember("Player 1", "p1"),
            LobbyMember("Player 2", "p2"),
        ]

    def _load(self, preset, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_game_data(f"optional-starter-{preset}", preset, self.players, **kwargs)

    def test_base_preset_grants_core_plus_herald(self):
        state = self._load("base")
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_starters), 3)
            names = {s.name for s in player.owned_starters}
            self.assertIn("Peasant", names)
            self.assertIn("Knight", names)
            self.assertIn("Herald", names)
            self.assertNotIn("Margrave", names)

    def test_june2026_preset_grants_margrave_optional(self):
        state = self._load("june2026")
        for player in state["player_list"]:
            names = {s.name for s in player.owned_starters}
            self.assertIn("Peasant", names)
            self.assertIn("Knight", names)
            self.assertIn("Margrave", names)
            self.assertNotIn("Herald", names)

    def test_draft_selection_grants_margrave_optional(self):
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
            self.assertEqual(_optional_starter_ids(player), [4])
            self.assertEqual(
                [s.name for s in player.owned_starters if _is_optional_starter(s)],
                ["Margrave"],
            )

    def test_random_preset_grants_at_most_one_optional_starter(self):
        from game_setup import load_draft_card_pool

        # The random preset can grant any -1/-1 starter that passes
        # keep_for_random (implemented + has art), so derive the allowed id set
        # from the live DB instead of hard-coding it — new expansion optional
        # starters (e.g. Coxswain) shouldn't break this test.
        _m, _c, starter_rows = load_draft_card_pool(2)
        allowed_ids = {int(r["id_starters"]) for r in starter_rows}
        self.assertTrue(allowed_ids, "expected at least one keep_for_random optional starter")

        random.seed(42)
        state = self._load("random")
        for player in state["player_list"]:
            optional_ids = _optional_starter_ids(player)
            self.assertEqual(len(optional_ids), 1)
            self.assertIn(optional_ids[0], allowed_ids)


if __name__ == "__main__":
    unittest.main()
