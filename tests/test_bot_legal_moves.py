import unittest

from bots.legal_moves import enumerate_actions


class TestBotLegalMoves(unittest.TestCase):
  def test_standard_action_includes_take_resource(self):
    state = {
      "preset": "base",
      "phase": "action",
      "actions_remaining": 2,
      "action_required": {"id": "p1", "action": "standard_action"},
      "player_list": [{
        "player_id": "p1",
        "gold_score": 5,
        "strength_score": 5,
        "magic_score": 5,
      }],
      "citizen_grid": [],
      "domain_grid": [],
      "monster_grid": [],
    }
    moves = enumerate_actions(state, "p1")
    take = [m for m in moves if m.get("action_type") == "take_resource"]
    self.assertEqual(len(take), 3)
    resources = {m["resource"] for m in take}
    self.assertEqual(resources, {"gold", "strength", "magic"})

  def test_crimson_seas_take_resource_includes_map(self):
    state = {
      "preset": "crimsonseas",
      "phase": "action",
      "actions_remaining": 2,
      "active_player_id": "p1",
      "action_required": {"id": "p1", "action": "standard_action"},
      "player_list": [{"player_id": "p1"}],
      "citizen_grid": [],
      "domain_grid": [],
      "monster_grid": [],
    }
    moves = enumerate_actions(state, "p1")
    resources = {
      m["resource"] for m in moves
      if m.get("action_type") == "take_resource"
    }
    self.assertEqual(resources, {"gold", "strength", "magic", "map"})

  def test_standard_action_not_my_turn(self):
    state = {
      "phase": "action",
      "actions_remaining": 2,
      "action_required": {"id": "p2", "action": "standard_action"},
      "player_list": [],
    }
    self.assertEqual(enumerate_actions(state, "p1"), [])

  def test_concurrent_choose_duke(self):
    state = {
      "phase": "setup",
      "concurrent_action": {
        "kind": "choose_duke",
        "pending": ["p1"],
      },
      "player_list": [{
        "player_id": "p1",
        "owned_dukes": [
          {"duke_id": 3, "name": "Duke A"},
          {"duke_id": 7, "name": "Duke B"},
        ],
      }],
    }
    moves = enumerate_actions(state, "p1")
    self.assertEqual(len(moves), 2)
    for m in moves:
      self.assertEqual(m["action_type"], "submit_concurrent_action")
      self.assertEqual(m["kind"], "choose_duke")
    responses = {m["response"] for m in moves}
    self.assertEqual(responses, {"3", "7"})

  def test_choose_monster_slay_options(self):
    state = {
      "phase": "action",
      "action_required": {"id": "p1", "action": "choose_monster_slay"},
      "pending_required_choice": {
        "options": [
          {"name": "Goblin", "monster_id": 1},
          {"name": "Orc", "monster_id": 2},
        ],
      },
      "player_list": [{"player_id": "p1"}],
    }
    moves = enumerate_actions(state, "p1")
    actions = [m["action"] for m in moves if m.get("action_type") == "act_on_required_action"]
    self.assertIn("choose_monster_slay 1", actions)
    self.assertIn("choose_monster_slay 2", actions)
    self.assertIn("skip", actions)

  def test_finalize_roll(self):
    state = {
      "phase": "roll_pending",
      "action_required": {"id": "p1", "action": "finalize_roll"},
      "player_list": [{"player_id": "p1"}],
    }
    moves = enumerate_actions(state, "p1")
    self.assertEqual(len(moves), 1)
    self.assertEqual(moves[0]["action_type"], "finalize_roll")

  def test_concurrent_blocks_standard_action(self):
    state = {
      "phase": "action",
      "actions_remaining": 2,
      "action_required": {"id": "p1", "action": "standard_action"},
      "concurrent_action": {
        "kind": "harvest_choices",
        "pending": ["p1"],
        "data": {
          "prompts": {
            "p1": [{
              "id": "hp1",
              "sub_kind": "bonus_resource_choice",
            }],
          },
        },
      },
      "player_list": [{"player_id": "p1"}],
    }
    moves = enumerate_actions(state, "p1")
    self.assertTrue(all(m.get("action_type") == "submit_concurrent_action" for m in moves))
    self.assertFalse(any(m.get("action_type") == "take_resource" for m in moves))

  def test_harvest_steal_victim_stage(self):
    state = {
      "phase": "harvest",
      "action_required": {"id": "p1", "action": "harvest_steal"},
      "pending_required_choice": {
        "stage": "victim",
        "victim_options": [{"victim_id": "p2", "victim_name": "Opponent"}],
      },
      "player_list": [{"player_id": "p1"}],
    }
    moves = enumerate_actions(state, "p1")
    self.assertEqual(moves[0]["action"], "steal_victim 1")

  def test_domain_prompt_verbs_match_engine_handlers(self):
    cases = (
      ("choose_domain_to_build", "build_domain_pick", True),
      ("choose_domain_reward", "grant_domain", False),
      ("choose_monster_strength", "choose_monster", False),
    )
    for required, verb, has_skip in cases:
      with self.subTest(required=required):
        state = {
          "phase": "action",
          "action_required": {"id": "p1", "action": required},
          "pending_required_choice": {"options": [{}, {}]},
          "player_list": [{"player_id": "p1"}],
        }
        moves = enumerate_actions(state, "p1")
        actions = {m["action"] for m in moves}
        expected = {f"{verb} 1", f"{verb} 2"}
        if has_skip:
          expected.add("skip")
        self.assertEqual(actions, expected)

  def test_domain_self_convert_uses_confirm_verb(self):
    state = {
      "phase": "action",
      "action_required": {"id": "p1", "action": "domain_self_convert"},
      "pending_required_choice": {"kind": "domain_self_convert"},
      "player_list": [{"player_id": "p1"}],
    }
    actions = {m["action"] for m in enumerate_actions(state, "p1")}
    self.assertEqual(actions, {"confirm_self_convert", "skip"})

  def test_domain_choose_resource_uses_choice_indices(self):
    state = {
      "phase": "action",
      "action_required": {"id": "p1", "action": "domain_choose_resource"},
      "pending_required_choice": {
        "kind": "domain_choose_resource",
        "choices": [["g", 2], ["v", 1]],
      },
      "player_list": [{"player_id": "p1"}],
    }
    actions = {m["action"] for m in enumerate_actions(state, "p1")}
    self.assertEqual(actions, {"choose 1", "choose 2"})

  def test_domain_build_payment_uses_available_resources_and_tomes(self):
    state = {
      "phase": "action",
      "action_required": {"id": "p1", "action": "build_domain_payment"},
      "pending_required_choice": {"gold_cost": 3},
      "player_list": [{
        "player_id": "p1",
        "gold_score": 1,
        "magic_score": 1,
        "owned_tomes": [
          {"tome_type": "gold", "is_flipped": False},
          {"tome_type": "magic", "is_flipped": True},
        ],
      }],
    }
    actions = {m["action"] for m in enumerate_actions(state, "p1")}
    self.assertIn("build_pay 2 1 1 0 0", actions)
    self.assertIn("skip", actions)
    self.assertNotIn("build_pay 3 0 0 0 0", actions)

  def test_bonus_take_one_resource_choice(self):
    state = {
      "phase": "harvest",
      "action_required": {"id": "p1", "action": "bonus_resource_choice"},
      "player_list": [{"player_id": "p1"}],
    }
    actions = {m["action"] for m in enumerate_actions(state, "p1")}
    self.assertEqual(actions, {"gold", "strength", "magic"})

  def test_event_sequence_uses_filtered_prompt_options(self):
    cases = (
      (
        {
          "verb": "banish_center_citizen",
          "stack_options": [1, 4],
        },
        {"1", "4"},
      ),
      (
        {
          "verb": "banish_owned_citizen",
          "owned_options": [2],
          "mandatory": False,
        },
        {"2", "skip"},
      ),
      (
        {
          "verb": "place_reserve_monster",
          "placement_options": [
            {"grid": "monster", "idx": 2},
            {"grid": "domain", "idx": 1},
          ],
        },
        {"place monster 2", "place domain 1"},
      ),
    )
    for prompt, expected in cases:
      with self.subTest(verb=prompt["verb"]):
        state = {
          "phase": "action",
          "action_required": {"id": "p1", "action": "event_sequence"},
          "pending_required_choice": prompt,
          "player_list": [{"player_id": "p1"}],
        }
        actions = {m["action"] for m in enumerate_actions(state, "p1")}
        self.assertEqual(actions, expected)

  def test_orphaned_event_slay_cost_still_enumerates(self):
    state = {
      "phase": "harvest",
      "game_id": "game-1",
      "action_required": {"id": "game-1", "action": ""},
      "pending_event_slay_cost": {"player_id": "p1", "resource": "m", "amount": 1},
      "player_list": [{"player_id": "p1"}],
      "monster_grid": [[{
        "monster_id": 9,
        "is_accessible": True,
      }]],
    }
    moves = enumerate_actions(state, "p1")
    self.assertEqual(len(moves), 1)
    self.assertEqual(moves[0].get("_route"), "apply_event_slay_cost")
    self.assertEqual(moves[0].get("monster_id"), 9)

  def test_game_over_returns_empty(self):
    state = {"phase": "game_over", "player_list": []}
    self.assertEqual(enumerate_actions(state, "p1"), [])


if __name__ == "__main__":
  unittest.main()
