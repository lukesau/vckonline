"""Regression test for King Tower (domain 53) end-of-action prompt.

King Tower's passive (`action.end manipulate_resources mode=pay_to_player
gain=v:1 pay=m:1 optional=true`) prompts at the end of the owner's Action
Phase to optionally pay 1 Magic to another player for 1 VP.

The standard action handlers reach this prompt via
`finish_turn_if_no_actions_remaining()`. But when the owner's final action
opened a follow-up prompt (e.g. slaying Wendigo, whose `choose <citizens>`
reward asks the player to pick a citizen), resolving that reward resumes the
turn through `advance_tick()` instead. The action-phase-exhaustion branch of
`advance_tick` used to end the turn directly without running the end-of-action
domain sequence, so King Tower was silently skipped. These tests pin the fix.
"""

import unittest

from cards import Domain
from game import Game
from game_models import Player


def make_king_tower(domain_id=53):
    return Domain(
        domain_id, "King Tower",
        12,                      # gold_cost
        1, 1, 1, 1,              # role counts
        1,                       # vp_reward
        False, True,             # has_activation_effect, has_passive_effect
        "action.end manipulate_resources mode=pay_to_player gain=v:1 pay=m:1 optional=true",
        None,
        "At the end of your Action Phase, pay 1 Magic to a player to gain 1 VP.",
        "shadowvale",
    )


def make_two_player_game():
    p1 = Player("p1", "Player 1")
    p1.gold_score = 0
    p1.strength_score = 0
    p1.magic_score = 0
    p2 = Player("p2", "Player 2")
    p2.gold_score = 0
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


def _enter_idle_action_phase_with_no_actions(game, players):
    """Mirror the engine state right after a follow-up reward prompt resolves:
    action phase, no actions left, and an idle (non-blocking) action_required."""
    game.phase = "action"
    game.actions_remaining = 0
    game.action_required["id"] = game.game_id
    game.action_required["action"] = ""


class KingTowerActionEndResumeTests(unittest.TestCase):
    def test_advance_tick_opens_king_tower_prompt_before_ending_turn(self):
        game, players = make_two_player_game()
        players[0].owned_domains.append(make_king_tower())
        players[0].magic_score = 1
        _enter_idle_action_phase_with_no_actions(game, players)

        # Resuming through advance_tick (the path taken after resolving a
        # monster-slay citizen reward) must still open the King Tower prompt.
        game.advance_tick()

        self.assertEqual(game.phase, "action_end_pending")
        self.assertEqual(game.action_required.get("id"), players[0].player_id)
        self.assertEqual(game.action_required.get("action"), "choose_player")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "domain_manipulate_player")
        self.assertEqual(prc.get("item", {}).get("domain_name"), "King Tower")
        self.assertEqual(
            [o.get("player_id") for o in prc.get("options", [])],
            [players[1].player_id],
        )

    def test_advance_tick_ends_turn_when_owner_cannot_pay_magic(self):
        game, players = make_two_player_game()
        players[0].owned_domains.append(make_king_tower())
        players[0].magic_score = 0
        _enter_idle_action_phase_with_no_actions(game, players)

        start_turn = int(game.turn_number)
        game.advance_tick()

        # Unaffordable optional effect is skipped silently; the turn ends.
        self.assertNotEqual(game.phase, "action_end_pending")
        self.assertEqual(int(game.turn_number), start_turn + 1)

    def test_finish_turn_path_still_opens_prompt(self):
        game, players = make_two_player_game()
        players[0].owned_domains.append(make_king_tower())
        players[0].magic_score = 1
        game.phase = "action"
        game.actions_remaining = 0
        game.action_required["id"] = players[0].player_id
        game.action_required["action"] = "standard_action"

        game.finish_turn_if_no_actions_remaining()

        self.assertEqual(game.phase, "action_end_pending")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "domain_manipulate_player")
        self.assertEqual(prc.get("item", {}).get("domain_name"), "King Tower")


if __name__ == "__main__":
    unittest.main()
