import unittest

from engines.available_actions import enumerate_actions


def _standard_action_state(player, citizen_grid=(), domain_grid=(), monster_grid=()):
  return {
    "preset": "base",
    "phase": "action",
    "actions_remaining": 2,
    "active_player_id": player["player_id"],
    "action_required": {"id": player["player_id"], "action": "standard_action"},
    "player_list": [player],
    "citizen_grid": list(citizen_grid),
    "domain_grid": list(domain_grid),
    "monster_grid": list(monster_grid),
  }


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

  def test_hire_enumerates_gold_magic_splits(self):
    # The turn-5 hint bug: 1 gold + 2 magic must see a 3-cost citizen
    # (magic is wild for gold, with at least 1 real gold in the payment).
    player = {"player_id": "p1", "gold_score": 1, "strength_score": 0, "magic_score": 2}
    citizen = [{"citizen_id": 11, "name": "Knight", "gold_cost": 3, "is_accessible": True}]
    moves = enumerate_actions(_standard_action_state(player, citizen_grid=[citizen]), "p1")
    hires = [m for m in moves if m.get("action_type") == "hire_citizen"]
    self.assertEqual(
      [m["payment"] for m in hires],
      [{"gold": 1, "strength": 0, "magic": 2}],
    )

  def test_hire_pure_gold_stays_lead_payment(self):
    player = {"player_id": "p1", "gold_score": 5, "strength_score": 0, "magic_score": 5}
    citizen = [{"citizen_id": 11, "name": "Knight", "gold_cost": 3, "is_accessible": True}]
    moves = enumerate_actions(_standard_action_state(player, citizen_grid=[citizen]), "p1")
    payments = [m["payment"] for m in moves if m.get("action_type") == "hire_citizen"]
    self.assertEqual(payments, [
      {"gold": 3, "strength": 0, "magic": 0},
      {"gold": 2, "strength": 0, "magic": 1},
      {"gold": 1, "strength": 0, "magic": 2},
    ])

  def test_hire_requires_one_real_gold_with_magic(self):
    # 0 gold + plenty of magic still cannot hire (engine's >=1 gold rule).
    player = {"player_id": "p1", "gold_score": 0, "strength_score": 0, "magic_score": 5}
    citizen = [{"citizen_id": 11, "name": "Knight", "gold_cost": 2, "is_accessible": True}]
    moves = enumerate_actions(_standard_action_state(player, citizen_grid=[citizen]), "p1")
    self.assertFalse(any(m.get("action_type") == "hire_citizen" for m in moves))

  def test_build_domain_enumerates_gold_magic_splits(self):
    player = {"player_id": "p1", "gold_score": 2, "strength_score": 0, "magic_score": 3}
    domain = [{"domain_id": 5, "gold_cost": 4, "is_visible": True, "is_accessible": True}]
    moves = enumerate_actions(_standard_action_state(player, domain_grid=[domain]), "p1")
    payments = [m["payment"] for m in moves if m.get("action_type") == "build_domain"]
    self.assertEqual(payments, [
      {"gold": 2, "strength": 0, "magic": 2},
      {"gold": 1, "strength": 0, "magic": 3},
    ])

  def test_slay_enumerates_wild_magic_splits(self):
    # Strength 4 monster, player has 2 strength + 3 magic: wild magic covers
    # the gap, but each payment keeps at least 1 real strength.
    player = {"player_id": "p1", "gold_score": 0, "strength_score": 2, "magic_score": 3}
    monster = [{"monster_id": 9, "strength_cost": 4, "magic_cost": 1, "is_accessible": True}]
    moves = enumerate_actions(_standard_action_state(player, monster_grid=[monster]), "p1")
    payments = [m["payment"] for m in moves if m.get("action_type") == "slay_monster"]
    self.assertEqual(payments, [
      {"gold": 0, "strength": 2, "magic": 3},
    ])

  def test_slay_wild_needs_one_real_strength(self):
    player = {"player_id": "p1", "gold_score": 0, "strength_score": 0, "magic_score": 6}
    monster = [{"monster_id": 9, "strength_cost": 2, "magic_cost": 0, "is_accessible": True}]
    moves = enumerate_actions(_standard_action_state(player, monster_grid=[monster]), "p1")
    self.assertFalse(any(m.get("action_type") == "slay_monster" for m in moves))

  def test_slay_max_strength_stays_lead_payment(self):
    player = {"player_id": "p1", "gold_score": 0, "strength_score": 3, "magic_score": 2}
    monster = [{"monster_id": 9, "strength_cost": 3, "magic_cost": 0, "is_accessible": True}]
    moves = enumerate_actions(_standard_action_state(player, monster_grid=[monster]), "p1")
    payments = [m["payment"] for m in moves if m.get("action_type") == "slay_monster"]
    self.assertEqual(payments, [
      {"gold": 0, "strength": 3, "magic": 0},
      {"gold": 0, "strength": 2, "magic": 1},
      {"gold": 0, "strength": 1, "magic": 2},
    ])

  def test_slay_payment_prompt_offers_wild_splits(self):
    state = {
      "phase": "action",
      "action_required": {"id": "p1", "action": "slay_monster_payment"},
      "pending_required_choice": {
        "gold_cost": 0,
        "strength_cost": 3,
        "magic_cost": 1,
      },
      "player_list": [{
        "player_id": "p1",
        "gold_score": 0,
        "strength_score": 1,
        "magic_score": 4,
      }],
    }
    actions = [m["action"] for m in enumerate_actions(state, "p1")]
    self.assertEqual(actions[0], "slay_pay 0 3 1")  # printed cost stays first
    self.assertIn("slay_pay 0 1 3", actions)
    self.assertEqual(actions[-1], "skip")

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
