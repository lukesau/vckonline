"""Tests for `immunity.take` (Castle of the Seven Suns).

The card's iconography reads "Opponents Cannot Take You" where the legend
defines "you" as the player AND any of their cards or Resources. So the
immunity covers every "take" surface in the engine — citizen `steal`,
domain `take_from_player`, and domain `take_owned` — but does NOT cover
operators that aren't `take` (banish, flip, all-player resource loss).
"""

import unittest

from cards import Citizen, Domain
from game import Game
from game_models import Player


def make_castle_of_the_seven_suns(domain_id=26, passive_effect="immunity.take"):
    return Domain(
        domain_id, "Castle of the Seven Suns",
        12,                      # gold_cost
        1, 1, 1, 1,              # role counts
        2,                       # vp_reward
        False, True,             # has_activation_effect, has_passive_effect
        passive_effect,          # passive_effect (parsed by engine)
        None,                    # activation_effect
        "For the rest of the game opponents cannot take resources or cards from the holder.",
        "flamesandfrost",
    )


def make_red_hollow():
    return Domain(
        35, "Red Hollow",
        7,
        1, 0, 1, 1,
        2,
        False, True,
        "action.end manipulate_resources mode=take_from_player take=s:1 optional=true",
        None,
        "At the end of your Action Phase, take 1 Strength from a player of your choice.",
        "flamesandfrost",
    )


def make_hobbs_end():
    return Domain(
        51, "Hobb's End",
        7,
        2, 0, 1, 0,
        1,
        True, False,
        "",
        "steal_citizen gold_cost<=2",
        "Immediately take a Citizen worth 2 gold or less from a Player of your choice.",
        "shadowvale",
    )


def make_simple_citizen(citizen_id, gold_cost=2, shadow=0, holy=0, soldier=0, worker=0):
    return Citizen(
        citizen_id, f"Citizen {citizen_id}",
        gold_cost,
        1, 0,
        shadow, holy, soldier, worker,
        1, 0,
        0, 0, 0, 0, 0, 0,
        False, False, "", "",
        False, "test",
    )


def make_two_player_game():
    p1 = Player("p1", "Player 1")
    p1.gold_score = 0
    p1.strength_score = 0
    p1.magic_score = 0
    p2 = Player("p2", "Player 2")
    p2.gold_score = 5
    p2.strength_score = 0
    p2.magic_score = 0
    game = Game({
        "game_id": "test-game",
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
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "harvest",
    })
    return game, [p1, p2]


class TakeImmunityHelperTests(unittest.TestCase):
    def test_helper_true_with_immunity_take(self):
        _game, players = make_two_player_game()
        players[1].owned_domains.append(make_castle_of_the_seven_suns())
        game = _game
        self.assertTrue(game._player_has_take_immunity(players[1]))

    def test_helper_back_compat_with_legacy_immunity_steal(self):
        _game, players = make_two_player_game()
        players[1].owned_domains.append(
            make_castle_of_the_seven_suns(passive_effect="immunity.steal")
        )
        self.assertTrue(_game._player_has_take_immunity(players[1]))

    def test_helper_false_without_domain(self):
        game, players = make_two_player_game()
        self.assertFalse(game._player_has_take_immunity(players[0]))
        self.assertFalse(game._player_has_take_immunity(players[1]))


class StealAndTakeFromPlayerImmunityTests(unittest.TestCase):
    def test_steal_skips_player_with_immunity_take(self):
        game, players = make_two_player_game()
        players[1].owned_domains.append(make_castle_of_the_seven_suns())

        game.harvest._execute_steal_payout("steal g 1", players[0].player_id)

        # No eligible victim -> no harvest_steal prompt opened.
        self.assertNotEqual(game.action_required.get("action"), "harvest_steal")

    def test_take_from_player_skips_immunity_take(self):
        game, players = make_two_player_game()
        players[1].owned_domains.append(make_castle_of_the_seven_suns())

        parsed, _opt = game.domain_effects._manipulate_candidates_other_players(
            players[0].player_id, "take", {"take": "g:1"}
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("options"), [],
                         "Castle of the Seven Suns must shield gold-take from action.end take_from_player.")

    def test_red_hollow_opens_end_of_action_strength_take_prompt(self):
        game, players = make_two_player_game()
        game.phase = "action"
        game.actions_remaining = 0
        game.action_required["id"] = players[0].player_id
        game.action_required["action"] = "standard_action"
        players[0].owned_domains.append(make_red_hollow())
        players[1].strength_score = 1

        game.finish_turn_if_no_actions_remaining()

        self.assertEqual(game.phase, "action_end_pending")
        self.assertEqual(game.action_required.get("id"), players[0].player_id)
        self.assertEqual(game.action_required.get("action"), "choose_player")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "domain_manipulate_player")
        self.assertEqual(prc.get("item", {}).get("domain_name"), "Red Hollow")
        self.assertEqual(prc.get("item", {}).get("kv", {}).get("take"), "s:1")
        self.assertEqual([o.get("player_id") for o in prc.get("options", [])], [players[1].player_id])

    def test_hobbs_end_activation_opens_player_prompt(self):
        game, players = make_two_player_game()
        players[1].owned_citizens.append(make_simple_citizen(201, gold_cost=2))
        active = game._player_by_id(players[0].player_id)

        game.domain_effects._apply_domain_activation_effect(active, make_hobbs_end())

        self.assertEqual(game.action_required.get("id"), players[0].player_id)
        self.assertEqual(game.action_required.get("action"), "choose_player")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "steal_citizen")
        self.assertEqual(prc.get("item", {}).get("domain_name"), "Hobb's End")
        self.assertEqual(prc.get("max_cost"), 2)
        self.assertEqual([o.get("player_id") for o in prc.get("options", [])], [players[1].player_id])

    def test_hobbs_end_build_opens_player_prompt(self):
        game, players = make_two_player_game()
        game.phase = "action"
        active = game._player_by_id(players[0].player_id)
        active.gold_score = 7
        active.owned_citizens.extend([
            make_simple_citizen(301, shadow=2),
            make_simple_citizen(302, soldier=1),
        ])
        players[1].owned_citizens.append(make_simple_citizen(303, gold_cost=2))
        hobbs_end = make_hobbs_end()
        hobbs_end.toggle_visibility(True)
        hobbs_end.toggle_accessibility(True)
        game.domain_grid = [[hobbs_end]]

        game.build_domain(players[0].player_id, hobbs_end.domain_id, gp=7, mp=0, sp=0)

        self.assertEqual(game.action_required.get("id"), players[0].player_id)
        self.assertEqual(game.action_required.get("action"), "choose_player")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "steal_citizen")
        self.assertEqual([o.get("player_id") for o in prc.get("options", [])], [players[1].player_id])


class TakeOwnedImmunityTests(unittest.TestCase):
    """`take_owned` lifts a CARD off the target's tableau. Per the operator
    legend, "you" includes "any of your cards", so Castle should block this.
    Before the rename the engine missed this case entirely."""

    def test_take_owned_skips_player_with_immunity_take(self):
        game, players = make_two_player_game()
        players[1].owned_citizens.append(make_simple_citizen(101))
        players[1].owned_domains.append(make_castle_of_the_seven_suns())

        active = game._player_by_id(players[0].player_id)
        game.domain_effects._prompt_take_owned_card(
            active,
            "Test Domain",
            {"kind": "citizen", "pick": "random", "optional": False},
        )

        # No `choose_player` opened because every other player is protected.
        self.assertNotEqual(game.action_required.get("action"), "choose_player")

    def test_take_owned_still_targets_unprotected_players(self):
        game, players = make_two_player_game()
        players[1].owned_citizens.append(make_simple_citizen(101))

        active = game._player_by_id(players[0].player_id)
        game.domain_effects._prompt_take_owned_card(
            active,
            "Test Domain",
            {"kind": "citizen", "pick": "random", "optional": False},
        )

        self.assertEqual(game.action_required.get("action"), "choose_player")
        prc = game.pending_required_choice or {}
        opt_ids = [opt.get("player_id") for opt in (prc.get("options") or [])]
        self.assertEqual(opt_ids, [players[1].player_id])


class NonTakeOperatorsBypassImmunity(unittest.TestCase):
    """Banish / flip are different operators in the rule book; they are not
    covered by `immunity.take`."""

    def test_sunder_bay_banish_still_targets_immunity_take_holder(self):
        game, players = make_two_player_game()
        players[1].owned_citizens.append(make_simple_citizen(101))
        players[1].owned_domains.append(make_castle_of_the_seven_suns())

        game.payouts._execute_banish_player_citizen_payout(players[0].player_id)

        prc = game.pending_required_choice or {}
        opt_ids = [opt.get("player_id") for opt in (prc.get("options") or [])]
        self.assertIn(players[1].player_id, opt_ids,
                      "Banish (Sunder Bay) is a separate operator from `take`; "
                      "Castle must NOT block it.")

    def test_targeted_flip_still_targets_immunity_take_holder(self):
        game, players = make_two_player_game()
        players[1].owned_citizens.append(make_simple_citizen(101))
        players[1].owned_domains.append(make_castle_of_the_seven_suns())

        game.payouts._execute_flip_citizen_payout("flip_citizen targeted", players[0].player_id)

        prc = game.pending_required_choice or {}
        opt_ids = [opt.get("player_id") for opt in (prc.get("options") or [])]
        self.assertIn(players[1].player_id, opt_ids,
                      "Flip is a separate operator from `take`; Castle must NOT block it.")


if __name__ == "__main__":
    unittest.main()
