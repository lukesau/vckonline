"""Greedy last-coin premium: payments that fully drain gold or strength rank
below splits that leave one behind (all else equal); premium=0 restores the
pure liquidity ordering."""

import contextlib
import io
import unittest

import db_config
from agent import fake_db
from agent.policies import GreedyConfig, GreedyPolicy

_real_connect = db_config.connect


def setUpModule():
  fake_db.install()


def tearDownModule():
  db_config.connect = _real_connect


_SINK = io.StringIO()


def _action_phase_game(seed):
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
  return game if game.phase == "action" else None


def _acting_player(game):
  pid = game.action_required["id"]
  return next(p for p in game.player_list if p.player_id == pid)


def _no_premium_policy():
  cfg = GreedyConfig()
  cfg.last_coin_premium = 0.0
  return GreedyPolicy(config=cfg)


def _find_drain_pair(game, pid, action_type, res):
  """(drain_move, leave_one_move) for the same target, or None."""
  from agent.headless import legal_moves

  groups = {}
  for m in legal_moves(game, pid):
    if m.get("action_type") != action_type:
      continue
    target = m.get("citizen_id", m.get("domain_id", m.get("monster_id")))
    groups.setdefault(target, []).append(m)
  player = _acting_player(game)
  have = int(getattr(player, f"{res}_score"))
  for splits in groups.values():
    drain = next((m for m in splits if m["payment"][res] == have), None)
    keep1 = next((m for m in splits if m["payment"][res] == have - 1), None)
    if drain is not None and keep1 is not None:
      return drain, keep1
  return None


class LastCoinPremiumTests(unittest.TestCase):
  def _pair_across_seeds(self, action_type, res, gold, strength, magic):
    for seed in range(1, 15):
      game = _action_phase_game(seed)
      if game is None:
        continue
      player = _acting_player(game)
      player.gold_score, player.strength_score, player.magic_score = gold, strength, magic
      pair = _find_drain_pair(game, player.player_id, action_type, res)
      if pair:
        return game, player.player_id, pair
    self.fail(f"no drain/keep-one {action_type} pair found in seeds 1-14")

  def _assert_premium_flips(self, action_type, res, gold, strength, magic):
    game, pid, (drain, keep1) = self._pair_across_seeds(action_type, res, gold, strength, magic)
    with_premium = GreedyPolicy().move_values(game, pid, [drain, keep1])
    without = _no_premium_policy().move_values(game, pid, [drain, keep1])
    self.assertGreater(
      with_premium[1], with_premium[0],
      f"premium should rank keep-one above draining {res}",
    )
    self.assertGreaterEqual(
      without[0], without[1],
      "without premium, liquidity should prefer the draining split",
    )

  def test_hire_prefers_keeping_last_gold(self):
    self._assert_premium_flips("hire_citizen", "gold", gold=2, strength=0, magic=6)

  def test_slay_prefers_keeping_last_strength(self):
    self._assert_premium_flips("slay_monster", "strength", gold=2, strength=2, magic=6)


if __name__ == "__main__":
  unittest.main()
