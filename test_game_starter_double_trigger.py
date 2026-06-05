import unittest

from cards import Citizen, Starter
from game import Game
from game_models import Player


def make_herald(starter_id, gold_on=1, gold_off=1):
    """A -1/-1 starter that fires on both `doubles` and `no_payout`.

    Mirrors the real Herald/Margrave: roll_match1/2 = -1 (never roll-matches)
    and activation_trigger = 'doubles_or_no_payout'. A flat gold payout keeps
    the harvest non-interactive (no special-payout prompt) so the test can
    drive straight to the end-of-harvest bonus gate.
    """
    return Starter(
        starter_id, "Herald", -1, -1,
        gold_on, gold_off,
        0, 0, 0, 0,
        False, False, "", "",
        "test",
        "doubles_or_no_payout",
    )


def make_sum_match_citizen(citizen_id, roll_sum):
    """Citizen that fires when die_sum == roll_sum, paying 1 gold."""
    return Citizen(
        citizen_id, f"Citizen {citizen_id}",
        2,
        roll_sum, 0,
        0, 0, 0, 0,
        1, 1,
        0, 0, 0, 0, 0, 0,
        False, False, "", "",
        False, "test",
    )


def make_doubles_harvest_game(player_specs, die=3):
    """Build a 2+ player game sitting in harvest with a doubles roll.

    `player_specs` is a list of dicts: {"herald": bool, "citizen_sum": int|None}.
    """
    players = []
    for i, spec in enumerate(player_specs):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = 0
        p.strength_score = 0
        p.magic_score = 0
        p.victory_score = 0
        if spec.get("herald"):
            p.owned_starters.append(make_herald(10 + i))
        cs = spec.get("citizen_sum")
        if cs is not None:
            p.owned_citizens.append(make_sum_match_citizen(100 + i, cs))
        players.append(p)
    game = Game({
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": die,
        "die_two": die,
        "die_sum": die * 2,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "harvest",
    })
    return game, players


class HeraldDoubleTriggerTests(unittest.TestCase):
    def test_doubles_only_still_gets_no_payout_bonus(self):
        # Doubles roll, no citizens with dice values: the Herald's doubles leg
        # fires in-band and must NOT suppress its own no_payout leg.
        game, players = make_doubles_harvest_game(
            [{"herald": True}, {"herald": True}],
            die=3,
        )

        game.advance_tick()

        # Each Herald fired TWICE: once for the in-band doubles leg and once for
        # the end-of-harvest no_payout leg (flat gold 1 each = 2 total). Before
        # the fix the doubles activation suppressed the no_payout leg, so the
        # Herald only paid out once.
        self.assertEqual(players[0].gold_score, 2, "Herald doubles + no_payout both fired")
        self.assertEqual(players[1].gold_score, 2, "Herald doubles + no_payout both fired")

        ca = game.concurrent_action or {}
        self.assertEqual(ca.get("kind"), "harvest_choices")
        self.assertEqual((ca.get("data") or {}).get("phase"), "finalize_bonus")

        pending = set(ca.get("pending") or [])
        self.assertIn(players[0].player_id, pending,
                      "Doubles-only player must still get the no_payout bonus")
        self.assertIn(players[1].player_id, pending,
                      "Doubles-only player must still get the no_payout bonus")

    def test_other_card_activation_suppresses_no_payout(self):
        # Same doubles roll, but player 1 also owns a citizen that fires on the
        # roll's sum. That real activation must suppress player 1's no_payout,
        # while player 2 (Herald-only) still receives it.
        game, players = make_doubles_harvest_game(
            [{"herald": True, "citizen_sum": 6}, {"herald": True}],
            die=3,
        )

        game.advance_tick()

        ca = game.concurrent_action or {}
        self.assertEqual(ca.get("kind"), "harvest_choices")
        self.assertEqual((ca.get("data") or {}).get("phase"), "finalize_bonus")

        pending = set(ca.get("pending") or [])
        self.assertNotIn(players[0].player_id, pending,
                         "A citizen activation must suppress that player's no_payout")
        self.assertIn(players[1].player_id, pending,
                      "Herald-only player still gets the no_payout bonus")


if __name__ == "__main__":
    unittest.main()
