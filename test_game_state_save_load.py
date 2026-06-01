"""Round-trip tests for game state save/load helpers.

These tests build a small `Game` in memory (no DB) and verify that
`serialize_game_to_save_dict` followed by `deserialize_save_dict_to_game`
produces a Game whose own serialized form matches the original.
"""

import json
import unittest

from cards import Citizen, Domain, Duke, Event, Exhausted, Monster, Starter
from game import Game
from game_models import Player
from game_serialization import (
    deserialize_save_dict_to_game,
    serialize_game_to_save_dict,
)


def _starter(starter_id=1):
    return Starter(
        starter_id, f"Starter {starter_id}",
        1, 0,
        1, 0,
        0, 0,
        0, 0,
        False, False,
        "", "",
        "test",
        activation_trigger="",
    )


def _citizen(citizen_id=10, gold_cost=2, is_flipped=False):
    return Citizen(
        citizen_id, f"Citizen {citizen_id}",
        gold_cost,
        1, 0,
        0, 0, 0, 0,
        1, 1,
        0, 0,
        0, 0,
        0, 0,
        False, False,
        "", "",
        False, "test",
        is_flipped=is_flipped,
    )


def _domain(domain_id=20):
    return Domain(
        domain_id, f"Domain {domain_id}",
        4,
        0, 0, 0, 0,
        2,
        False, False,
        "", "",
        "",
        "test",
    )


def _monster(monster_id=30, area="A1", order=1):
    return Monster(
        monster_id, f"Monster {monster_id}",
        area, "Minion", order,
        2, 0,
        1, 1, 0, 0,
        False, "",
        False, "",
        False,
        "test",
    )


def _duke(duke_id=40):
    return Duke(
        duke_id, f"Duke {duke_id}",
        2, 0, 0,
        0, 0, 0, 0,
        0, 0, 0,
        0, 0, 0, 0,
        "test",
    )


def _event(event_id=50):
    return Event(
        event_id=event_id,
        name=f"Event {event_id}",
        roll_match1=7,
        roll_effect="",
        has_roll_effect=0,
        is_monster=0,
        has_activation_effect=0,
        has_passive_effect=0,
        activation_effect="",
        passive_effect="",
        strength_cost=1,
        magic_cost=0,
        monster_type="",
        vp_reward=0,
        gold_reward=0,
        strength_reward=0,
        magic_reward=0,
        has_special_reward=0,
        special_reward="",
        expansion="test",
    )


def _build_player(pid="p1", name="Alice"):
    p = Player(pid, name)
    p.owned_starters = [_starter(1), _starter(2)]
    p.owned_citizens = [_citizen(11), _citizen(12, is_flipped=True)]
    p.owned_domains = [_domain(21)]
    p.owned_dukes = [_duke(41)]
    p.owned_monsters = [_monster(31), _event(51)]
    p.gold_score = 5
    p.strength_score = 3
    p.magic_score = 2
    p.victory_score = 4
    p.is_first = True
    p.harvest_delta = {"gold": 1, "strength": 0, "magic": 0, "victory": 0}
    return p


def _build_game_with_rich_state():
    p1 = _build_player("p1", "Alice")
    p2 = _build_player("p2", "Bob")
    p2.is_first = False
    p2.gold_score = 0
    p2.victory_score = 0

    monster_grid = [
        [_monster(101, area="A1", order=2), _monster(102, area="A1", order=1)],
        [_monster(103, area="A2", order=1)],
    ]
    citizen_grid = [
        [_citizen(201)],
        [],
        [_citizen(202, is_flipped=True)],
    ]
    domain_grid = [
        [_domain(301)],
        [_domain(302)],
    ]

    game_state = {
        "game_id": "test-roundtrip-game",
        "debug_mode": True,
        "player_list": [p1, p2],
        "monster_grid": monster_grid,
        "monster_stack_areas": ["A1", "A2"],
        "citizen_grid": citizen_grid,
        "domain_grid": domain_grid,
        "die_one": 3,
        "die_two": 4,
        "die_sum": 7,
        "rolled_die_one": 2,
        "rolled_die_two": 4,
        "rolled_die_sum": 6,
        "roll_events": ["doubles"],
        "exhausted_count": 4,
        "exhausted_stack": [Exhausted(0), _event(401), Exhausted(1)],
        "banish_pile": [_citizen(501), _domain(502)],
        "pending_payout_continuation": {
            "player_id": "p1",
            "parts": ["gold +2", "strength +1"],
            "balance_hint": {"gold": 0, "strength": 0, "magic": 0},
        },
        "end_game_triggered": False,
        "final_scores": None,
        "final_result": None,
        "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
        "action_required": {"id": "p1", "action": "harvest_steal"},
        "concurrent_action": None,
        "tick_id": 12,
        "turn_number": 3,
        "turn_index": 1,
        "phase": "harvest",
        "actions_remaining": 1,
        "harvest_processed": False,
        "pending_harvest_choices": ["p2"],
        "harvest_player_order": ["p1", "p2"],
        "harvest_player_idx": 0,
        "harvest_consumed": {"p1": ["citizen:11"]},
        "_harvest_steal_phase_done": False,
        "pending_harvest_slays": [{"player_id": "p1", "source_label": "Citizen 11"}],
        "game_log": [
            {"text": "Game started.", "ts": 1000},
            {"text": "Alice rolled (3, 4) -> 7.", "ts": 1001},
        ],
        "pending_action_end_queue": [],
        "pending_required_choice": {
            "kind": "harvest_steal",
            "stage": "victim",
            "player_id": "p1",
            "victim_options": [
                {"victim_id": "p2", "victim_name": "Bob"},
            ],
            "resource_options": [{"resource": "gold", "amount": 1}],
            "options": [
                {"kind": "steal", "victim_id": "p2", "victim_name": "Bob",
                 "resource": "gold", "amount": 1}
            ],
        },
        "pending_roll": None,
        "pending_event_slay_cost": None,
    }
    return Game(game_state)


class GameStateRoundTripTests(unittest.TestCase):
    def test_roundtrip_preserves_serialized_form(self):
        game = _build_game_with_rich_state()
        snapshot = serialize_game_to_save_dict(game)

        # Cheap sanity check: the snapshot must already be JSON-roundtrippable.
        re_loaded = json.loads(json.dumps(snapshot))
        self.assertEqual(re_loaded, snapshot)

        # Rehydrate -> re-snapshot -> compare.
        rebuilt = deserialize_save_dict_to_game(snapshot)
        snapshot2 = serialize_game_to_save_dict(rebuilt)

        # Game-level comparison.
        self.assertEqual(snapshot2, snapshot)

    def test_rebuilt_game_basic_invariants(self):
        game = _build_game_with_rich_state()
        snapshot = serialize_game_to_save_dict(game)
        rebuilt = deserialize_save_dict_to_game(snapshot)

        self.assertEqual(rebuilt.game_id, "test-roundtrip-game")
        self.assertEqual(rebuilt.phase, "harvest")
        self.assertEqual(rebuilt.turn_number, 3)
        self.assertEqual(rebuilt.turn_index, 1)
        self.assertEqual(rebuilt.die_one, 3)
        self.assertEqual(rebuilt.die_two, 4)
        self.assertEqual(rebuilt.rolled_die_one, 2)
        self.assertTrue(rebuilt.debug_mode)
        self.assertEqual(rebuilt.monster_stack_areas, ["A1", "A2"])

        # Players are full-fat objects, not dicts.
        self.assertEqual(len(rebuilt.player_list), 2)
        p1 = rebuilt.player_list[0]
        self.assertIsInstance(p1, Player)
        self.assertEqual(p1.player_id, "p1")
        self.assertEqual(p1.gold_score, 5)
        self.assertTrue(p1.is_first)
        self.assertEqual(len(p1.owned_citizens), 2)
        self.assertIsInstance(p1.owned_citizens[0], Citizen)
        self.assertEqual(len(p1.owned_dukes), 1)
        self.assertIsInstance(p1.owned_dukes[0], Duke)
        self.assertEqual(len(p1.owned_monsters), 2)
        # owned_monsters mixes Monster + Event; Event must rehydrate as Event.
        kinds = sorted(type(c).__name__ for c in p1.owned_monsters)
        self.assertEqual(kinds, ["Event", "Monster"])

        # Grids are objects, not dicts.
        for stack in rebuilt.monster_grid:
            for c in stack:
                self.assertIsInstance(c, Monster)
        for stack in rebuilt.domain_grid:
            for c in stack:
                self.assertIsInstance(c, Domain)
        for stack in rebuilt.citizen_grid:
            for c in stack:
                self.assertIsInstance(c, Citizen)

        # banish_pile + exhausted_stack rehydrate by their card class.
        self.assertEqual(len(rebuilt.banish_pile), 2)
        ex = rebuilt.exhausted_stack
        self.assertEqual(len(ex), 3)
        self.assertEqual(sum(1 for c in ex if isinstance(c, Exhausted)), 2)
        self.assertEqual(sum(1 for c in ex if isinstance(c, Event)), 1)

        # Misc engine state survived.
        self.assertEqual(rebuilt.pending_harvest_choices, ["p2"])
        self.assertFalse(rebuilt.harvest_processed)
        self.assertEqual(
            rebuilt.pending_required_choice["kind"], "harvest_steal"
        )
        self.assertEqual(rebuilt.pending_payout_continuation["parts"], ["gold +2", "strength +1"])

    def test_save_format_version_is_present(self):
        game = _build_game_with_rich_state()
        snapshot = serialize_game_to_save_dict(game)
        self.assertEqual(snapshot.get("save_format_version"), 1)


if __name__ == "__main__":
    unittest.main()
