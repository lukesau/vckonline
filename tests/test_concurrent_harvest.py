import json
import unittest

from cards import Citizen, Starter
from game import Game
from game_models import Player
from game_serialization import GameObjectEncoder


def make_herald_starter(starter_id):
    """Herald: a -1/-1 starter whose no_payout/doubles leg is `choose g 1 s 1 m 1`.

    Matches the shipped Herald row — the end-of-harvest leg opens an
    interactive `choose` prompt rather than any hardcoded default.
    """
    return Starter(
        starter_id, "Herald", -1, -1,
        0, 0,
        0, 0, 0, 0,
        True, True, "choose g 1 s 1 m 1", "choose g 1 s 1 m 1",
        "test",
        "doubles_or_no_payout_twice",
    )


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
        True, True,  # has_special_payout_on/off_turn
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
        # Each player's payouts are now presented as a list (all at once).
        self.assertIsInstance(prompts[p1.player_id], list)
        self.assertEqual(len(prompts[p1.player_id]), 1)

        self.assertEqual(set(ca.get("pending") or []), {p1.player_id, p2.player_id})

        cmd_other_before = prompts[p2.player_id][0]["pending_required_choice"]["command"]
        # No prompt id supplied -> resolves the player's first pending payout.
        game.submit_concurrent_action(p1.player_id, "confirm_harvest_exchange", kind="harvest_choices")

        ca2 = game.concurrent_action
        self.assertIsNotNone(ca2)
        self.assertEqual(ca2.get("kind"), "harvest_choices")
        self.assertEqual(set(ca2.get("pending") or []), {p2.player_id})
        self.assertIn(p2.player_id, (ca2.get("data") or {}).get("prompts") or {})

        cmd_other_after = (ca2.get("data") or {}).get("prompts")[p2.player_id][0]["pending_required_choice"]["command"]
        self.assertEqual(cmd_other_before, cmd_other_after, "Other players' prompt must not be disturbed.")

    def test_optional_exchange_player_multi_prompt_listed_all_at_once(self):
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
        # Both of p1's payouts are presented up front so they can choose order.
        self.assertEqual(len(prompts[p1.player_id]), 2)
        self.assertEqual(len(prompts[p2.player_id]), 1)
        p1_cmds = {e["pending_required_choice"]["command"] for e in prompts[p1.player_id]}
        self.assertEqual(p1_cmds, {"exchange g 1 s 1", "exchange g 2 s 1"})
        p2_cmd = prompts[p2.player_id][0]["pending_required_choice"]["command"]

        # Resolve p1's *second* listed payout first (order is the player's choice).
        target = prompts[p1.player_id][1]
        game.submit_concurrent_action(
            p1.player_id, f"{target['id']}|confirm_harvest_exchange", kind="harvest_choices"
        )

        ca2 = game.concurrent_action
        self.assertIsNotNone(ca2)

        pending = set(ca2.get("pending") or [])
        self.assertIn(p1.player_id, pending, "Player with a remaining payout stays pending.")
        self.assertIn(p2.player_id, pending, "Other participant remains pending.")

        prompts2 = ((ca2.get("data") or {}).get("prompts") or {})
        self.assertEqual(len(prompts2[p1.player_id]), 1, "Resolved payout is removed from the list.")
        remaining = prompts2[p1.player_id][0]["pending_required_choice"]["command"]
        self.assertEqual(remaining, "exchange g 1 s 1", "Unresolved payout still pending.")
        self.assertEqual(prompts2[p2.player_id][0]["pending_required_choice"]["command"], p2_cmd)

    def test_finalize_bonus_is_concurrent(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        for p in (p1, p2):
            p.gold_score = 0
            p.owned_citizens = []
            # Only a no_payout starter (Herald) drives the end-of-harvest leg.
            p.owned_starters.append(make_herald_starter(300 + int(p.player_id[1:])))

        game = make_game_for_test([p1, p2])
        game.advance_tick()

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca.get("kind"), "harvest_choices")
        self.assertEqual((ca.get("data") or {}).get("phase"), "finalize_bonus")
        self.assertEqual(set(ca.get("pending") or []), {p1.player_id, p2.player_id})
        prompts = ((ca.get("data") or {}).get("prompts") or {})
        for pid in (p1.player_id, p2.player_id):
            self.assertEqual(prompts[pid][0]["sub_kind"], "harvest_choose")

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
            True, False,  # has_special_payout_on/off_turn (on-turn steal)
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
        # Bug repro: when players own a no_payout starter (Herald) and nothing
        # else triggers, the end-of-harvest leg opens a concurrent `choose`
        # gate. After every player resolves it, the gate previously cycled
        # forever (handler.finalize re-called _harvest_complete_finalize, which
        # recomputed activated_pids against an already-cleared harvest_consumed
        # and re-opened the gate for everyone). Verify the gate clears once and
        # the game advances into the action phase.
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        for p in (p1, p2):
            p.gold_score = 0
            p.owned_citizens = []
            p.owned_starters.append(make_herald_starter(300 + int(p.player_id[1:])))

        game = make_game_for_test([p1, p2])
        game.advance_tick()

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual((ca.get("data") or {}).get("phase"), "finalize_bonus")
        self.assertEqual(set(ca.get("pending") or []), {p1.player_id, p2.player_id})

        # Each Herald's `choose g 1 s 1 m 1`: option 1 is +1 gold.
        game.submit_concurrent_action(p1.player_id, "choose 1", kind="harvest_choices")
        game.submit_concurrent_action(p2.player_id, "choose 1", kind="harvest_choices")

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

    def test_wild_gain_exchange_skip_concurrent(self):
        # Sorceress-style payout: `exchange m 1 wild 2`. Skipping must leave
        # the wild exchange's resources untouched (no magic spent, no wild
        # gain) and clear the concurrent gate. The citizen's printed
        # `gold_payout_*=1` still applies — only the *special* exchange is
        # the optional bit being skipped.
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        for p in (p1, p2):
            p.gold_score = 0
            p.strength_score = 0
            p.magic_score = 3
            p.owned_citizens.append(make_exchange_citizen(100, "exchange m 1 wild 2"))

        game = make_game_for_test([p1, p2])
        game.advance_tick()

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca.get("kind"), "harvest_choices")
        prompts = ((ca.get("data") or {}).get("prompts") or {})
        for pid in (p1.player_id, p2.player_id):
            self.assertEqual(prompts[pid][0]["sub_kind"], "harvest_wild_gain_exchange")

        for pid in (p1.player_id, p2.player_id):
            game.submit_concurrent_action(pid, "skip_harvest_exchange", kind="harvest_choices")

        self.assertIsNone(
            game.concurrent_action,
            "Wild-gain exchange gate must clear once every player skips.",
        )
        for p in (p1, p2):
            self.assertEqual(p.gold_score, 1, "Printed gold payout still applies.")
            self.assertEqual(p.strength_score, 0)
            self.assertEqual(p.magic_score, 3, "Magic must not be deducted on skip.")
            self.assertEqual(p.harvest_delta.get("magic", 0), 0)

    def test_wild_cost_exchange_skip_concurrent(self):
        # Bogatyr-style payout: `exchange wild 1 s 4`. Skipping must leave
        # the wild exchange's resources untouched (nothing paid, no strength
        # gained) and clear the concurrent gate. The citizen's printed
        # `gold_payout_*=1` still applies.
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        for p in (p1, p2):
            p.gold_score = 2
            p.strength_score = 0
            p.magic_score = 2
            p.owned_citizens.append(make_exchange_citizen(100, "exchange wild 1 s 4"))

        game = make_game_for_test([p1, p2])
        game.advance_tick()

        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca.get("kind"), "harvest_choices")
        prompts = ((ca.get("data") or {}).get("prompts") or {})
        for pid in (p1.player_id, p2.player_id):
            self.assertEqual(prompts[pid][0]["sub_kind"], "harvest_wild_cost_exchange")

        for pid in (p1.player_id, p2.player_id):
            game.submit_concurrent_action(pid, "skip_harvest_exchange", kind="harvest_choices")

        self.assertIsNone(
            game.concurrent_action,
            "Wild-cost exchange gate must clear once every player skips.",
        )
        for p in (p1, p2):
            self.assertEqual(p.gold_score, 3, "Starts at 2, +1 from printed gold payout, nothing paid on skip.")
            self.assertEqual(p.strength_score, 0, "Strength must not be granted on skip.")
            self.assertEqual(p.magic_score, 2, "Magic must not be deducted on skip.")
            self.assertEqual(p.harvest_delta.get("strength", 0), 0)

    def test_ui_serialization_active_player_id_non_null(self):
        p1 = Player("p1", "Player 1")
        p2 = Player("p2", "Player 2")
        game = make_game_for_test([p1, p2], game_id="test-ui-1")
        state = json.loads(json.dumps(game, cls=GameObjectEncoder))

        self.assertIn("active_player_id", state)
        self.assertIsNotNone(state["active_player_id"])


if __name__ == "__main__":
    unittest.main()

