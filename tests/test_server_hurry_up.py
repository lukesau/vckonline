"""Server-side hurry-up timer tests.

The "hurry-up" timer is a per-action shot clock the server arms whenever
the game is waiting on the active player's next standard action. On expiry
the server auto-takes +1 of the player's lowest resource (random tie-break
among tied lowest). This replaces the older "game has been idle for 3
minutes" countdown that shared the same UI slot but was reset by the
client's state-poll safety net (PASSIVE_GAME_POLL_MS in 01-core.js).

These tests skip the asyncio sleep entirely and call the apply helper
directly: `_hurry_up_apply` is the unit under test, and the timer task is
just a thin `asyncio.sleep` shim around it.
"""

import asyncio
import random
import time
import unittest

import server
from game import Game
from game_models import Player


def _make_action_phase_game(game_id, scores):
    """Two-player game already in action phase, waiting on p1's standard action."""
    p1 = Player("p1", "Player 1")
    p2 = Player("p2", "Player 2")
    p1.gold_score = scores["p1"][0]
    p1.strength_score = scores["p1"][1]
    p1.magic_score = scores["p1"][2]
    p2.gold_score = scores["p2"][0]
    p2.strength_score = scores["p2"][1]
    p2.magic_score = scores["p2"][2]
    return Game({
        "game_id": game_id,
        "player_list": [p1, p2],
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "p1", "action": "standard_action"},
        "game_log": [],
        "turn_index": 0,
        "phase": "action",
        "actions_remaining": 2,
    })


class HurryUpShouldRunTests(unittest.TestCase):
    def test_runs_during_active_player_standard_action(self):
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        self.assertTrue(server._hurry_up_should_run(game))

    def test_does_not_run_outside_action_phase(self):
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.phase = "harvest"
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_on_concurrent_gate(self):
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.concurrent_action = {"kind": "choose_duke", "pending": ["p1"]}
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_when_mid_prompt(self):
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.action_required = {"id": "p1", "action": "choose_monster_slay"}
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_when_actions_exhausted(self):
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.actions_remaining = 0
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_during_shutdown(self):
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.shutdown = {"reason": "test"}
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_during_roll_pending(self):
        # New turn: dice are rolled, player must finalize (possibly via
        # Twilight / Blood Moon reroll). No shot clock here -- they may sit
        # on a roll-modifier domain decision for as long as they like.
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.phase = "roll_pending"
        game.action_required = {"id": "p1", "action": "finalize_roll"}
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_during_manual_harvest_prompt(self):
        # Manual harvest steps (e.g. picking which starter pays out) are
        # not "regular actions" and have no shot clock.
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.phase = "harvest"
        game.action_required = {"id": "p1", "action": "manual_harvest"}
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_during_action_end_pending(self):
        # End-of-action domain prompts (pay/take vs another player) trigger
        # after the standard action resolves; they are not a "regular action"
        # so they get no shot clock.
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.phase = "action_end_pending"
        game.action_required = {"id": "p1", "action": "choose_player_to_pay"}
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_during_slay_payment_prompt(self):
        # The slay action's payment sub-prompt is mid-action and gets no
        # shot clock even though it's still during phase=='action'.
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.action_required = {"id": "p1", "action": "slay_monster_payment"}
        self.assertFalse(server._hurry_up_should_run(game))

    def test_does_not_run_during_event_slay_cost_choice(self):
        # Event-slay-cost prompts let the player pick which monster to
        # accept the extra cost on. Decision phase, not a regular action.
        game = _make_action_phase_game("g1", {"p1": (1, 0, 1), "p2": (0, 0, 0)})
        game.action_required = {"id": "p1", "action": "event_slay_cost_choice"}
        self.assertFalse(server._hurry_up_should_run(game))


class PickLowestResourceTests(unittest.TestCase):
    def test_picks_unique_lowest(self):
        p = Player("p1", "Player 1")
        p.gold_score = 5
        p.strength_score = 2
        p.magic_score = 9
        self.assertEqual(server._pick_lowest_resource(p), "strength")

    def test_tie_break_is_random_across_tied_lowest(self):
        p = Player("p1", "Player 1")
        p.gold_score = 0
        p.strength_score = 0
        p.magic_score = 4
        seen = set()
        rng_backup = random.getstate()
        try:
            for seed in range(200):
                random.seed(seed)
                seen.add(server._pick_lowest_resource(p))
        finally:
            random.setstate(rng_backup)
        self.assertEqual(seen, {"gold", "strength"})

    def test_tie_break_three_way_covers_all(self):
        p = Player("p1", "Player 1")
        p.gold_score = 3
        p.strength_score = 3
        p.magic_score = 3
        seen = set()
        rng_backup = random.getstate()
        try:
            for seed in range(200):
                random.seed(seed)
                seen.add(server._pick_lowest_resource(p))
        finally:
            random.setstate(rng_backup)
        self.assertEqual(seen, {"gold", "strength", "magic"})


class HurryUpApplyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._broadcasts = []

        original = server.manager.broadcast

        async def fake_broadcast(game_id, game):
            self._broadcasts.append((game_id, game))

        server.manager.broadcast = fake_broadcast
        self.addCleanup(setattr, server.manager, "broadcast", original)

    async def test_apply_consumes_one_action_and_takes_lowest(self):
        game = _make_action_phase_game(
            "hu-apply-1", {"p1": (5, 1, 3), "p2": (0, 0, 0)}
        )
        deadline = time.time() + 0.1
        game.hurry_up_deadline = deadline
        server.games["hu-apply-1"] = game
        try:
            await server._hurry_up_apply("hu-apply-1", deadline)
        finally:
            server.games.pop("hu-apply-1", None)
            server._hurry_up_cancel("hu-apply-1")

        self.assertEqual(game.player_list[0].strength_score, 2)
        self.assertEqual(game.player_list[0].gold_score, 5)
        self.assertEqual(game.player_list[0].magic_score, 3)
        self.assertEqual(game.actions_remaining, 1)
        self.assertTrue(self._broadcasts, "should have broadcast updated state")
        self.assertIn("Hurry-up", game.game_log[-1]["msg"])

    async def test_apply_last_action_ends_turn(self):
        game = _make_action_phase_game(
            "hu-apply-2", {"p1": (5, 5, 0), "p2": (0, 0, 0)}
        )
        game.actions_remaining = 1
        deadline = time.time() + 0.1
        game.hurry_up_deadline = deadline
        server.games["hu-apply-2"] = game
        try:
            await server._hurry_up_apply("hu-apply-2", deadline)
        finally:
            server.games.pop("hu-apply-2", None)
            server._hurry_up_cancel("hu-apply-2")

        self.assertEqual(game.player_list[0].magic_score, 1)
        self.assertEqual(game.turn_index, 1)
        # finish_turn_if_no_actions_remaining → next player's roll phase. The
        # roll auto-advances to roll_pending (waiting for finalize_roll) before
        # control returns. The active player is now p2; their hurry-up clock
        # is rearmed by _hurry_up_reset only after they finalize_roll the dice.
        self.assertEqual(game.phase, "roll_pending")

    async def test_apply_is_a_no_op_if_deadline_was_superseded(self):
        game = _make_action_phase_game(
            "hu-apply-3", {"p1": (5, 5, 0), "p2": (0, 0, 0)}
        )
        old_deadline = time.time() + 0.1
        game.hurry_up_deadline = old_deadline + 60.0
        server.games["hu-apply-3"] = game
        try:
            await server._hurry_up_apply("hu-apply-3", old_deadline)
        finally:
            server.games.pop("hu-apply-3", None)
            server._hurry_up_cancel("hu-apply-3")

        self.assertEqual(game.player_list[0].magic_score, 0)
        self.assertEqual(game.actions_remaining, 2)
        self.assertFalse(self._broadcasts)


class HurryUpResetAndEnsureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        original = server.manager.broadcast

        async def fake_broadcast(game_id, game):
            return

        server.manager.broadcast = fake_broadcast
        self.addCleanup(setattr, server.manager, "broadcast", original)

    async def test_reset_arms_a_fresh_deadline(self):
        game = _make_action_phase_game(
            "hu-r-1", {"p1": (1, 1, 1), "p2": (0, 0, 0)}
        )
        server.games["hu-r-1"] = game
        try:
            before = time.time()
            server._hurry_up_reset("hu-r-1")
            self.assertGreater(game.hurry_up_deadline, before + 0.5)
            self.assertLessEqual(game.hurry_up_deadline, before + server.HURRY_UP_SECONDS + 1.0)
        finally:
            server._hurry_up_cancel("hu-r-1")
            server.games.pop("hu-r-1", None)

    async def test_ensure_does_not_push_back_existing_deadline(self):
        game = _make_action_phase_game(
            "hu-e-1", {"p1": (1, 1, 1), "p2": (0, 0, 0)}
        )
        server.games["hu-e-1"] = game
        try:
            server._hurry_up_reset("hu-e-1")
            original_deadline = game.hurry_up_deadline
            # Wait briefly so we can detect a refresh.
            await asyncio.sleep(0.05)
            server._hurry_up_ensure("hu-e-1")
            self.assertEqual(game.hurry_up_deadline, original_deadline)
        finally:
            server._hurry_up_cancel("hu-e-1")
            server.games.pop("hu-e-1", None)

    async def test_ensure_arms_when_no_deadline_present(self):
        game = _make_action_phase_game(
            "hu-e-2", {"p1": (1, 1, 1), "p2": (0, 0, 0)}
        )
        server.games["hu-e-2"] = game
        try:
            self.assertEqual(game.hurry_up_deadline, 0.0)
            before = time.time()
            server._hurry_up_ensure("hu-e-2")
            self.assertGreater(game.hurry_up_deadline, before + 0.5)
        finally:
            server._hurry_up_cancel("hu-e-2")
            server.games.pop("hu-e-2", None)

    async def test_reset_clears_when_not_waiting_on_player(self):
        game = _make_action_phase_game(
            "hu-r-2", {"p1": (1, 1, 1), "p2": (0, 0, 0)}
        )
        game.phase = "harvest"
        server.games["hu-r-2"] = game
        try:
            game.hurry_up_deadline = time.time() + 60.0
            server._hurry_up_reset("hu-r-2")
            self.assertEqual(game.hurry_up_deadline, 0.0)
            self.assertNotIn("hu-r-2", server._hurry_up_tasks)
        finally:
            server.games.pop("hu-r-2", None)


class HurryUpSerializationTests(unittest.TestCase):
    def test_seconds_remaining_in_serialized_state(self):
        game = _make_action_phase_game(
            "hu-s-1", {"p1": (1, 1, 1), "p2": (0, 0, 0)}
        )
        game.hurry_up_deadline = time.time() + 45.0
        state = server._serialize_game_for_player(game, "p1")
        self.assertIsNotNone(state.get("hurry_up_seconds_remaining"))
        self.assertGreater(state["hurry_up_seconds_remaining"], 40.0)
        self.assertLessEqual(state["hurry_up_seconds_remaining"], 45.0)
        self.assertEqual(state["hurry_up_total_seconds"], server.HURRY_UP_SECONDS)

    def test_seconds_remaining_is_null_when_not_armed(self):
        game = _make_action_phase_game(
            "hu-s-2", {"p1": (1, 1, 1), "p2": (0, 0, 0)}
        )
        game.phase = "harvest"
        state = server._serialize_game_for_player(game, "p1")
        self.assertIsNone(state.get("hurry_up_seconds_remaining"))


if __name__ == "__main__":
    unittest.main()
