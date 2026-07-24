"""Turn-aware root priors: same-turn follow-up bonus and pair-prior wiring."""

import contextlib
import io
import unittest

import db_config
from agent import fake_db
from agent.mcts import MCTSPolicy, _move_key

_real_connect = db_config.connect


def setUpModule():
  fake_db.install()


def tearDownModule():
  db_config.connect = _real_connect


_SINK = io.StringIO()


def _action_game(seed):
  from agent.headless import acting_player_ids, advance, apply_move, legal_moves, new_game

  game = new_game(seed=seed)
  with contextlib.redirect_stdout(_SINK):
    for _ in range(50):
      if game.phase == "action":
        break
      moved = False
      for pid in acting_player_ids(game):
        moves = legal_moves(game, pid)
        if moves:
          apply_move(game, moves[0])
          moved = True
          break
      if not moved:
        advance(game)
  if game.phase != "action":
    return None
  pid = game.action_required["id"]
  return game, pid


def _take(pid, resource):
  return {"player_id": pid, "action_type": "take_resource", "resource": resource}


class TurnFollowUpBonusTests(unittest.TestCase):
  def setUp(self):
    self.policy = MCTSPolicy(iterations=1, turn_priors=True)

  def test_bonus_positive_when_second_action_remains(self):
    game, pid = _action_game(seed=5)
    self.assertEqual(int(game.actions_remaining), 2)
    bonus = self.policy._turn_follow_up_bonus(game, pid, _take(pid, "gold"))
    self.assertGreater(bonus, 0.0)

  def test_bonus_zero_on_last_action(self):
    from agent.headless import apply_move

    game, pid = _action_game(seed=5)
    with contextlib.redirect_stdout(_SINK):
      apply_move(game, _take(pid, "gold"))
    self.assertEqual(int(game.actions_remaining), 1)
    bonus = self.policy._turn_follow_up_bonus(game, pid, _take(pid, "magic"))
    self.assertEqual(bonus, 0.0)

  def test_slay_reward_gold_funds_follow_up(self):
    # A slay whose gold reward enables purchases must carry a bigger bonus
    # than the same slay with the reward zeroed out (the user-reported combo:
    # slay first, spend the reward on action two).
    from agent.headless import legal_moves

    for seed in range(1, 25):
      pack = _action_game(seed)
      if pack is None:
        continue
      game, pid = pack
      player = next(p for p in game.player_list if p.player_id == pid)
      player.gold_score, player.strength_score, player.magic_score = 0, 12, 0
      slays = [
        m for m in legal_moves(game, pid)
        if m.get("action_type") == "slay_monster" and m.get("monster_id") is not None
      ]
      for move in slays:
        card = next(
          (s[-1] for s in game.monster_grid
           if s and getattr(s[-1], "monster_id", None) == move["monster_id"]),
          None,
        )
        if card is None or int(getattr(card, "gold_reward", 0) or 0) < 1:
          continue
        with_reward = self.policy._turn_follow_up_bonus(game, pid, move)
        original = card.gold_reward
        try:
          card.gold_reward = 0
          without_reward = self.policy._turn_follow_up_bonus(game, pid, move)
        finally:
          card.gold_reward = original
        self.assertGreaterEqual(with_reward, without_reward)
        if with_reward > without_reward + 1e-9:
          return  # found a state where the reward demonstrably funds action two
    self.fail("no state found where slay reward gold changed the follow-up bonus")


class TurnPriorTests(unittest.TestCase):
  def test_turn_priors_are_a_distribution_over_legal_moves(self):
    from agent.headless import legal_moves

    game, pid = _action_game(seed=7)
    policy = MCTSPolicy(iterations=1, turn_priors=True)
    moves_by_key = {_move_key(m): m for m in legal_moves(game, pid)}
    priors = policy._compute_turn_priors(game, pid, moves_by_key)
    self.assertTrue(priors)
    self.assertTrue(set(priors) <= set(moves_by_key))
    self.assertAlmostEqual(sum(priors.values()), 1.0, places=6)

  def test_analyze_with_turn_priors_picks_legal_move(self):
    from agent.headless import legal_moves

    game, pid = _action_game(seed=7)
    policy = MCTSPolicy(iterations=24, turn_priors=True)
    moves = legal_moves(game, pid)
    with contextlib.redirect_stdout(_SINK):
      decision = policy.analyze(game, pid, moves)
    legal = {_move_key(m) for m in moves}
    self.assertIn(_move_key(decision["chosen"]), legal)


if __name__ == "__main__":
  unittest.main()
