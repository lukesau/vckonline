"""MCTS prior pruning: top_k counts distinct effects, not payment splits."""

import unittest

from agent.mcts import MCTSPolicy, _move_key


class _StubGreedy:
  def __init__(self, values):
    self._values = values

  def move_values(self, sim, pid, moves):
    return [self._values[_move_key(m)] for m in moves]


def _hire(cid, gold, magic):
  return {
    "player_id": "p1",
    "action_type": "hire_citizen",
    "citizen_id": cid,
    "payment": {"gold": gold, "strength": 0, "magic": magic},
  }


class EffectGroupedTopKTests(unittest.TestCase):
  def _priors(self, moves, values, top_k):
    policy = MCTSPolicy(iterations=1, top_k=top_k)
    keyed = {_move_key(m): m for m in moves}
    policy._greedy = _StubGreedy({
      _move_key(m): v for m, v in zip(moves, values)
    })
    return policy._compute_priors(None, "p1", keyed), keyed

  def test_payment_splits_share_one_topk_slot(self):
    hire_a1, hire_a2 = _hire(1, 3, 0), _hire(1, 2, 1)
    hire_b1, hire_b2 = _hire(2, 2, 0), _hire(2, 1, 1)
    take = {"player_id": "p1", "action_type": "take_resource", "resource": "gold"}
    moves = [hire_a1, hire_a2, hire_b1, hire_b2, take]
    values = [10.0, 9.9, 9.5, 9.4, 9.0]

    priors, _ = self._priors(moves, values, top_k=2)

    # Two effect groups kept (both hires, all their splits); take_resource
    # is the 3rd distinct effect and falls outside top_k=2.
    kept = set(priors)
    self.assertEqual(kept, {
      _move_key(hire_a1), _move_key(hire_a2),
      _move_key(hire_b1), _move_key(hire_b2),
    })
    self.assertAlmostEqual(sum(priors.values()), 1.0)

  def test_distinct_effects_still_pruned_to_topk(self):
    moves = [
      {"player_id": "p1", "action_type": "take_resource", "resource": r}
      for r in ("gold", "strength", "magic")
    ]
    priors, _ = self._priors(moves, [3.0, 2.0, 1.0], top_k=2)
    self.assertEqual(len(priors), 2)
    self.assertNotIn(_move_key(moves[2]), priors)


if __name__ == "__main__":
  unittest.main()
