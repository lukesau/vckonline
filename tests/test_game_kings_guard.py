"""Tests for the Recruit the King's Guard event (event 10, expansion kingsguard).

This is the only event that introduces a brand-new citizen stack. On reveal it
drops the set-aside King's Guard citizens on top of the event card so they can be
hired like any other board stack. When the event un-exhausts, the un-hired guards
return to the reserve; re-revealing restores exactly that many. Hiring the whole
stack leaves the event in place with nothing to hire (no "double exhaust").
"""

import unittest

from cards import Citizen, Event, Exhausted
from game import Game
from game_models import Player


KINGS_GUARD_ACTIVATION = "place_kings_guard"


def make_kings_guard_event(event_id=10):
    return Event(
        event_id, "Recruit the King's Guard",
        -1,                      # roll_match1
        None,                    # roll_effect
        0,                       # has_roll_effect
        0,                       # is_monster
        1,                       # has_activation_effect
        0,                       # has_passive_effect
        KINGS_GUARD_ACTIVATION,  # activation_effect
        None,                    # passive_effect
        0, 0,                    # strength/magic cost
        None,                    # monster_type
        0, 0, 0, 0,              # vp/gold/strength/magic reward
        0, None,                 # has_special_reward, special_reward
        "kingsguard",
    )


def make_kings_guard_citizen(citizen_id=49):
    return Citizen(
        citizen_id, "King's Guard",
        3,                       # gold_cost
        7, 8,                    # roll_match1, roll_match2
        0, 0, 1, 0,              # shadow/holy/soldier/worker
        0, 0,                    # gold payout on/off
        2, 2,                    # strength payout on/off
        0, 0,                    # magic payout on/off
        0, 0,                    # vp payout on/off
        0, 0, None, None,        # special payout flags/strings
        1,                       # special_citizen
        "kingsguard",
    )


def make_game(n_players=2, *, phase="action", gold=100):
    players = []
    for i in range(n_players):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = gold
        p.strength_score = gold
        p.magic_score = gold
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
        "turn_index": 0,
        "phase": phase,
        "actions_remaining": 2,
    })
    return game, players


def reveal_kings_guard(game, stack, n_guards=5):
    """Arm the reserve, drop the event onto `stack`, and reveal it."""
    game.kings_guard_pool = [make_kings_guard_citizen() for _ in range(n_guards)]
    ev = make_kings_guard_event()
    game.exhausted_stack.append(ev)
    game.events.reveal_exhausted_onto_stack(stack)
    return ev


def hire_top_guard(game, player, stack, owned_same_name):
    """Hire the accessible top citizen of `stack`, paying its name-scaled cost."""
    top = stack[-1]
    cost = int(top.gold_cost) + int(owned_same_name)
    game.hire_citizen(player.player_id, top.citizen_id, gp=cost)


class KingsGuardPlacementTests(unittest.TestCase):
    def test_reveal_places_guards_on_top_of_event(self):
        game, players = make_game(2)
        stack = game.citizen_grid[6]   # roll-7 stack, but placement is event-driven
        ev = reveal_kings_guard(game, stack, n_guards=5)

        self.assertIs(stack[0], ev)
        self.assertEqual(len(stack), 6)               # event + 5 guards
        self.assertEqual(game.kings_guard_pool, [])   # all moved onto the board
        self.assertFalse(ev.is_accessible)            # event is a spent placeholder
        self.assertTrue(stack[-1].is_accessible)      # only the top guard is hireable
        self.assertTrue(all(g.is_visible for g in stack[1:]))
        self.assertFalse(any(g.is_accessible for g in stack[1:-1]))

    def test_empty_reserve_places_nothing(self):
        game, players = make_game(2)
        stack = game.citizen_grid[0]
        game.kings_guard_pool = []
        ev = make_kings_guard_event()
        game.exhausted_stack.append(ev)
        game.events.reveal_exhausted_onto_stack(stack)
        self.assertEqual(stack, [ev])
        self.assertFalse(ev.is_accessible)


class KingsGuardHireTests(unittest.TestCase):
    def test_hire_walks_down_the_stack_then_event_remains(self):
        game, players = make_game(2)
        stack = game.citizen_grid[6]
        ev = reveal_kings_guard(game, stack, n_guards=5)
        # Sentinel in the deck proves no fresh exhausted card is flipped.
        sentinel = Exhausted(999)
        game.exhausted_stack.append(sentinel)

        for i in range(5):
            hire_top_guard(game, players[0], stack, owned_same_name=i)
            if i < 4:
                self.assertTrue(stack[-1].is_accessible)

        owned = [c for c in players[0].owned_citizens if c.name == "King's Guard"]
        self.assertEqual(len(owned), 5)
        self.assertEqual(stack, [ev])                 # only the event is left
        self.assertFalse(ev.is_accessible)            # no double-exhaust
        self.assertEqual(game.exhausted_stack, [sentinel])  # nothing re-revealed

    def test_hire_works_when_event_is_on_a_non_citizen_grid(self):
        game, players = make_game(2)
        stack = game.domain_grid[0]   # event un-exhausted onto a domain slot
        reveal_kings_guard(game, stack, n_guards=3)

        hire_top_guard(game, players[0], stack, owned_same_name=0)
        owned = [c for c in players[0].owned_citizens if c.name == "King's Guard"]
        self.assertEqual(len(owned), 1)
        self.assertEqual(len(stack), 3)               # event + 2 remaining guards
        self.assertTrue(stack[-1].is_accessible)

    def test_hiring_entire_stack_does_not_restore_on_rereveal(self):
        game, players = make_game(2)
        stack = game.citizen_grid[6]
        ev = reveal_kings_guard(game, stack, n_guards=5)
        for i in range(5):
            hire_top_guard(game, players[0], stack, owned_same_name=i)
        self.assertEqual(stack, [ev])

        # Un-exhaust: nothing un-hired to retract, so the event recycles alone.
        popped = game.domain_effects._unexhaust_stack_top_if_present(stack)
        self.assertTrue(popped)
        self.assertEqual(game.kings_guard_pool, [])
        # Re-reveal places zero guards.
        stack2 = game.citizen_grid[5]
        game.events.reveal_exhausted_onto_stack(stack2)
        self.assertEqual(len(stack2), 1)
        self.assertFalse(stack2[-1].is_accessible)


class KingsGuardUnexhaustTests(unittest.TestCase):
    def test_unexhaust_retracts_unhired_guards_and_keeps_hired(self):
        game, players = make_game(2)
        stack = game.citizen_grid[6]
        ev = reveal_kings_guard(game, stack, n_guards=5)
        # Hire 2; 3 guards remain on the board.
        hire_top_guard(game, players[0], stack, owned_same_name=0)
        hire_top_guard(game, players[0], stack, owned_same_name=1)
        self.assertEqual(len(stack), 4)               # event + 3

        popped = game.domain_effects._unexhaust_stack_top_if_present(stack)
        self.assertTrue(popped)
        self.assertEqual(stack, [])                   # event recycled too
        self.assertIn(ev, game.exhausted_stack)
        self.assertEqual(len(game.kings_guard_pool), 3)
        self.assertTrue(all(not g.is_visible for g in game.kings_guard_pool))
        # The 2 hired guards stay in the tableau.
        owned = [c for c in players[0].owned_citizens if c.name == "King's Guard"]
        self.assertEqual(len(owned), 2)

    def test_rereveal_restores_exactly_the_retracted_count(self):
        game, players = make_game(2)
        stack = game.citizen_grid[6]
        reveal_kings_guard(game, stack, n_guards=5)
        hire_top_guard(game, players[0], stack, owned_same_name=0)
        hire_top_guard(game, players[0], stack, owned_same_name=1)
        game.domain_effects._unexhaust_stack_top_if_present(stack)
        self.assertEqual(len(game.kings_guard_pool), 3)

        # Re-reveal onto a different slot restores exactly 3 guards.
        stack2 = game.citizen_grid[0]
        game.events.reveal_exhausted_onto_stack(stack2)
        guards_on_board = [c for c in stack2 if isinstance(c, Citizen)]
        self.assertEqual(len(guards_on_board), 3)
        self.assertEqual(game.kings_guard_pool, [])
        self.assertTrue(stack2[-1].is_accessible)

    def test_return_owned_card_to_kings_guard_slot_unexhausts(self):
        # A citizen returned to the King's Guard slot (roll 7) should pull the
        # guards back and recycle the event before the returned card lands.
        game, players = make_game(2)
        stack = game.citizen_grid[6]
        reveal_kings_guard(game, stack, n_guards=5)
        returning = make_kings_guard_citizen(citizen_id=49)
        returning.name = "Knight"          # a normal roll-7 citizen being returned
        returning.expansion = "base"
        returning.special_citizen = 0
        ok = game.domain_effects._return_citizen_to_stack(returning)
        self.assertTrue(ok)
        self.assertIs(stack[-1], returning)
        # All 5 un-hired guards went back to the reserve.
        self.assertEqual(len(game.kings_guard_pool), 5)


class KingsGuardSerializationTests(unittest.TestCase):
    def test_pool_round_trips(self):
        from game_serialization import serialize_game_to_save_dict, deserialize_save_dict_to_game

        game, players = make_game(2)
        game.kings_guard_pool = [make_kings_guard_citizen() for _ in range(4)]
        blob = serialize_game_to_save_dict(game)
        restored = deserialize_save_dict_to_game(blob)
        self.assertEqual(len(restored.kings_guard_pool), 4)
        self.assertTrue(all(isinstance(c, Citizen) for c in restored.kings_guard_pool))
        self.assertTrue(all(c.name == "King's Guard" for c in restored.kings_guard_pool))


class KingsGuardDbTests(unittest.TestCase):
    """The DB must hold exactly one King's Guard citizen (expansion + flag)."""

    def test_exactly_one_kings_guard_citizen(self):
        try:
            import mariadb
            conn = mariadb.connect(
                user="vckonline", password="vckonline",
                host="127.0.0.1", port=3306, database="vckonline",
            )
        except Exception as e:
            self.skipTest(f"DB unavailable: {e}")
        try:
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT * FROM citizens WHERE expansion = %s AND special_citizen = 1",
                ("kingsguard",),
            )
            rows = cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "King's Guard")
            cur.execute("SELECT activation_effect FROM events WHERE id_events = 10")
            self.assertEqual(cur.fetchone()["activation_effect"], "place_kings_guard")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
