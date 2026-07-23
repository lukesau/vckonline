"""Sequential-halving parallel search: partitioning and end-to-end analyze."""

import contextlib
import io
import unittest

import db_config
from agent import fake_db
from agent.mcts import MCTSPolicy, _move_key, _parallel_worker

_real_connect = db_config.connect


def setUpModule():
  fake_db.install()


def tearDownModule():
  db_config.connect = _real_connect


_SINK = io.StringIO()


class _FakePool:
  """Runs worker payloads in-process (unit tests must not spawn processes)."""

  def map(self, fn, payloads):
    return [fn(p) for p in list(payloads)]

  def shutdown(self, *args, **kwargs):
    pass


class PartitionTests(unittest.TestCase):
  def test_disjoint_cover_and_balance(self):
    priors = {"a": 0.5, "b": 0.3, "c": 0.1, "d": 0.1}
    buckets = MCTSPolicy._partition_by_prior(list(priors), priors, 2)
    self.assertEqual(sorted(k for b in buckets for k in b), ["a", "b", "c", "d"])
    self.assertEqual(len(buckets), 2)
    # Heaviest key sits alone; the rest balance into the other bucket.
    self.assertIn(["a"], buckets)

  def test_buckets_capped_by_key_count(self):
    priors = {"a": 0.6, "b": 0.4}
    buckets = MCTSPolicy._partition_by_prior(list(priors), priors, 8)
    self.assertEqual(len(buckets), 2)


class HalvingSearchTests(unittest.TestCase):
  def _action_game(self):
    from agent.headless import acting_player_ids, advance, apply_move, legal_moves, new_game

    game = new_game(seed=9)
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
    self.assertEqual(game.phase, "action")
    pid = game.action_required["id"]
    return game, pid, legal_moves(game, pid)

  def test_halving_analyze_picks_a_legal_move(self):
    game, pid, moves = self._action_game()
    self.assertGreater(len(moves), 2)
    policy = MCTSPolicy(iterations=48, workers=4, parallel_mode="halving")
    policy._pool = _FakePool()
    with contextlib.redirect_stdout(_SINK):
      decision = policy.analyze(game, pid, moves)
    legal_keys = {_move_key(m) for m in moves}
    self.assertIn(_move_key(decision["chosen"]), legal_keys)
    candidates = decision["candidates"]
    self.assertTrue(candidates)
    for entry in candidates:
      self.assertIn(_move_key(entry["move"]), legal_keys)
    # The top candidate must carry phase-2 verification visits.
    self.assertGreater(candidates[0]["visits"], 0)

  def test_halving_mode_default_stays_root(self):
    policy = MCTSPolicy(iterations=10, workers=4)
    self.assertEqual(policy.parallel_mode, "root")
    policy = MCTSPolicy(iterations=10, workers=4, parallel_mode="nonsense")
    self.assertEqual(policy.parallel_mode, "root")


if __name__ == "__main__":
  unittest.main()
