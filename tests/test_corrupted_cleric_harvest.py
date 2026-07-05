"""Corrupted Cleric (event 1) + concurrent harvest decisions.

While Corrupted Cleric is in play, rolling a 1 opens event_slay_cost_choice
(add_slay_cost m 1) before harvest automation. That must complete before the
harvest_choices gate opens. A stale harvest_choices concurrent_action left
over from a prior harvest (pending empty, completed populated) must not cause
the next harvest to skip payouts.
"""

import unittest

from cards import Event, Monster
from game import Game
from game_models import Player
from tests.test_concurrent_harvest import make_exchange_citizen, make_game_for_test


def make_corrupted_cleric():
    ev = Event(
        1, "Corrupted Cleric",
        1, "add_slay_cost m 1", 1, 1,
        0, 0, None, None,
        0, 0, None,
        0, 0, 0, 0, 0, None,
        "base",
    )
    ev.toggle_visibility(True)
    ev.toggle_accessibility(True)
    return ev


def make_board_monster(monster_id=99):
    m = Monster(
        monster_id, "Target Orc", "Forest", "Minion", 1,
        2, 2, 1, 0, 0, 0, False, None, False, None, False, "base",
    )
    m.toggle_visibility(True)
    m.toggle_accessibility(True)
    return m


class CorruptedClericHarvestTests(unittest.TestCase):
    def test_cleric_then_concurrent_harvest_two_turns(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        for p in (p1, p2):
            p.gold_score = 10
            p.strength_score = 10
            p.magic_score = 10
            p.owned_citizens.append(make_exchange_citizen(100, "exchange g 1 s 1"))

        game = make_game_for_test([p1, p2])
        game.monster_grid = [[make_board_monster()], [make_corrupted_cleric()], [], [], []]

        for turn, (active, die1, die2) in enumerate(
            [("p1", 1, 2), ("p2", 1, 3)], start=1
        ):
            game.phase = "roll_pending"
            game.pending_roll = {
                "rolled_die_one": die1,
                "rolled_die_two": die2,
                "rolled_die_sum": die1 + die2,
            }
            game.action_required = {"id": active, "action": "finalize_roll"}
            game.finalize_roll(active)

            self.assertEqual(
                game.action_required.get("action"),
                "event_slay_cost_choice",
                f"turn {turn}: Corrupted Cleric should open slay-cost prompt",
            )

            while game.phase == "harvest" and game.advance_tick():
                pass

            game.apply_event_slay_cost(active, monster_id=99)
            while game.advance_tick():
                pass

            ca = game.concurrent_action
            self.assertIsNotNone(ca, f"turn {turn}: harvest choices gate expected")
            self.assertEqual(ca.get("kind"), "harvest_choices")

            for pid in list(ca.get("pending") or []):
                plist = ((ca.get("data") or {}).get("prompts") or {}).get(pid) or []
                self.assertTrue(plist, f"turn {turn}: expected prompts for {pid}")
                prompt_id = plist[0]["id"]
                game.submit_concurrent_action(
                    pid,
                    f"{prompt_id}|confirm_harvest_exchange",
                    kind="harvest_choices",
                )

            while game.phase == "harvest" and game.advance_tick():
                pass

            self.assertEqual(game.phase, "action", f"turn {turn}: should reach action phase")
            self.assertIsNone(game.concurrent_action, f"turn {turn}: gate should clear")

            game.actions_remaining = 0
            game.advance_tick()
            while game.phase != "roll_pending":
                game.advance_tick()

    def test_stale_completed_gate_does_not_skip_next_harvest(self):
        p1 = Player("p1", "Player 1")
        p1.gold_score = 10
        p1.strength_score = 10
        p1.magic_score = 10
        p1.owned_citizens.append(make_exchange_citizen(100, "exchange g 1 s 1"))

        game = make_game_for_test([p1])
        game.monster_grid = [[make_board_monster()], [make_corrupted_cleric()], [], [], []]

        game.concurrent_action = {
            "kind": "harvest_choices",
            "pending": [],
            "completed": ["p1"],
            "responses": {},
            "data": {"phase": "scan", "prompts": {}, "prompt_seq": 1},
        }

        game.phase = "roll_pending"
        game.pending_roll = {"rolled_die_one": 1, "rolled_die_two": 2, "rolled_die_sum": 3}
        game.action_required = {"id": "p1", "action": "finalize_roll"}
        game.finalize_roll("p1")

        while game.phase == "harvest" and game.advance_tick():
            pass

        game.apply_event_slay_cost("p1", monster_id=99)
        while game.advance_tick():
            pass

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertIn("p1", ca.get("pending") or [])

        plist = ((ca.get("data") or {}).get("prompts") or {}).get("p1") or []
        self.assertTrue(plist)
        game.submit_concurrent_action(
            "p1", f"{plist[0]['id']}|confirm_harvest_exchange", kind="harvest_choices"
        )

        while game.phase == "harvest" and game.advance_tick():
            pass

        self.assertEqual(p1.strength_score, 11, "exchange payout should have fired (+1s)")
        self.assertEqual(p1.gold_score, 10, "exchange cost should have been paid (-1g after +1g printed payout)")

    def test_harvest_submit_rejected_while_cleric_pending(self):
        p1 = Player("p1", "Player 1")
        p1.gold_score = 10
        p1.owned_citizens.append(make_exchange_citizen(100, "exchange g 1 s 1"))

        game = make_game_for_test([p1])
        game.monster_grid = [[make_board_monster()], [make_corrupted_cleric()], [], [], []]
        game.phase = "roll_pending"
        game.pending_roll = {"rolled_die_one": 1, "rolled_die_two": 2, "rolled_die_sum": 3}
        game.action_required = {"id": "p1", "action": "finalize_roll"}
        game.finalize_roll("p1")

        game.concurrent_action = {
            "kind": "harvest_choices",
            "pending": ["p1"],
            "completed": [],
            "responses": {},
            "data": {
                "phase": "scan",
                "prompts": {
                    "p1": [{
                        "id": "p1",
                        "sub_kind": "harvest_optional_exchange",
                        "action": "harvest_optional_exchange",
                        "pending_required_choice": {"command": "exchange g 1 s 1"},
                    }]
                },
                "prompt_seq": 1,
            },
        }

        with self.assertRaises(ValueError):
            game.submit_concurrent_action(
                "p1", "p1|confirm_harvest_exchange", kind="harvest_choices"
            )

        self.assertEqual(game.action_required.get("action"), "event_slay_cost_choice")
        self.assertIsNotNone(game.pending_event_slay_cost)


    def test_apply_event_slay_cost_opens_harvest_without_extra_advance(self):
        """apply_event_slay_cost must bootstrap harvest itself (server endpoint path)."""
        p1 = Player("p1", "Player 1")
        p1.gold_score = 10
        p1.strength_score = 10
        p1.magic_score = 10
        p1.owned_citizens.append(make_exchange_citizen(100, "exchange g 1 s 1"))

        game = make_game_for_test([p1])
        game.monster_grid = [[make_board_monster()], [make_corrupted_cleric()], [], [], []]
        game.phase = "roll_pending"
        game.pending_roll = {"rolled_die_one": 1, "rolled_die_two": 2, "rolled_die_sum": 3}
        game.action_required = {"id": "p1", "action": "finalize_roll"}
        game.finalize_roll("p1")

        self.assertIsNone(game.harvest_player_order)
        self.assertEqual(game.action_required.get("action"), "event_slay_cost_choice")

        game.apply_event_slay_cost("p1", monster_id=99)

        self.assertIsNotNone(game.harvest_player_order)
        ca = game.concurrent_action
        self.assertIsNotNone(ca, "harvest gate should open immediately after cleric resolves")
        self.assertEqual(ca.get("kind"), "harvest_choices")
        self.assertIn("p1", ca.get("pending") or [])


if __name__ == "__main__":
    unittest.main()
