"""Player-count-general features (v3): shape, finiteness, 2p equivalence."""

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


def _game(preset="base", players=2, seed=6):
  from agent.headless import acting_player_ids, advance, apply_move, legal_moves, new_game

  game = new_game(preset=preset, num_players=players, seed=seed)
  with contextlib.redirect_stdout(_SINK):
    for _ in range(60):
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
  return game


class GeneralFeatureTests(unittest.TestCase):
  def test_shape_and_finiteness_across_player_counts(self):
    from agent.features import N_FEATURES, extract

    for players in (2, 3, 4, 5):
      with self.subTest(players=players):
        game = _game(players=players)
        for p in game.player_list:
          vec = extract(game, p.player_id)
          self.assertEqual(vec.shape, (N_FEATURES,))
          self.assertTrue(np.all(np.isfinite(vec)))

  def test_crimsonseas_states_extract(self):
    from agent.features import N_FEATURES, extract

    game = _game(preset="crimsonseas", players=4)
    vec = extract(game, game.player_list[0].player_id)
    self.assertEqual(vec.shape, (N_FEATURES,))
    self.assertTrue(np.all(np.isfinite(vec)))

  def test_2p_leader_equals_mean_block(self):
    # In a 2-player game the leader and mean opponent aggregates must be the
    # SAME block — that identity is what keeps 2p training data meaningful.
    from agent.features import extract

    game = _game(players=2)
    vec = extract(game, game.player_list[0].player_id)
    leader = vec[18:36]
    mean = vec[36:54]
    np.testing.assert_allclose(leader, mean, rtol=0, atol=1e-6)

  def test_viewer_relative(self):
    from agent.features import extract

    game = _game(players=3, seed=8)
    a, b = game.player_list[0].player_id, game.player_list[1].player_id
    self.assertFalse(np.allclose(extract(game, a), extract(game, b)))

  def test_single_player_viewer_rejected(self):
    from agent.features import extract

    game = _game(players=2)
    with self.assertRaises(ValueError):
      extract(game, "nobody")


if __name__ == "__main__":
  unittest.main()
