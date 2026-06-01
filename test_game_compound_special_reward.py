"""Regression tests for compound monster `special_reward` strings that combine
two prompt-opening rewards (`<domains>`, `<citizens>`) joined by ` + `.

Both orderings must:
- Open prompts in order: first leg, then (after it resolves) second leg.
- Move both an accessible domain and an accessible citizen onto the player's
  tableau, plus credit the monster's flat `vp_reward`.
- Not leak the `-9999` sentinel into the player's gold score.

The compound dispatch in `engines/payouts.py` runs BEFORE the bare-`<domains>`
and bare-`<citizens>` shortcuts so the second leg isn't lost. The
`choose_domain_reward` action handler in `engines/player_actions.py` drains
`pending_payout_continuation` after the player picks a domain so the second
leg fires.
"""

import unittest

from cards import Citizen, Domain, Monster
from game import Game
from game_models import Player


def _make_monster(monster_id, name, special_reward, *, has_special_reward=True,
                  strength_cost=5, magic_cost=4, vp_reward=3):
    m = Monster(
        monster_id, name, "Tundra", "Titan", 4,
        strength_cost, magic_cost, vp_reward, 0,
        0, 0,
        has_special_reward, special_reward,
        False, "",
        0, "test",
    )
    m.toggle_visibility(True)
    m.toggle_accessibility(True)
    return m


def _make_citizen(citizen_id, name):
    c = Citizen(
        citizen_id=citizen_id,
        name=name,
        gold_cost=0,
        roll_match1=2, roll_match2=0,
        shadow_count=0, holy_count=0, soldier_count=0, worker_count=1,
        gold_payout_on_turn=0, gold_payout_off_turn=0,
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


def _make_domain(domain_id, name, vp_reward=0):
    # No activation / passive effect: the test wants to verify the compound
    # chain itself, not interactions with another effect that opens its own
    # prompt on acquisition.
    d = Domain(
        domain_id=domain_id,
        name=name,
        gold_cost=0,
        shadow_count=0, holy_count=0, soldier_count=0, worker_count=0,
        vp_reward=vp_reward,
        has_activation_effect=False, has_passive_effect=False,
        passive_effect="", activation_effect="",
        text="", expansion="test",
    )
    d.toggle_visibility(True)
    d.toggle_accessibility(True)
    return d


def _make_game(player, monster):
    citizen_grid = [
        [_make_citizen(1, "Peasant")],
        [_make_citizen(2, "Knight")],
    ]
    domain_grid = [
        [_make_domain(101, "Smallholding")],
        [_make_domain(102, "Watchtower")],
    ]
    return Game({
        "game_id": "test-game",
        "player_list": [player],
        "monster_grid": [[monster]],
        "citizen_grid": citizen_grid,
        "domain_grid": domain_grid,
        "die_one": 1, "die_two": 1, "die_sum": 2,
        "exhausted_count": 0, "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "phase": "action",
        "actions_remaining": 1,
    })


def _open_immediate_slay_payment(game, player_id, monster):
    game.action_required["id"] = player_id
    game.action_required["action"] = "slay_monster_payment"
    game.pending_required_choice = {
        "kind": "immediate_slay",
        "stage": "pay_for_slay",
        "player_id": player_id,
        "source_label": "Test",
        "resume_kind": "domain_activation",
        "monster_id": monster.monster_id,
        "monster_name": monster.name,
        "strength_cost": int(monster.strength_cost),
        "magic_cost": int(monster.magic_cost),
        "gold_cost": 0,
    }


class DomainsThenCitizensCompoundTests(unittest.TestCase):
    """special_reward = `<domains> + <citizens>`."""

    def _slay(self):
        player = Player("p1", "Player 1")
        player.gold_score = 0
        player.strength_score = 11
        player.magic_score = 5
        player.victory_score = 0
        monster = _make_monster(901, "Compound Beast",
                                "<domains> + <citizens>")
        game = _make_game(player, monster)
        _open_immediate_slay_payment(game, player.player_id, monster)
        game.act_on_required_action(player.player_id, "slay_pay 0 5 4")
        return player, monster, game

    def test_first_leg_opens_choose_domain_reward(self):
        player, _, game = self._slay()
        self.assertEqual(player.gold_score, 0,
                         "gold leaked -9999 sentinel into player score")
        # Slay vp_reward applied immediately on slay (independent of either leg).
        self.assertEqual(player.victory_score, 3)
        self.assertEqual(game.action_required.get("action", ""),
                         "choose_domain_reward")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "grant_domain_reward")
        self.assertEqual(prc.get("player_id"), "p1")
        # Both domains are pickable.
        self.assertEqual(len(prc.get("options") or []), 2)

    def test_second_leg_opens_after_domain_pick(self):
        player, _, game = self._slay()
        game.act_on_required_action("p1", "grant_domain 1")
        # First leg now resolved; the citizens leg should be open.
        self.assertEqual(len(player.owned_domains), 1)
        self.assertEqual(player.owned_domains[0].name, "Smallholding")
        ar = game.action_required.get("action", "")
        self.assertTrue(
            ar.lower().startswith("choose"),
            f"expected the citizens leg to open after the domain pick; "
            f"got action_required={ar!r}",
        )
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "special_payout_choose")

    def test_full_chain_grants_both_cards(self):
        player, _, game = self._slay()
        game.act_on_required_action("p1", "grant_domain 1")
        game.act_on_required_action("p1", "choose 1")
        domain_names = sorted(d.name for d in player.owned_domains)
        citizen_names = sorted(c.name for c in player.owned_citizens)
        self.assertEqual(domain_names, ["Smallholding"])
        self.assertEqual(citizen_names, ["Peasant"])
        # Slay payment was deducted; nothing else touched gold.
        self.assertEqual(player.gold_score, 0)
        self.assertEqual(player.strength_score, 11 - 5)
        self.assertEqual(player.magic_score, 5 - 4)
        # vp_reward = 3 from the slay; neither leg pays vp.
        self.assertEqual(player.victory_score, 3)


class CitizensThenDomainsCompoundTests(unittest.TestCase):
    """special_reward = `<citizens> + <domains>` (reverse order)."""

    def _slay(self):
        player = Player("p1", "Player 1")
        player.gold_score = 0
        player.strength_score = 11
        player.magic_score = 5
        player.victory_score = 0
        monster = _make_monster(902, "Reverse Beast",
                                "<citizens> + <domains>")
        game = _make_game(player, monster)
        _open_immediate_slay_payment(game, player.player_id, monster)
        game.act_on_required_action(player.player_id, "slay_pay 0 5 4")
        return player, monster, game

    def test_first_leg_opens_choose_citizens(self):
        player, _, game = self._slay()
        self.assertEqual(player.gold_score, 0)
        ar = game.action_required.get("action", "")
        self.assertTrue(
            ar.lower().startswith("choose"),
            f"expected the citizens leg to open first; got "
            f"action_required={ar!r}",
        )
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "special_payout_choose")

    def test_second_leg_opens_after_citizen_pick(self):
        player, _, game = self._slay()
        game.act_on_required_action("p1", "choose 1")
        self.assertEqual(len(player.owned_citizens), 1)
        self.assertEqual(game.action_required.get("action", ""),
                         "choose_domain_reward")
        prc = game.pending_required_choice or {}
        self.assertEqual(prc.get("kind"), "grant_domain_reward")

    def test_full_chain_grants_both_cards(self):
        player, _, game = self._slay()
        game.act_on_required_action("p1", "choose 1")
        game.act_on_required_action("p1", "grant_domain 1")
        domain_names = sorted(d.name for d in player.owned_domains)
        citizen_names = sorted(c.name for c in player.owned_citizens)
        self.assertEqual(domain_names, ["Smallholding"])
        self.assertEqual(citizen_names, ["Peasant"])
        self.assertEqual(player.gold_score, 0)
        self.assertEqual(player.victory_score, 3)


class CompoundDispatchPlusInsideAngleBracketsTests(unittest.TestCase):
    """`<citizens + v 1> + ...` should not be split inside the angle brackets.

    Today no shipped card uses a top-level compound where one leg is a
    citizens-where extras clause, but the helper used by the dispatcher must
    still respect the bracket scope so a future card can mix the two without
    surprise. We assert directly against the helper.
    """

    def test_helper_ignores_plus_inside_angle_brackets(self):
        from engines.payouts import PayoutsEngine

        class _Stub:
            pass

        eng = PayoutsEngine.__new__(PayoutsEngine)
        eng.game = _Stub()
        self.assertFalse(eng._has_top_level_plus("<citizens + v 1>"))
        self.assertTrue(eng._has_top_level_plus("<domains> + <citizens>"))
        self.assertTrue(eng._has_top_level_plus("s 5 + slay"))
        self.assertFalse(eng._has_top_level_plus("choose g 1 m 1"))


if __name__ == "__main__":
    unittest.main()
