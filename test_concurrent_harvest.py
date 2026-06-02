import json
import unittest

from cards import Citizen
from game import Game
from game_models import Player
from game_serialization import GameObjectEncoder


def make_exchange_citizen(citizen_id, special_cmd):
    """Citizen that always activates on harvest and offers an exchange."""
    return Citizen(
        citizen_id,
        f"Citizen {citizen_id}",
        0,   # gold_cost
        1, 0,  # roll_match1, roll_match2 (matches die_one=1)
        0, 0, 0, 0,  # shadow/holy/soldier/worker
        1, 1,  # gold_payout_on_turn/off_turn (ensures slot exists for on- and off-turn)
        0, 0,  # strength payout
        0, 0,  # magic payout
        0, 0,  # vp payout
        False, False,  # has_special_payout_on/off_turn
        special_cmd, special_cmd,  # special_payout_on_turn/off_turn (so everyone can prompt)
        False,  # special_citizen
        "test",  # expansion
    )


def make_game_for_test(players, game_id="test-game"):
    return Game({
        "game_id": game_id,
        "player_list": players,
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": game_id, "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "harvest",
    })


class ConcurrentHarvestTests(unittest.TestCase):
    def test_optional_exchange_concurrent_multiple_players(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        for p in (p1, p2):
            p.gold_score = 10
            p.owned_citizens.append(make_exchange_citizen(100, "exchange g 1 s 1"))

        game = make_game_for_test([p1, p2])
        game.advance_tick()

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca.get("kind"), "harvest_choices")

        prompts = ((ca.get("data") or {}).get("prompts") or {})
        self.assertIn(p1.player_id, prompts)
        self.assertIn(p2.player_id, prompts)

        self.assertEqual(set(ca.get("pending") or []), {p1.player_id, p2.player_id})

        cmd_other_before = prompts[p2.player_id]["pending_required_choice"]["command"]
        game.submit_concurrent_action(p1.player_id, "confirm_harvest_exchange", kind="harvest_choices")

        ca2 = game.concurrent_action
        self.assertIsNotNone(ca2)
        self.assertEqual(ca2.get("kind"), "harvest_choices")
        self.assertEqual(set(ca2.get("pending") or []), {p2.player_id})
        self.assertIn(p2.player_id, (ca2.get("data") or {}).get("prompts") or {})

        cmd_other_after = (ca2.get("data") or {}).get("prompts")[p2.player_id]["pending_required_choice"]["command"]
        self.assertEqual(cmd_other_before, cmd_other_after, "Other players' prompt must not be disturbed.")

    def test_optional_exchange_player_multi_prompt_redrains_into_pending(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        p1.gold_score = 10
        p2.gold_score = 10

        p1.owned_citizens.append(make_exchange_citizen(100, "exchange g 1 s 1"))
        p1.owned_citizens.append(make_exchange_citizen(101, "exchange g 2 s 1"))
        p2.owned_citizens.append(make_exchange_citizen(200, "exchange g 1 s 1"))

        game = make_game_for_test([p1, p2])
        game.advance_tick()

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca.get("kind"), "harvest_choices")

        prompts = ((ca.get("data") or {}).get("prompts") or {})
        p1_cmd_1 = prompts[p1.player_id]["pending_required_choice"]["command"]
        p2_cmd = prompts[p2.player_id]["pending_required_choice"]["command"]
        self.assertNotEqual(p1_cmd_1, "", "Expected a command in the first prompt snapshot.")

        game.submit_concurrent_action(p1.player_id, "confirm_harvest_exchange", kind="harvest_choices")

        ca2 = game.concurrent_action
        self.assertIsNotNone(ca2)

        pending = set(ca2.get("pending") or [])
        self.assertIn(p1.player_id, pending, "Player with a second prompt must stay pending.")
        self.assertIn(p2.player_id, pending, "Other participant remains pending.")

        prompts2 = ((ca2.get("data") or {}).get("prompts") or {})
        p1_cmd_2 = prompts2[p1.player_id]["pending_required_choice"]["command"]
        self.assertNotEqual(p1_cmd_1, p1_cmd_2, "After re-drain the same player should receive the next prompt payload.")
        self.assertEqual(prompts2[p2.player_id]["pending_required_choice"]["command"], p2_cmd)

    def test_finalize_bonus_is_concurrent(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        for p in (p1, p2):
            p.gold_score = 0
            p.owned_citizens = []

        game = make_game_for_test([p1, p2])
        game.advance_tick()

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca.get("kind"), "harvest_choices")
        self.assertEqual((ca.get("data") or {}).get("phase"), "finalize_bonus")
        self.assertEqual(set(ca.get("pending") or []), {p1.player_id, p2.player_id})

    def test_steal_phase_resolves_before_nonsteal_concurrent_gate(self):
        # Thief (p1) only has a steal citizen. The others have exchange citizens.
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        p3 = Player("p3", "Player 3")

        for p in (p2, p3):
            p.gold_score = 10
            p.owned_citizens.append(make_exchange_citizen(200 + int(p.player_id[-1]), "exchange g 1 s 1"))

        p1.gold_score = 0
        p1.owned_citizens.append(Citizen(
            900,
            "Thief Citizen",
            0,
            1, 0,
            0, 0, 0, 0,
            0, 0,
            0, 0,
            0, 0,
            0, 0,
            False, False,
            "steal g 1", "",
            False,
            "test",
        ))

        game = make_game_for_test([p1, p2, p3])
        game.advance_tick()

        self.assertIsNone(game.concurrent_action, "Concurrent harvest gate must not open before steal resolution.")
        self.assertEqual(game.action_required.get("action"), "harvest_steal")
        self.assertEqual(game.action_required.get("id"), p1.player_id)

        # Steal prompt stage is expected to ask for victim selection first.
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "harvest_steal")
        self.assertEqual(prc.get("stage"), "victim")

        game.act_on_required_action(p1.player_id, "steal_victim 1")

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca.get("kind"), "harvest_choices")
        self.assertEqual(set(ca.get("pending") or []), {p2.player_id, p3.player_id})

    def test_finalize_bonus_does_not_reopen_after_resolution(self):
        # Bug repro: when no player has a triggered starter/citizen, the
        # end-of-harvest bonus gate opens. After every player picks a free
        # resource, the gate previously cycled forever (handler.finalize
        # re-called _harvest_complete_finalize, which recomputed activated_pids
        # against an already-cleared harvest_consumed and re-opened the bonus
        # gate for everyone). Verify the gate clears once and the game
        # advances into the action phase.
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        for p in (p1, p2):
            p.gold_score = 0
            p.owned_citizens = []

        game = make_game_for_test([p1, p2])
        game.advance_tick()

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual((ca.get("data") or {}).get("phase"), "finalize_bonus")
        self.assertEqual(set(ca.get("pending") or []), {p1.player_id, p2.player_id})

        game.submit_concurrent_action(p1.player_id, "gold", kind="harvest_choices")
        game.submit_concurrent_action(p2.player_id, "gold", kind="harvest_choices")

        self.assertIsNone(
            game.concurrent_action,
            "Finalize bonus gate must clear after all players respond (not reopen).",
        )
        self.assertEqual(
            game.phase,
            "action",
            "Game should advance into the action phase after the bonus gate clears.",
        )
        self.assertEqual(game.action_required.get("action"), "standard_action")
        self.assertEqual(game.action_required.get("id"), p1.player_id)
        # Each player got exactly +1 gold — not double-applied by a re-opened gate.
        self.assertEqual(p1.gold_score, 1)
        self.assertEqual(p2.gold_score, 1)

    def test_ui_serialization_active_player_id_non_null(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        game = make_game_for_test([p1, p2], game_id="test-ui-1")
        state = json.loads(json.dumps(game, cls=GameObjectEncoder))

        self.assertIn("active_player_id", state)
        self.assertIsNotNone(state["active_player_id"])


if __name__ == "__main__":
    unittest.main()

