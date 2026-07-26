"""Greedy's `count owned_<role>` valuation must mirror engine fix 7bc2362:
face-up citizen pips only — domain/noble pips and flipped citizens excluded."""

import unittest
from types import SimpleNamespace as NS

from agent.policies import GreedyPolicy


def _player(citizens):
  return NS(
    owned_citizens=citizens,
    owned_domains=[],
    owned_starters=[],
    # calc_roles inflates worker pips the way domains/nobles used to: if the
    # valuation consults it for role harvest verbs, the test fails.
    calc_roles=lambda: {"shadow_count": 9, "holy_count": 9, "soldier_count": 9, "worker_count": 9},
  )


class RoleCountPayoutTests(unittest.TestCase):
  def setUp(self):
    self.greedy = GreedyPolicy()
    self.rates = {"g": 1.0, "s": 1.0, "m": 1.0, "v": 1.0, "p": 0.3}

  def test_counts_faceup_citizen_pips_only(self):
    player = _player([
      NS(worker_count=2, is_flipped=False),
      NS(worker_count=1, is_flipped=True),   # flipped: excluded
      NS(worker_count=1, is_flipped=False),
    ])
    value = self.greedy._payout_value("count owned_worker g 2", self.rates, player)
    self.assertAlmostEqual(value, 3 * 2.0)  # 3 face-up pips x 2g, NOT 9 x 2

  def test_zero_role_pips_zero_value(self):
    player = _player([NS(worker_count=0, is_flipped=False)])
    value = self.greedy._payout_value("count owned_soldier g 2", self.rates, player)
    self.assertEqual(value, 0.0)


if __name__ == "__main__":
  unittest.main()
