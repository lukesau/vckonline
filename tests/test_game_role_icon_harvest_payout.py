import unittest

from cards import Citizen, Domain, Noble
from game import Game
from game_models import Player


def make_citizen(citizen_id, name="Citizen", worker=0, soldier=0, special_on=""):
    return Citizen(
        citizen_id, name,
        1, 2, 0,
        0, 0, soldier, worker,
        0, 0, 0, 0, 0, 0, 0, 0,
        bool(special_on), False,
        special_on, "",
        False, "test",
    )


def make_domain(domain_id, name="Domain", worker=0, soldier=0):
    return Domain(
        domain_id, name, 5,
        0, 0, soldier, worker,
        1, False, False, "", "", "test domain", "test",
    )


def make_noble(noble_id, name="Noble", worker=0, soldier=0):
    return Noble(
        noble_id, name,
        0, 0, soldier, worker,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, 0, 0, 0,
        0, "",
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


class RoleIconHarvestPayoutTests(unittest.TestCase):
    """Butcher / Warlord / Blacksmith / Baker use count owned_worker|owned_soldier.

    Harvest must scale off face-up Citizen role pips only. Domain and Noble
    icons still feed calc_roles() for endgame Duke/Noble scoring.
    """

    def _payout(self, player, effect):
        game = make_game(player)
        return game.payouts.execute_special_payout(effect, player.player_id)

    def test_butcher_pays_two_gold_per_worker_citizen_pip(self):
        player = Player("p1", "Player 1")
        player.owned_citizens.extend([
            make_citizen(10, "Butcher", worker=1, special_on="count owned_worker g 2"),
            make_citizen(101, "Worker A", worker=1),
            make_citizen(102, "Worker B", worker=1),
        ])

        payout = self._payout(player, "count owned_worker g 2")

        self.assertEqual(payout, [6, 0, 0, 0])

    def test_butcher_ignores_domain_and_noble_worker_icons(self):
        player = Player("p1", "Player 1")
        player.owned_citizens.extend([
            make_citizen(10, "Butcher", worker=1),
            make_citizen(101, "Worker", worker=1),
        ])
        player.owned_domains.append(make_domain(13, "Halfpenny Hill", worker=3))
        player.owned_nobles.append(make_noble(6, "Izmael the Provider", worker=1))

        payout = self._payout(player, "count owned_worker g 2")

        # 2 citizen worker pips only -> 4g (not 2+3+1=6 pips / 12g).
        self.assertEqual(payout, [4, 0, 0, 0])
        self.assertEqual(player.calc_roles()["worker_count"], 6)

    def test_butcher_ignores_flipped_worker_citizens(self):
        player = Player("p1", "Player 1")
        flipped = make_citizen(101, "Flipped Worker", worker=1)
        flipped.is_flipped = True
        player.owned_citizens.extend([
            make_citizen(10, "Butcher", worker=1),
            flipped,
            make_citizen(102, "Worker", worker=1),
        ])

        payout = self._payout(player, "count owned_worker g 2")

        self.assertEqual(payout, [4, 0, 0, 0])

    def test_warlord_pays_one_strength_per_soldier_citizen_pip(self):
        player = Player("p1", "Player 1")
        player.owned_citizens.extend([
            make_citizen(16, "Warlord", soldier=1),
            make_citizen(101, "Soldier", soldier=1),
        ])

        payout = self._payout(player, "count owned_soldier s 1")

        self.assertEqual(payout, [0, 2, 0, 0])

    def test_warlord_ignores_domain_and_noble_soldier_icons(self):
        player = Player("p1", "Player 1")
        player.owned_citizens.extend([
            make_citizen(16, "Warlord", soldier=1),
            make_citizen(101, "Soldier", soldier=1),
        ])
        player.owned_domains.append(make_domain(10, "Blood Crow Army", soldier=3))
        player.owned_nobles.append(make_noble(3, "Doom Chun'nan", soldier=1))

        payout = self._payout(player, "count owned_soldier s 1")

        self.assertEqual(payout, [0, 2, 0, 0])
        self.assertEqual(player.calc_roles()["soldier_count"], 6)

    def test_blacksmith_and_baker_share_citizen_only_soldier_count(self):
        player = Player("p1", "Player 1")
        player.owned_citizens.extend([
            make_citizen(12, "Blacksmith", worker=1, soldier=0),
            make_citizen(28, "Baker", worker=1, soldier=0),
            make_citizen(101, "Soldier", soldier=1),
        ])
        player.owned_domains.append(make_domain(10, "Blood Crow Army", soldier=3))

        blacksmith = self._payout(player, "count owned_soldier g 1")
        baker = self._payout(player, "count owned_soldier g 2")

        self.assertEqual(blacksmith, [1, 0, 0, 0])
        self.assertEqual(baker, [2, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
