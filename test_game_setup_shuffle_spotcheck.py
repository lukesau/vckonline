"""Visual spot-check for shadowvale setup shuffling.

Run with:

    python3 -m unittest test_game_setup_shuffle_spotcheck -v

This intentionally prints a small set of real `load_game_data` deals so the
duke/domain mix can be inspected without opening the GUI.
"""

import contextlib
import importlib.util
import io
import random
import socket
import unittest

from game_models import LobbyMember
from game_setup import load_game_data


def _db_ready():
    if importlib.util.find_spec("mariadb") is None:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        return sock.connect_ex(("127.0.0.1", 3306)) == 0
    finally:
        sock.close()


class ShadowvaleShuffleSpotcheckTests(unittest.TestCase):
    @unittest.skipUnless(
        _db_ready(),
        "requires active DB tunnel and mariadb module; run source ./activate_with_env.sh first",
    )
    def test_shadowvale_duke_and_domain_deals_vary(self):
        players = [
            LobbyMember("Player 1", "p1"),
            LobbyMember("Player 2", "p2"),
            LobbyMember("Player 3", "p3"),
            LobbyMember("Player 4", "p4"),
        ]
        samples = []
        first_player_duke_expansions = []
        visible_domain_sets = []

        for seed in range(8):
            random.seed(seed)
            with contextlib.redirect_stdout(io.StringIO()):
                state = load_game_data(
                    f"shadowvale-shuffle-spotcheck-{seed}",
                    "shadowvale",
                    players,
                )

            duke_deals = []
            for player in state["player_list"]:
                dukes = [
                    f"{duke.duke_id}:{duke.name} [{duke.expansion}]"
                    for duke in player.owned_dukes
                ]
                duke_deals.append((player.name, dukes))

            visible_domains = [
                f"{stack[-1].domain_id}:{stack[-1].name} [{stack[-1].expansion}]"
                for stack in state["domain_grid"]
            ]

            samples.append((seed, duke_deals, visible_domains))
            first_player_duke_expansions.append(
                tuple(duke.expansion for duke in state["player_list"][0].owned_dukes)
            )
            visible_domain_sets.append(tuple(visible_domains))

        print("\nShadowvale shuffle spot-check samples:")
        for seed, duke_deals, visible_domains in samples:
            print(f"\nseed={seed}")
            print("  dukes:")
            for player_name, dukes in duke_deals:
                print(f"    {player_name}: {', '.join(dukes)}")
            print("  visible domain tops:")
            for domain in visible_domains:
                print(f"    {domain}")

        self.assertFalse(
            all(
                expansions == ("shadowvale", "shadowvale")
                for expansions in first_player_duke_expansions
            ),
            "old deterministic ordering always gave the first dealt player two shadowvale dukes",
        )
        self.assertGreater(
            len(set(visible_domain_sets)),
            1,
            "visible domain tops should vary across seeded shadowvale setups",
        )


if __name__ == "__main__":
    unittest.main()
