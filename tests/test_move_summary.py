"""Tests for agent decision summaries."""

import unittest

from agent.move_summary import (
    compare_decisions,
    format_compare_block,
    format_greedy_decision,
    format_mcts_decision,
    move_key,
    move_label,
)


class MoveSummaryTests(unittest.TestCase):
    def test_move_label_standard_actions(self):
        self.assertEqual(
            move_label({"action_type": "take_resource", "resource": "m"}),
            "take magic",
        )
        self.assertEqual(
            move_label({
                "action_type": "hire_citizen",
                "citizen_id": 7,
                "payment": {"gold": 3},
            }),
            "hire citizen #7 (3g)",
        )

    def test_compare_agree(self):
        move = {"action_type": "take_resource", "resource": "g"}
        key = move_key(move)
        greedy = {
            "policy": "greedy",
            "chosen": move,
            "candidates": [{"move": move, "key": key, "vp_equiv": 1.0, "delta_from_best": 0.0}],
            "best_vp_equiv": 1.0,
        }
        mcts = {
            "policy": "mcts",
            "chosen": move,
            "candidates": [{
                "move": move,
                "key": key,
                "visits": 80,
                "visit_pct": 80.0,
                "q": 0.62,
                "prior": 0.5,
            }],
            "iterations": 100,
            "workers": 1,
        }
        cmp = compare_decisions(greedy, mcts)
        self.assertTrue(cmp["same_move"])
        lines = format_compare_block(greedy, mcts)
        self.assertTrue(any("AGREE" in line for line in lines))

    def test_compare_diverge(self):
        greedy_move = {"action_type": "take_resource", "resource": "g"}
        mcts_move = {"action_type": "hire_citizen", "citizen_id": 3}
        g_key = move_key(greedy_move)
        m_key = move_key(mcts_move)
        greedy = {
            "policy": "greedy",
            "chosen": greedy_move,
            "candidates": [
                {"move": greedy_move, "key": g_key, "vp_equiv": 2.0, "delta_from_best": 0.0},
                {"move": mcts_move, "key": m_key, "vp_equiv": 1.5, "delta_from_best": -0.5},
            ],
            "best_vp_equiv": 2.0,
        }
        mcts = {
            "policy": "mcts",
            "chosen": mcts_move,
            "candidates": [
                {"move": mcts_move, "key": m_key, "visits": 55, "visit_pct": 55.0, "q": 0.58, "prior": 0.4},
                {"move": greedy_move, "key": g_key, "visits": 45, "visit_pct": 45.0, "q": 0.52, "prior": 0.3},
            ],
            "iterations": 100,
            "workers": 1,
        }
        cmp = compare_decisions(greedy, mcts)
        self.assertFalse(cmp["same_move"])
        self.assertEqual(cmp["top3_overlap"], 2)
        lines = format_compare_block(greedy, mcts)
        self.assertTrue(any("DIVERGE" in line for line in lines))
        self.assertTrue(any(line.startswith("greedy:") for line in lines))
        self.assertTrue(any(line.startswith("mcts:") for line in lines))

    def test_formatters_include_pick_line(self):
        move = {"action_type": "take_resource", "resource": "s"}
        greedy_lines = format_greedy_decision({
            "policy": "greedy",
            "chosen": move,
            "candidates": [{"move": move, "vp_equiv": 0.5, "delta_from_best": 0.0}],
            "best_vp_equiv": 0.5,
        })
        self.assertTrue(any("pick → take strength" in line for line in greedy_lines))

        mcts_lines = format_mcts_decision({
            "policy": "mcts",
            "chosen": move,
            "candidates": [{
                "move": move,
                "visits": 10,
                "visit_pct": 100.0,
                "q": 0.5,
                "prior": 1.0,
            }],
            "iterations": 10,
            "workers": 1,
        })
        self.assertTrue(any("pick → take strength" in line for line in mcts_lines))


if __name__ == "__main__":
    unittest.main()
