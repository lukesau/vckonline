"""Regression tests for the may-slay (Dragoon-style) -> slay_monster flow when
the slain monster has a `special_reward` that opens a follow-up prompt.

Covers three intersecting bugs that all manifested only when slay_monster was
invoked from inside the `slay_monster_payment` prompt handler:

1. The DB previously stored Frost Ogre / Wendigo's `special_reward` as a bare
   `<citizens>` instead of `choose <citizens>`. `execute_special_payout` had
   no top-level handler for bare `<citizens>`, so the token fell through and
   returned the `-9999` sentinel WITHOUT opening a citizen prompt. The
   defensive fallback added to `execute_special_payout` now normalizes a bare
   `<citizens ...>` token to `choose <citizens ...>`.

2. `slay_monster`'s deferral check used "is action_required set?" as a proxy
   for "did the special reward open a new prompt?" — but when slay_monster
   was called from a prompt handler that itself had `action_required` set to
   `slay_monster_payment`, that check always saw the OUTER prompt and treated
   the `-9999` sentinel as real. The sentinel then leaked into the player's
   gold score (the user saw their gold drop from 9 to -9990).

3. After `slay_monster` returned, the `slay_monster_payment` handler used to
   unconditionally clear `action_required` and `pending_required_choice` and
   then call `_resume_after_immediate_slay`. If the slain monster's special
   reward opened a follow-up `choose` prompt (e.g. Warg's
   `choose m 3 <citizens where name==Peasant>`), that new prompt was silently
   destroyed and the player never got to pick.
"""

import unittest

from cards import Citizen, Monster
from game import Game
from game_models import Player


def _make_monster(monster_id, name, special_reward, has_special_reward=True,
                  strength_cost=5, magic_cost=4, vp_reward=3, gold_reward=0,
                  strength_reward=0, magic_reward=0, area="Tundra",
                  monster_type="Titan", order=4, expansion="flamesandfrost"):
    m = Monster(
        monster_id, name, area, monster_type, order,
        strength_cost, magic_cost, vp_reward, gold_reward,
        strength_reward, magic_reward,
        has_special_reward, special_reward,
        False, "",
        0, expansion,
    )
    m.toggle_visibility(True)
    m.toggle_accessibility(True)
    return m


def _make_peasant_citizen(citizen_id=1):
    c = Citizen(
        citizen_id=citizen_id,
        name="Peasant",
        gold_cost=0,
        roll_match1=2, roll_match2=0,
        shadow_count=0, holy_count=0, soldier_count=0, worker_count=1,
        gold_payout_on_turn=1, gold_payout_off_turn=0,
        strength_payout_on_turn=0, strength_payout_off_turn=0,
        magic_payout_on_turn=0, magic_payout_off_turn=0,
        vp_payout_on_turn=0, vp_payout_off_turn=0,
        has_special_payout_on_turn=False, has_special_payout_off_turn=False,
        special_payout_on_turn="", special_payout_off_turn="",
        special_citizen=False, expansion="base",
    )
    c.toggle_visibility(True)
    c.toggle_accessibility(True)
    return c


def _make_knight_citizen(citizen_id=2):
    c = Citizen(
        citizen_id=citizen_id,
        name="Knight",
        gold_cost=4,
        roll_match1=11, roll_match2=0,
        shadow_count=0, holy_count=0, soldier_count=1, worker_count=0,
        gold_payout_on_turn=0, gold_payout_off_turn=0,
        strength_payout_on_turn=1, strength_payout_off_turn=0,
        magic_payout_on_turn=0, magic_payout_off_turn=0,
        vp_payout_on_turn=0, vp_payout_off_turn=0,
        has_special_payout_on_turn=False, has_special_payout_off_turn=False,
        special_payout_on_turn="", special_payout_off_turn="",
        special_citizen=False, expansion="base",
    )
    c.toggle_visibility(True)
    c.toggle_accessibility(True)
    return c


def _make_game(player, monster, *, citizen_grid=None):
    if citizen_grid is None:
        # Two distinct stacks so `<citizens>` has multiple options and the
        # prompt actually has to render (a single option auto-applies).
        citizen_grid = [
            [_make_peasant_citizen(1)],
            [_make_knight_citizen(2)],
        ]
    return Game({
        "game_id": "test-game",
        "player_list": [player],
        "monster_grid": [[monster]],
        "citizen_grid": citizen_grid,
        "domain_grid": [],
        "die_one": 1, "die_two": 1, "die_sum": 2,
        "exhausted_count": 0, "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "phase": "action",
        "actions_remaining": 1,
    })


def _open_immediate_slay_payment(game, player_id, monster, resume_kind="harvest_pending_slay"):
    """Set up the may-slay prompt at the pay_for_slay stage, ready to receive
    a `slay_pay <g> <s> <m>` action from the player. Mirrors what the engine
    does after the player picks a monster from the choose_monster_slay stage.
    """
    game.action_required["id"] = player_id
    game.action_required["action"] = "slay_monster_payment"
    game.pending_required_choice = {
        "kind": "immediate_slay",
        "stage": "pay_for_slay",
        "player_id": player_id,
        "source_label": "Dragoon",
        "resume_kind": resume_kind,
        "monster_id": monster.monster_id,
        "monster_name": monster.name,
        "strength_cost": int(monster.strength_cost),
        "magic_cost": int(monster.magic_cost),
        "gold_cost": 0,
    }


class FrostOgreImmediateSlayTests(unittest.TestCase):
    """Frost Ogre slain via a may-slay prompt — special_reward `<citizens>` (legacy)
    AND `choose <citizens>` (canonical) both need to:
      - NOT leak the -9999 sentinel into player.gold_score
      - Open the citizen-pick prompt so the player can grab a citizen
      - Award the +3 VP slay reward
    """

    def _run(self, special_reward):
        player = Player("p1", "Player 1")
        player.gold_score = 9
        player.strength_score = 11
        player.magic_score = 5
        player.victory_score = 5
        monster = _make_monster(81, "Frost Ogre", special_reward)
        game = _make_game(player, monster)
        _open_immediate_slay_payment(game, player.player_id, monster)

        game.act_on_required_action(player.player_id, "slay_pay 0 5 4")

        return player, monster, game

    def test_bare_citizens_does_not_leak_sentinel(self):
        player, _, game = self._run("<citizens>")
        # Gold paid: 0. The bug deducted 9999 here.
        self.assertEqual(player.gold_score, 9, "gold leaked -9999 sentinel into player score")
        self.assertEqual(player.strength_score, 11 - 5)
        self.assertEqual(player.magic_score, 5 - 4)
        self.assertEqual(player.victory_score, 5 + 3, "VP slay reward not applied")

    def test_bare_citizens_opens_followup_choice_prompt(self):
        _, _, game = self._run("<citizens>")
        # Defensive fallback in execute_special_payout normalizes bare
        # `<citizens>` to `choose <citizens>` and opens the choose prompt.
        ar = game.action_required.get("action", "")
        self.assertTrue(
            ar.lower().startswith("choose"),
            f"expected a choose prompt to be open after slay; got action_required={ar!r}",
        )
        self.assertIsNotNone(game.pending_required_choice)
        self.assertEqual(game.pending_required_choice.get("kind"), "special_payout_choose")

    def test_bare_citizens_stashes_post_slay_resume(self):
        _, _, game = self._run("<citizens>")
        cont = getattr(game, "pending_post_slay_resume", None)
        self.assertIsNotNone(cont, "post-slay resume continuation was not stashed")
        self.assertEqual(cont.get("resume_kind"), "harvest_pending_slay")
        self.assertEqual(cont.get("player_id"), "p1")

    def test_canonical_choose_citizens_also_works(self):
        # Once the DB is fixed (sql/fix_grant_citizen_choose_prefix.sql), Frost
        # Ogre's special_reward is `choose <citizens>`. Same expectations.
        player, _, game = self._run("choose <citizens>")
        self.assertEqual(player.gold_score, 9)
        self.assertEqual(player.victory_score, 5 + 3)
        ar = game.action_required.get("action", "")
        self.assertTrue(ar.lower().startswith("choose"))
        self.assertEqual(game.pending_required_choice.get("kind"), "special_payout_choose")


class WargImmediateSlayChooseSurvivesTests(unittest.TestCase):
    """Warg slain via a may-slay prompt — special_reward
    `choose m 3 <citizens where name==Peasant>` returns [0,0,0,0] but opens a
    follow-up choose prompt that the handler must NOT clobber.
    """

    def _run(self):
        player = Player("p1", "Player 1")
        player.gold_score = 9
        player.strength_score = 11
        player.magic_score = 5
        player.victory_score = 5
        monster = _make_monster(
            78, "Warg", "choose m 3 <citizens where name==Peasant>",
            strength_cost=3, magic_cost=3, vp_reward=1,
        )
        game = _make_game(player, monster)
        _open_immediate_slay_payment(game, player.player_id, monster)

        game.act_on_required_action(player.player_id, "slay_pay 0 3 3")
        return player, monster, game

    def test_no_gold_leak(self):
        player, _, _ = self._run()
        self.assertEqual(player.gold_score, 9, "gold leaked -9999 sentinel into player score")

    def test_vp_reward_applied(self):
        player, _, _ = self._run()
        self.assertEqual(player.victory_score, 5 + 1)

    def test_choose_prompt_survives_after_slay(self):
        _, _, game = self._run()
        ar = game.action_required.get("action", "")
        self.assertTrue(
            ar.lower().startswith("choose"),
            f"choose prompt was clobbered by slay_monster_payment handler; "
            f"action_required={ar!r}",
        )
        self.assertIsNotNone(game.pending_required_choice)
        self.assertEqual(game.pending_required_choice.get("kind"), "special_payout_choose")

    def test_post_slay_resume_drains_after_choose_resolves(self):
        _, _, game = self._run()
        self.assertIsNotNone(getattr(game, "pending_post_slay_resume", None))
        # Resolve the choose prompt by picking option 1.
        game.act_on_required_action("p1", "choose 1")
        # After the choose resolves and any continuation drains, the post-slay
        # resume should have fired (cleared) and the may-slay flow should be
        # done. With resume_kind=harvest_pending_slay there's no harvest in
        # progress in this test, so the resume is essentially a no-op clear.
        self.assertIsNone(
            getattr(game, "pending_post_slay_resume", None),
            "post-slay resume continuation was not drained after choose resolved",
        )


if __name__ == "__main__":
    unittest.main()
