"""End-game tie-break: on equal VP, the FEWEST tableau cards wins.

Rulebook: "In the event of a tie, the tied player who has the fewest cards
in their tableau wins the game. If still a tie, the tied players share the
victory." Exercised against `_calculate_final_scores` ranking and
`_build_final_result` (win / tiebreak / true-tie kinds).
"""

import unittest

from cards import Monster
from game import Game
from game_models import Player


def make_monster(monster_id, vp_reward=0):
    m = Monster(
        monster_id, f"Monster {monster_id}", "Cutthroats", "Orc", 1,
        1, 0, vp_reward,
        0, 0, 0,
        False, "",
        False, "",
        False, "test",
    )
    return m


def make_game(players):
    return Game({
        "game_id": "test-game",
        "preset": "base1",
        "player_list": players,
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 1,
        "die_sum": 2,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
    })


class TieBreakTests(unittest.TestCase):
    def _two_tied_players(self):
        """Both on 6 total VP; p1 holds 2 cards, p2 holds 1."""
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        p1.victory_score = 2
        p1.owned_monsters.extend([make_monster(1, vp_reward=2),
                                  make_monster(2, vp_reward=2)])
        p2.victory_score = 3
        p2.owned_monsters.append(make_monster(3, vp_reward=3))
        return p1, p2

    def test_fewest_cards_ranks_first_on_vp_tie(self):
        p1, p2 = self._two_tied_players()
        game = make_game([p1, p2])
        scores = game.endgame._calculate_final_scores()
        self.assertEqual([s["total_vp"] for s in scores], [6, 6])
        self.assertEqual(scores[0]["player_id"], "p2",
                         "the smaller tableau must rank first on a VP tie")
        self.assertEqual(scores[0]["rank"], 1)

    def test_final_result_awards_tiebreak_to_smaller_tableau(self):
        p1, p2 = self._two_tied_players()
        game = make_game([p1, p2])
        result = game.endgame._build_final_result(
            game.endgame._calculate_final_scores())
        self.assertEqual(result["kind"], "tiebreak")
        self.assertEqual(result["winner_player_ids"], ["p2"])
        self.assertIn("smaller tableau", result["detail"])

    def test_outright_vp_win_needs_no_tiebreak(self):
        p1, p2 = self._two_tied_players()
        p2.victory_score += 1
        game = make_game([p1, p2])
        result = game.endgame._build_final_result(
            game.endgame._calculate_final_scores())
        self.assertEqual(result["kind"], "win")
        self.assertEqual(result["winner_player_ids"], ["p2"])

    def test_equal_vp_and_tableau_share_the_victory(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        p1.victory_score = 4
        p1.owned_monsters.append(make_monster(1, vp_reward=2))
        p2.victory_score = 4
        p2.owned_monsters.append(make_monster(2, vp_reward=2))
        game = make_game([p1, p2])
        result = game.endgame._build_final_result(
            game.endgame._calculate_final_scores())
        self.assertEqual(result["kind"], "tie")
        self.assertEqual(sorted(result["winner_player_ids"]), ["p1", "p2"])


if __name__ == "__main__":
    unittest.main()
