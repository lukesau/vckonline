"""Engine round-trip for enumerated mixed payments (magic-as-wild).

The enumerator emits gold+magic hire/build splits and wild-magic slay splits;
these tests apply those exact move dicts to a live Game and assert the engine
accepts them and deducts the right resources.
"""

import contextlib
import io
import unittest

import db_config
from agent import fake_db

_real_connect = db_config.connect


def setUpModule():
  fake_db.install()


def tearDownModule():
  db_config.connect = _real_connect


_SINK = io.StringIO()


def _action_phase_game(seed=11):
  from agent.headless import acting_player_ids, advance, apply_move, legal_moves, new_game

  game = new_game(seed=seed)
  with contextlib.redirect_stdout(_SINK):
    # Drive the pre-turn decisions (choose_duke, finalize_roll) with the
    # first legal move until the first standard action is owed.
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
    raise AssertionError(f"setup did not reach action phase (phase={game.phase!r})")
  return game


def _acting_player(game):
  pid = game.action_required["id"]
  return next(p for p in game.player_list if p.player_id == pid)


class MixedPaymentRoundTripTests(unittest.TestCase):
  def test_engine_accepts_enumerated_gold_magic_hire(self):
    from agent.headless import apply_move, legal_moves

    game = _action_phase_game()
    player = _acting_player(game)
    player.gold_score, player.strength_score, player.magic_score = 1, 0, 10

    hires = [
      m for m in legal_moves(game, player.player_id)
      if m.get("action_type") == "hire_citizen" and m["payment"]["magic"] > 0
    ]
    self.assertTrue(hires, "no mixed-payment hire enumerated at game start")
    move = hires[0]
    cost = move["payment"]["gold"] + move["payment"]["magic"]
    owned_before = len(player.owned_citizens)

    with contextlib.redirect_stdout(_SINK):
      apply_move(game, move)

    self.assertEqual(len(player.owned_citizens), owned_before + 1)
    self.assertEqual(player.gold_score, 1 - move["payment"]["gold"])
    self.assertEqual(player.magic_score, 10 - move["payment"]["magic"])
    self.assertEqual(move["payment"]["gold"] + move["payment"]["magic"], cost)

  def test_engine_accepts_enumerated_wild_magic_slay(self):
    from agent.headless import apply_move, legal_moves

    game = _action_phase_game()
    player = _acting_player(game)
    player.gold_score, player.strength_score, player.magic_score = 0, 1, 12

    def _target_card(move):
      for stack in game.monster_grid:
        if not stack:
          continue
        top = stack[-1]
        if move.get("monster_id") is not None \
            and getattr(top, "monster_id", None) == move["monster_id"]:
          return top
        if move.get("event_id") is not None \
            and getattr(top, "event_id", None) == move["event_id"]:
          return top
      return None

    slays = [
      m for m in legal_moves(game, player.player_id)
      if m.get("action_type") == "slay_monster" and m["payment"]["strength"] == 1
      and m["payment"]["magic"] > 0
    ]
    self.assertTrue(slays, "no wild-magic slay enumerated at game start")
    # Prefer a plain-reward monster so score deltas are exactly predictable.
    move = next(
      (m for m in slays
       if _target_card(m) is not None and not getattr(_target_card(m), "has_special_reward", False)),
      slays[0],
    )
    card = _target_card(move)
    plain_reward = card is not None and not getattr(card, "has_special_reward", False)
    strength_reward = int(getattr(card, "strength_reward", 0) or 0)
    magic_reward = int(getattr(card, "magic_reward", 0) or 0)
    owned_before = len(player.owned_monsters)

    with contextlib.redirect_stdout(_SINK):
      apply_move(game, move)

    self.assertEqual(len(player.owned_monsters), owned_before + 1)
    if plain_reward:
      self.assertEqual(player.strength_score, 1 - move["payment"]["strength"] + strength_reward)
      self.assertEqual(player.magic_score, 12 - move["payment"]["magic"] + magic_reward)


if __name__ == "__main__":
  unittest.main()
