"""advance_tick must block on every player-owed prompt verb.

Regression for the shadowvale 3p hang: build_domain_payment (the pay stage of
a harvest-time domain build) was missing from the blocking whitelist, so
advance_tick kept returning True and auto-advance loops spun forever.
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


class AdvanceTickBlockingTests(unittest.TestCase):
  def test_blocks_on_player_owed_prompt_verbs(self):
    from agent.headless import new_game

    game = new_game(seed=3)
    pid = game.player_list[0].player_id
    for verb in ("build_domain_payment", "may_sail", "may_recruit",
                 "choose_domain_to_build", "harvest_steal"):
      with self.subTest(verb=verb):
        game.phase = "harvest"
        game.action_required = {"id": pid, "action": verb}
        with contextlib.redirect_stdout(_SINK):
          self.assertFalse(
            game.advance_tick(),
            f"advance_tick must wait while {verb!r} is owed by a player",
          )


if __name__ == "__main__":
  unittest.main()
