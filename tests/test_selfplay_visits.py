"""Self-play visit recording: decision records carry policy-head targets."""

import unittest

from agent.move_summary import move_key
from agent.selfplay import play_selfplay_game


class RecordVisitsTests(unittest.TestCase):
  def test_decision_records_have_visit_distributions(self):
    result = play_selfplay_game(
      seed=3, policy_name="mcts-nn", iterations=4,
      collect_states=True, record_visits=True,
    )
    self.assertIsNotNone(result, "self-play game failed to finish")
    samples, game = result
    self.assertEqual(game.phase, "game_over")
    self.assertTrue(samples, "no samples recorded")

    decisions = [payload for payload, tag in samples if tag == "decision"]
    self.assertEqual(len(decisions), len(samples), "periodic sampling should be off")
    self.assertGreater(len(decisions), 10)
    for rec in decisions[:20]:
      self.assertIn("state", rec)
      self.assertTrue(rec["to_move"])
      self.assertTrue(rec["visit_counts"])
      total = sum(v for _, v in rec["visit_counts"])
      self.assertGreater(total, 0)
      keys = {move_key(m) for m, _ in rec["visit_counts"]}
      self.assertIn(move_key(rec["chosen"]), keys)

  def test_plain_mode_unchanged(self):
    result = play_selfplay_game(
      seed=3, policy_name="greedy", collect_states=True, record_visits=True,
    )
    self.assertIsNotNone(result)
    samples, _ = result
    # record_visits is ignored for greedy: periodic plain states only.
    self.assertTrue(all(tag is None for _, tag in samples))


if __name__ == "__main__":
  unittest.main()
