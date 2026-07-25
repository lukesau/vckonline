"""Policy head: featurization, scoring, training convergence, MCTS wiring."""

import contextlib
import io
import unittest

import numpy as np

import db_config
from agent import fake_db

_real_connect = db_config.connect


def setUpModule():
  fake_db.install()


def tearDownModule():
  db_config.connect = _real_connect


_SINK = io.StringIO()


def _action_game(seed=7):
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
  pid = game.action_required["id"]
  from agent.headless import legal_moves as _lm
  return game, pid, _lm(game, pid)


class FeaturizeTests(unittest.TestCase):
  def test_decision_featurization_shapes(self):
    from agent.features import N_FEATURES
    from agent.policies import GreedyPolicy
    from agent.policy_net import N_MOVE_FEATURES, featurize_decision

    game, pid, moves = _action_game()
    self.assertGreater(len(moves), 2)
    state_vec, move_mat = featurize_decision(game, pid, moves, greedy=GreedyPolicy())
    self.assertEqual(state_vec.shape, (N_FEATURES,))
    self.assertEqual(move_mat.shape, (len(moves), N_MOVE_FEATURES))
    self.assertTrue(np.all(np.isfinite(move_mat)))
    # Different moves must featurize differently (at least somewhere).
    self.assertGreater(len({tuple(r) for r in move_mat.round(4).tolist()}), 1)


class TrainingTests(unittest.TestCase):
  def test_learns_synthetic_preference(self):
    # Target: always prefer the move whose first move-feature is 1.
    from agent.policy_net import PolicyNet

    rng = np.random.default_rng(0)
    n_dec, n_state, n_move = 300, 6, 4
    states, moves, targets, starts = [], [], [], [0]
    for _ in range(n_dec):
      k = int(rng.integers(2, 5))
      mm = rng.normal(size=(k, n_move)).astype(np.float32)
      winner = int(rng.integers(k))
      mm[:, 0] = 0.0
      mm[winner, 0] = 1.0
      t = np.zeros(k, dtype=np.float32)
      t[winner] = 1.0
      states.append(rng.normal(size=n_state).astype(np.float32))
      moves.append(mm)
      targets.append(t)
      starts.append(starts[-1] + k)
    net = PolicyNet(n_state=n_state, n_move=n_move, n_hidden=16, seed=1)
    logs = []
    net.train(np.stack(states), np.concatenate(moves), np.asarray(starts),
              np.concatenate(targets), epochs=30, batch_decisions=32,
              log=logs.append)
    top1 = float(logs[-1].split()[-1])
    self.assertGreater(top1, 0.9, f"failed to learn synthetic rule: {logs[-1]}")


class MctsWiringTests(unittest.TestCase):
  def test_policy_priors_are_distribution_and_search_runs(self):
    from agent.mcts import MCTSPolicy, _move_key

    game, pid, moves = _action_game()
    policy = MCTSPolicy(iterations=16, policy_path="agent/data/policy_smoke_model.npz")
    self.assertIsNotNone(policy._policy_net)
    keyed = {_move_key(m): m for m in moves}
    priors = policy._compute_priors(game, pid, keyed)
    self.assertTrue(priors)
    self.assertTrue(set(priors) <= set(keyed))
    self.assertAlmostEqual(sum(priors.values()), 1.0, places=5)
    with contextlib.redirect_stdout(_SINK):
      decision = policy.analyze(game, pid, moves)
    self.assertIn(_move_key(decision["chosen"]), set(keyed))

  def test_missing_policy_net_falls_back_to_greedy(self):
    from agent.mcts import MCTSPolicy, _move_key

    game, pid, moves = _action_game()
    policy = MCTSPolicy(iterations=4)
    self.assertIsNone(policy._policy_net)
    keyed = {_move_key(m): m for m in moves}
    priors = policy._compute_priors(game, pid, keyed)
    self.assertAlmostEqual(sum(priors.values()), 1.0, places=5)


if __name__ == "__main__":
  unittest.main()
