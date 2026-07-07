import unittest

from bots.legal_moves import enumerate_actions


class TestBotLegalMoves(unittest.TestCase):
  def test_standard_action_includes_take_resource(self):
    state = {
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
    self.assertEqual(len(take), 4)
    resources = {m["resource"] for m in take}
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

  def test_game_over_returns_empty(self):
    state = {"phase": "game_over", "player_list": []}
    self.assertEqual(enumerate_actions(state, "p1"), [])


if __name__ == "__main__":
  unittest.main()
