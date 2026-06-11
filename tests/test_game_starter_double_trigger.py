import unittest

from cards import Citizen, Starter
from game import Game
from game_models import Player


def make_herald(starter_id, gold_on=1, gold_off=1):
    """A -1/-1 starter that fires on both `doubles` and `no_payout`.

    Mirrors the real Herald: roll_match1/2 = -1 (never roll-matches) and
    activation_trigger = 'doubles_or_no_payout_twice'. The `twice` marker is
    what makes the doubles + no_payout legs stack into two activations on a
    doubles roll that activates no other card — Herald is the only starter
    that does this. A flat gold payout keeps the harvest non-interactive (no
    special-payout prompt) so the test can drive straight to the
    end-of-harvest bonus gate.
    """
    return Starter(
        starter_id, "Herald", -1, -1,
        gold_on, gold_off,
        0, 0, 0, 0,
        False, False, "", "",
        "test",
        "doubles_or_no_payout_twice",
    )


def make_margrave(starter_id):
    """A -1/-1 no-payout starter with Margrave's printed payout shape."""
    return Starter(
        starter_id, "Margrave", -1, -1,
        1, 0,
        1, 0,
        1, 0,
        False, True, "", "exchange wild 1 v 1",
        "test",
        "doubles_or_no_payout",
    )


def make_coxswain(starter_id, gold_on=1, gold_off=1):
    """A -1/-1 starter with the default `doubles_or_no_payout` trigger.

    Mirrors the real Coxswain: it has both a `doubles` leg and a `no_payout`
    leg, but activates AT MOST ONCE per harvest even when both conditions are
    met. That single-activation behavior is now the default for every -1/-1
    starter (the in-band doubles activation suppresses the end-of-harvest
    no_payout leg), so Coxswain needs no special marker — only the Herald
    overrides it with `twice`. A flat gold payout keeps the harvest
    non-interactive.
    """
    return Starter(
        starter_id, "Coxswain", -1, -1,
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
        if spec.get("coxswain"):
            p.owned_starters.append(make_coxswain(20 + i))
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

        self.assertIsNone(game.concurrent_action)

    def test_other_card_activation_suppresses_no_payout(self):
        # Same doubles roll, but player 1 also owns a citizen that fires on the
        # roll's sum. That real activation must suppress player 1's no_payout,
        # while player 2 (Herald-only) still receives it.
        game, players = make_doubles_harvest_game(
            [{"herald": True, "citizen_sum": 6}, {"herald": True}],
            die=3,
        )

        game.advance_tick()

        self.assertEqual(players[0].gold_score, 2,
                         "A citizen activation must suppress that player's no_payout")
        self.assertEqual(players[1].gold_score, 2,
                         "Herald-only player still gets the no_payout bonus")
        self.assertIsNone(game.concurrent_action)

    def test_margrave_on_turn_no_payout_does_not_fall_back_to_wild_bonus(self):
        game, players = make_doubles_harvest_game(
            [{"herald": False}, {"herald": False}],
            die=2,
        )
        players[0].owned_starters.append(make_margrave(4))

        game.harvest._activate_finalize_bonus_for(players[0].player_id)

        self.assertEqual(players[0].gold_score, 1)
        self.assertEqual(players[0].strength_score, 1)
        self.assertEqual(players[0].magic_score, 1)
        self.assertEqual(game.action_required.get("action"), "")

    def test_margrave_off_turn_unaffordable_exchange_does_not_fall_back_to_wild_bonus(self):
        game, players = make_doubles_harvest_game(
            [{"herald": False}, {"herald": False}],
            die=2,
        )
        players[1].owned_starters.append(make_margrave(4))

        game.harvest._activate_finalize_bonus_for(players[1].player_id)

        self.assertEqual(players[1].gold_score, 0)
        self.assertEqual(players[1].strength_score, 0)
        self.assertEqual(players[1].magic_score, 0)
        self.assertEqual(players[1].victory_score, 0)
        self.assertEqual(game.action_required.get("action"), "")


class MargraveOnceOnlyTests(unittest.TestCase):
    """Margrave (default `doubles_or_no_payout`) fires at most once per harvest."""

    def test_doubles_no_citizens_fires_once(self):
        # Doubles roll, no dice-value citizens: the Margrave's in-band doubles
        # leg fires and MUST suppress its own no_payout leg, so the active
        # player's on-turn payout (1g/1s/1m) lands exactly once. Before the
        # default flipped to single, the Margrave fired twice like the Herald.
        game, players = make_doubles_harvest_game(
            [{"herald": False}, {"herald": False}],
            die=2,
        )
        players[0].owned_starters.append(make_margrave(4))

        game.advance_tick()

        self.assertEqual(players[0].gold_score, 1, "Margrave fires once on doubles+no_payout")
        self.assertEqual(players[0].strength_score, 1, "Margrave fires once on doubles+no_payout")
        self.assertEqual(players[0].magic_score, 1, "Margrave fires once on doubles+no_payout")
        self.assertIsNone(game.concurrent_action)


class CoxswainOnceOnlyTests(unittest.TestCase):
    """Coxswain (default `doubles_or_no_payout`) fires at most once per harvest."""

    def test_doubles_no_citizens_fires_once(self):
        # Doubles roll, no dice-value citizens: the Coxswain's in-band doubles
        # leg fires and MUST suppress its own no_payout leg, so it pays out
        # exactly once (flat gold 1), unlike the Herald which pays twice.
        game, players = make_doubles_harvest_game(
            [{"coxswain": True}, {"coxswain": True}],
            die=3,
        )

        game.advance_tick()

        self.assertEqual(players[0].gold_score, 1, "Coxswain fires once on doubles+no_payout")
        self.assertEqual(players[1].gold_score, 1, "Coxswain fires once on doubles+no_payout")
        self.assertIsNone(game.concurrent_action)

    def test_no_doubles_no_citizens_fires_once_via_no_payout(self):
        # No doubles and no citizens fired: only the end-of-harvest no_payout
        # leg fires, paying out once.
        game, players = make_doubles_harvest_game(
            [{"coxswain": True}, {"coxswain": True}],
            die=2,
        )
        game.die_two = 5
        game.die_sum = game.die_one + game.die_two

        game.advance_tick()

        self.assertEqual(players[0].gold_score, 1, "Coxswain no_payout leg fires once")
        self.assertEqual(players[1].gold_score, 1, "Coxswain no_payout leg fires once")
        self.assertIsNone(game.concurrent_action)

    def test_doubles_with_citizen_activation_fires_once(self):
        # Doubles roll where a citizen also fires: the citizen activation plus
        # the Coxswain's own doubles leg both suppress its no_payout leg, so the
        # Coxswain still contributes exactly one activation.
        game, players = make_doubles_harvest_game(
            [{"coxswain": True, "citizen_sum": 6}, {"coxswain": True}],
            die=3,
        )

        game.advance_tick()

        self.assertEqual(players[0].gold_score, 2,
                         "Coxswain doubles leg (1) + citizen (1), no second no_payout fire")
        self.assertEqual(players[1].gold_score, 1,
                         "Coxswain-only player fires once on doubles")
        self.assertIsNone(game.concurrent_action)


if __name__ == "__main__":
    unittest.main()
