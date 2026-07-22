"""Tests for move-recommendation mode helpers."""

import unittest

from agent.game_url import parse_game_url
from agent.move_summary import format_recommendation_block, move_key


class RecommendUrlTests(unittest.TestCase):
    def test_parse_browser_url(self):
        url = (
            "https://vcko.lukesau.com/?game_id=c361f04f-445e-4121-808b-81cb36b2ce08"
            "&player_id=bg87dTCzzhaAwj8WStWLio"
        )
        base_url, game_id, player_id = parse_game_url(url)
        self.assertEqual(base_url, "https://vcko.lukesau.com")
        self.assertEqual(game_id, "c361f04f-445e-4121-808b-81cb36b2ce08")
        self.assertEqual(player_id, "bg87dTCzzhaAwj8WStWLio")

    def test_parse_rejects_missing_ids(self):
        with self.assertRaises(ValueError):
            parse_game_url("https://vcko.lukesau.com/")


class RecommendFormatTests(unittest.TestCase):
    def test_shows_top_five_rankings(self):
        moves = [
            {"action_type": "take_resource", "resource": "g"},
            {"action_type": "take_resource", "resource": "s"},
            {"action_type": "take_resource", "resource": "m"},
            {"action_type": "hire_citizen", "citizen_id": 1},
            {"action_type": "hire_citizen", "citizen_id": 2},
            {"action_type": "build_domain", "domain_id": 3},
        ]
        greedy = {
            "policy": "greedy",
            "chosen": moves[0],
            "best_vp_equiv": 5.0,
            "candidates": [
                {"move": m, "key": move_key(m), "vp_equiv": 5.0 - i * 0.5, "delta_from_best": -i * 0.5}
                for i, m in enumerate(moves)
            ],
        }
        mcts = {
            "policy": "mcts",
            "chosen": moves[3],
            "iterations": 100,
            "workers": 1,
            "candidates": [
                {
                    "move": m,
                    "key": move_key(m),
                    "visits": 100 - i * 10,
                    "visit_pct": 20.0,
                    "q": 0.6 - i * 0.05,
                    "prior": 0.2,
                }
                for i, m in enumerate(moves)
            ],
        }
        lines = format_recommendation_block(greedy, mcts, top_n=5)
        text = "\n".join(lines)
        self.assertIn("read-only", text)
        self.assertIn("#5", text)
        self.assertNotIn("playing MCTS", text)
        self.assertIn("#1", text)
        self.assertTrue(any(line.startswith("  #1 ") for line in lines))


if __name__ == "__main__":
    unittest.main()
