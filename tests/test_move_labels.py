"""Human-readable hint labels for prompt/concurrent moves (name the target,
don't show raw indexes)."""

import unittest
from types import SimpleNamespace as NS

from agent.move_summary import move_label


def _game(**kw):
  base = {
    "pending_required_choice": {},
    "action_required": {"id": "p1", "action": ""},
    "player_list": [],
    "citizen_grid": [],
    "concurrent_action": {},
  }
  base.update(kw)
  return NS(**base)


def _prompt(action):
  return {"player_id": "p1", "action_type": "act_on_required_action", "action": action}


def _concurrent(kind, response):
  return {
    "player_id": "p1",
    "action_type": "submit_concurrent_action",
    "kind": kind,
    "response": response,
  }


class PromptLabelTests(unittest.TestCase):
  def test_choose_index_names_the_option(self):
    game = _game(
      pending_required_choice={"options": [{"name": "Fire Temple"}, {"name": "Skerry"}]},
      action_required={"id": "p1", "action": "choose_domain_reward"},
    )
    self.assertEqual(move_label(_prompt("choose 2"), game), "choose Skerry")

  def test_resource_choice_names_amount_and_resource(self):
    game = _game(pending_required_choice={"choices": [["g", 2], ["v", 1]]})
    self.assertEqual(move_label(_prompt("choose 1"), game), "choose 2 gold")
    self.assertEqual(move_label(_prompt("choose 2"), game), "choose 1 VP")

  def test_banish_owned_citizen_names_the_citizen(self):
    game = _game(
      pending_required_choice={"verb": "banish_owned_citizen", "owned_options": [1]},
      player_list=[NS(player_id="p1", owned_citizens=[NS(name="Peasant"), NS(name="Cleric")])],
    )
    self.assertEqual(move_label(_prompt("1"), game), "banish Cleric")

  def test_steal_victim_names_the_player(self):
    game = _game(
      pending_required_choice={"victim_options": [{"victim_name": "Lukesau"}]},
    )
    self.assertEqual(move_label(_prompt("steal_victim 1"), game), "steal from Lukesau")

  def test_wild_gain_names_resource(self):
    self.assertEqual(move_label(_prompt("wild_gain_resource m"), _game()), "gain 1 magic")

  def test_slay_pay_spells_out_payment(self):
    self.assertEqual(
      move_label(_prompt("slay_pay 0 2 1"), _game()),
      "slay: pay 2 strength + 1 magic",
    )

  def test_unknown_prompt_falls_back_to_raw(self):
    self.assertEqual(move_label(_prompt("mystery_verb 9"), _game()), "prompt: mystery_verb 9")


class ConcurrentLabelTests(unittest.TestCase):
  def test_choose_duke_names_the_duke(self):
    game = _game(player_list=[
      NS(player_id="p1", owned_dukes=[NS(duke_id=14, name="Duke Ilsban")]),
    ])
    self.assertEqual(move_label(_concurrent("choose_duke", "14"), game), "choose duke Duke Ilsban")

  def test_flip_one_citizen_names_the_citizen(self):
    game = _game(player_list=[
      NS(player_id="p1", owned_citizens=[NS(name="Knight"), NS(name="Miner")]),
    ])
    self.assertEqual(move_label(_concurrent("flip_one_citizen", "0"), game), "flip Knight")

  def test_harvest_take_resource_named(self):
    self.assertEqual(
      move_label(_concurrent("harvest_choices", "hp1|gold"), _game()),
      "take gold",
    )

  def test_harvest_sub_prompt_resolved(self):
    self.assertEqual(
      move_label(_concurrent("harvest_choices", "hp1|wild_gain_resource s"), _game()),
      "gain 1 strength",
    )

  def test_concurrent_fallback_keeps_kind_prefix(self):
    self.assertEqual(
      move_label(_concurrent("odd_kind", "42"), _game()),
      "odd_kind: 42",
    )


if __name__ == "__main__":
  unittest.main()
