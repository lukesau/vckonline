"""Training mode: move grading, per-action feedback, end-game summary."""

import asyncio
import unittest

import db_config
import server
from agent import fake_db
from agent.grading import classify, empty_tally, grade_move, moves_equivalent
from server import CreateLobbyRequest, GameActionRequest, JoinLobbyRequest, ReadyRequest

_real_connect = db_config.connect


def setUpModule():
    fake_db.install()


def tearDownModule():
    db_config.connect = _real_connect


def _reset_server_state():
    server.lobbies.clear()
    server.games.clear()
    server.game_histories.clear()
    server._bot_policies.clear()
    server._hint_cache.clear()
    server._analysis_state.clear()
    server.gamers.clear()


def _decision(moves, qs, chosen_index=0):
    return {
        "policy": "mcts",
        "chosen": moves[chosen_index],
        "candidates": [
            {"move": m, "key": str(i), "visits": 100 - i, "q": q, "prior": 0.1,
             "visit_pct": 10.0}
            for i, (m, q) in enumerate(zip(moves, qs))
        ],
    }


class GradeMoveTests(unittest.TestCase):
    MOVES = [
        {"player_id": "p1", "action_type": "take_resource", "resource": "magic"},
        {"player_id": "p1", "action_type": "take_resource", "resource": "gold"},
        {"player_id": "p1", "action_type": "take_resource", "resource": "strength"},
    ]

    def test_classify_thresholds(self):
        self.assertEqual(classify(0.0), "great")
        self.assertEqual(classify(0.02), "great")
        self.assertEqual(classify(0.021), "fine")
        self.assertEqual(classify(0.08), "fine")
        self.assertEqual(classify(0.081), "blunder")

    def test_perfect_when_matching_bot(self):
        decision = _decision(self.MOVES, [0.6, 0.59, 0.4])
        fb = grade_move(decision, dict(self.MOVES[0]))
        self.assertEqual(fb["category"], "perfect")
        self.assertEqual(fb["delta_pct"], 0.0)

    def test_great_fine_blunder_by_delta(self):
        decision = _decision(self.MOVES, [0.60, 0.59, 0.45])
        self.assertEqual(grade_move(decision, dict(self.MOVES[1]))["category"], "great")
        decision = _decision(self.MOVES, [0.60, 0.55, 0.45])
        self.assertEqual(grade_move(decision, dict(self.MOVES[1]))["category"], "fine")
        self.assertEqual(grade_move(decision, dict(self.MOVES[2]))["category"], "blunder")

    def test_unrated_when_off_candidate_list(self):
        decision = _decision(self.MOVES[:2], [0.6, 0.5])
        fb = grade_move(decision, dict(self.MOVES[2]))
        self.assertEqual(fb["category"], "unrated")

    def test_move_equivalence_ignores_private_and_none(self):
        a = {"player_id": "p1", "action_type": "finalize_roll", "die_one": None,
             "die_two": None, "kind": None}
        b = {"player_id": "p1", "action_type": "finalize_roll", "_mod_cost_gold": 0}
        self.assertTrue(moves_equivalent(a, b))
        c = {"player_id": "p1", "action_type": "finalize_roll", "die_one": 6, "die_two": 2}
        self.assertFalse(moves_equivalent(a, c))

    def test_payment_normalization(self):
        a = {"player_id": "p1", "action_type": "hire_citizen", "citizen_id": 3,
             "payment": {"gold": 3, "strength": 0, "magic": 0}}
        b = {"player_id": "p1", "action_type": "hire_citizen", "citizen_id": 3,
             "payment": {"gold": 3}}
        self.assertTrue(moves_equivalent(a, b))


class TrainingModeEndToEndTests(unittest.TestCase):
    def setUp(self):
        _reset_server_state()
        from agent import grading

        self._orig_iters = grading.ANALYSIS_ITERATIONS
        grading.ANALYSIS_ITERATIONS = 8  # keep tests fast

    def tearDown(self):
        from agent import grading

        grading.ANALYSIS_ITERATIONS = self._orig_iters

    def _start_training_game(self, training_mode=True, move_analysis=False):
        async def _go():
            a = await server.create_lobby(CreateLobbyRequest(
                name="Alice", preset="base", min_players=2,
                training_mode=training_mode, move_analysis=move_analysis,
            ))
            b = await server.join_lobby(JoinLobbyRequest(name="Bob", lobby_id=a["lobby_id"]))
            await server.set_ready(ReadyRequest(player_id=a["player_id"]))
            await server.set_ready(ReadyRequest(player_id=b["player_id"]))
            return a["player_id"], b["player_id"]
        pid_a, pid_b = asyncio.run(_go())
        game_id, game = next(iter(server.games.items()))
        return game_id, game, pid_a, pid_b

    def test_flags_stamped_and_registry_created(self):
        game_id, game, *_ = self._start_training_game()
        self.assertTrue(game.training_mode)
        self.assertFalse(game.move_analysis)
        self.assertIn(game_id, server._analysis_state)

    def test_no_registry_without_flags(self):
        game_id, game, *_ = self._start_training_game(training_mode=False)
        self.assertNotIn(game_id, server._analysis_state)
        state = server._serialize_game_for_player(game, None)
        self.assertFalse(state["training_mode"])

    def test_action_is_graded_and_feedback_serialized(self):
        game_id, game, pid_a, pid_b = self._start_training_game()

        async def _play_graded_action():
            # Resolve the duke gate (concurrent, >=2 options -> graded).
            from agent.headless import legal_moves

            graded_pid = None
            for pid in (pid_a, pid_b):
                moves = legal_moves(game, pid)
                if len(moves) >= 2:
                    graded_pid = pid
                    request = GameActionRequest(player_id=pid, **{
                        k: v for k, v in moves[0].items()
                        if k in ("action_type", "response", "kind")
                    })
                    await server.perform_game_action(game_id, request)
                    break
            # Let the fire-and-forget grading task finish.
            for _ in range(200):
                await asyncio.sleep(0.01)
                if server._analysis_state[game_id]["feedback"].get(graded_pid):
                    break
            return graded_pid

        graded_pid = asyncio.run(_play_graded_action())
        feedback = server._analysis_state[game_id]["feedback"].get(graded_pid)
        self.assertIsNotNone(feedback, "grading task never recorded feedback")
        self.assertIn(feedback["category"],
                      ("perfect", "great", "fine", "blunder", "unrated"))
        tally = server._analysis_state[game_id]["tallies"][graded_pid]
        self.assertEqual(sum(tally.values()), 1)

        state = server._serialize_game_for_player(game, graded_pid)
        self.assertEqual(state.get("move_feedback"), feedback)
        other = pid_b if graded_pid == pid_a else pid_a
        state_other = server._serialize_game_for_player(game, other)
        self.assertNotIn("move_feedback", state_other)

    def test_game_over_summary_serialized(self):
        game_id, game, pid_a, pid_b = self._start_training_game()
        astate = server._analysis_state[game_id]
        astate["tallies"][pid_a] = {**empty_tally(), "perfect": 3, "blunder": 1}
        game.phase = "game_over"
        game.final_scores = game.final_scores or []
        state = server._serialize_game_for_player(game, pid_a)
        summary = state.get("move_quality_summary")
        self.assertTrue(summary)
        row = next(r for r in summary if r["player_id"] == pid_a)
        self.assertEqual(row["perfect"], 3)
        self.assertEqual(row["blunder"], 1)
        self.assertEqual(row["graded"], 4)
        self.assertEqual(row["name"], "Alice")


if __name__ == "__main__":
    unittest.main()
