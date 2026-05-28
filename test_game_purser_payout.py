import unittest

from cards import Citizen, Starter
from game import Game
from game_models import Player


def make_citizen(citizen_id, name="Plain", special_on=""):
    """Minimal Citizen used as a body-count target for Purser.

    Constructor positional args (see cards.Citizen.__init__):
      citizen_id, name, gold_cost, roll_match1, roll_match2,
      shadow, holy, soldier, worker,
      g_on, g_off, s_on, s_off, m_on, m_off, vp_on, vp_off,
      has_sp_on, has_sp_off, sp_on, sp_off, special_citizen, expansion
    """
    return Citizen(
        citizen_id, name,
        1,        # gold_cost
        2, 0,     # roll_match1, roll_match2
        0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0,
        bool(special_on), False,
        special_on, "",
        False, "test",
    )


def make_purser(citizen_id=48):
    return make_citizen(citizen_id, name="Purser", special_on="count owned_citizens g 1")


def make_starter(starter_id=1, name="Peasant"):
    return Starter(
        starter_id, name, 5, 0,
        1, 1, 0, 0, 0, 0,
        False, False, "", "",
        "test",
    )


def make_game(player):
    return Game({
        "game_id": "test-game",
        "player_list": [player],
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


class PurserPayoutTests(unittest.TestCase):
    """Purser's special_payout_on_turn = 'count owned_citizens g 1'.

    Verifies the `count owned_citizens` verb in the citizen harvest path:
      * scales 1g per face-up owned citizen, including the Purser itself
      * excludes flipped citizens (mirrors `count owned_citizen_name`)
      * does NOT include starter citizens (starters live in a separate pool)
    """

    def _run_purser_payout(self, player):
        game = make_game(player)
        return game.execute_special_payout(
            "count owned_citizens g 1", player.player_id
        )

    def test_purser_alone_pays_one_gold_for_itself(self):
        player = Player("p1", "Player 1")
        player.owned_citizens.append(make_purser())

        payout = self._run_purser_payout(player)

        # 1 owned citizen (the Purser) -> 1g, no other resources.
        self.assertEqual(payout, [1, 0, 0, 0])

    def test_purser_pays_one_per_face_up_citizen(self):
        player = Player("p1", "Player 1")
        player.owned_citizens.extend([
            make_purser(),
            make_citizen(101),
            make_citizen(102),
            make_citizen(103),
        ])

        payout = self._run_purser_payout(player)

        # 4 face-up owned citizens -> 4g.
        self.assertEqual(payout, [4, 0, 0, 0])

    def test_purser_ignores_flipped_citizens(self):
        player = Player("p1", "Player 1")
        purser = make_purser()
        flipped = make_citizen(101)
        flipped.is_flipped = True
        player.owned_citizens.extend([
            purser,
            flipped,
            make_citizen(102),
        ])

        payout = self._run_purser_payout(player)

        # 2 face-up (Purser + the unflipped peer); flipped one is skipped.
        self.assertEqual(payout, [2, 0, 0, 0])

    def test_purser_does_not_count_starters(self):
        player = Player("p1", "Player 1")
        player.owned_citizens.append(make_purser())
        # Starters live in `owned_starters`, not `owned_citizens`, so they
        # are out of scope for the `count owned_citizens` verb.
        player.owned_starters.append(make_starter(1, "Peasant"))
        player.owned_starters.append(make_starter(2, "Knight"))

        payout = self._run_purser_payout(player)

        self.assertEqual(payout, [1, 0, 0, 0])

    def test_purser_with_only_flipped_peers_still_counts_itself(self):
        player = Player("p1", "Player 1")
        purser = make_purser()
        flipped_a = make_citizen(101)
        flipped_a.is_flipped = True
        flipped_b = make_citizen(102)
        flipped_b.is_flipped = True
        player.owned_citizens.extend([purser, flipped_a, flipped_b])

        payout = self._run_purser_payout(player)

        # Only the Purser is face-up -> 1g floor.
        self.assertEqual(payout, [1, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
