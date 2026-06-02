"""Tests for non-monster Event activation / passive effects (flamesandfrost).

These events fire when flipped off the Exhausted stack onto a board stack. The
activation/passive codepaths reuse domain-style mechanics (self_convert bank
trades, concurrent flip, banish-for-reward, all_lose, roll.on_event).
"""

import unittest

from cards import Citizen, Event
from game import Game
from game_models import Player


# --- card builders ---------------------------------------------------------

def make_event(event_id, name, *, activation_effect=None, passive_effect=None,
               has_activation=False, has_passive=False, is_monster=0):
    return Event(
        event_id, name,
        -1,                      # roll_match1
        None,                    # roll_effect
        0,                       # has_roll_effect
        is_monster,
        1 if has_activation else 0,
        1 if has_passive else 0,
        activation_effect,
        passive_effect,
        0, 0,                    # strength_cost, magic_cost
        None,                    # monster_type
        0, 0, 0, 0,              # vp/gold/strength/magic reward
        0, None,                 # has_special_reward, special_reward
        "flamesandfrost",
    )


def make_citizen(citizen_id, *, shadow=0, holy=0, soldier=0, worker=0, name=None):
    return Citizen(
        citizen_id, name or f"Citizen {citizen_id}",
        2,                       # gold_cost
        1, 0,                    # roll_match1, roll_match2
        shadow, holy, soldier, worker,
        1, 0,                    # gold payout on/off
        0, 0, 0, 0, 0, 0,        # strength/magic/vp payouts
        False, False, "", "",
        False, "test",
    )


def make_game(n_players=3, *, phase="harvest", turn_index=0, gold=10, strength=10, magic=10):
    players = []
    for i in range(n_players):
        p = Player(f"p{i+1}", f"Player {i+1}")
        p.gold_score = gold
        p.strength_score = strength
        p.magic_score = magic
        p.victory_score = 0
        players.append(p)
    game = Game({
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [[], [], [], [], []],
        "citizen_grid": [[], [], [], [], [], [], [], [], [], []],
        "domain_grid": [[], [], [], [], []],
        "die_one": 1, "die_two": 2, "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": turn_index,
        "phase": phase,
        "actions_remaining": 2,
    })
    return game, players


def fire(game, event, revealing_player_id):
    game.events._fire_activation({
        "event_id": int(event.event_id),
        "name": event.name,
        "activation_effect": event.activation_effect,
        "revealing_player_id": revealing_player_id,
    })


# --- Curse of The North (passive) ------------------------------------------

class CurseOfTheNorthTests(unittest.TestCase):
    def test_doubles_all_lose_3_magic(self):
        game, players = make_game(3, magic=5)
        ev = make_event(20, "Curse of The North",
                        passive_effect="roll.on_event doubles all_lose m 3",
                        has_passive=True)
        game.monster_grid[0].append(ev)
        game.roll_events = ["doubles"]
        game.events.apply_board_event_passive_roll_effects()
        for p in players:
            self.assertEqual(p.magic_score, 2)

    def test_no_doubles_no_loss(self):
        game, players = make_game(3, magic=5)
        ev = make_event(20, "Curse of The North",
                        passive_effect="roll.on_event doubles all_lose m 3",
                        has_passive=True)
        game.monster_grid[0].append(ev)
        game.roll_events = []
        game.events.apply_board_event_passive_roll_effects()
        for p in players:
            self.assertEqual(p.magic_score, 5)

    def test_magic_floored_at_zero(self):
        game, players = make_game(2, magic=1)
        ev = make_event(20, "Curse of The North",
                        passive_effect="roll.on_event doubles all_lose m 3",
                        has_passive=True)
        game.domain_grid[0].append(ev)
        game.roll_events = ["doubles"]
        game.events.apply_board_event_passive_roll_effects()
        for p in players:
            self.assertEqual(p.magic_score, 0)

    def test_passive_inactive_once_recycled_off_board(self):
        game, players = make_game(2, magic=5)
        ev = make_event(20, "Curse of The North",
                        passive_effect="roll.on_event doubles all_lose m 3",
                        has_passive=True)
        # Not placed on any board stack -> not "in play" -> no effect.
        game.exhausted_stack.append(ev)
        game.roll_events = ["doubles"]
        game.events.apply_board_event_passive_roll_effects()
        for p in players:
            self.assertEqual(p.magic_score, 5)


# --- The Key and Blade (immediate, no prompt) ------------------------------

class KeyAndBladeTests(unittest.TestCase):
    def test_active_loses_3_others_lose_1(self):
        game, players = make_game(3, gold=10)
        ev = make_event(21, "The Key and Blade",
                        activation_effect="active_lose g 3 + others_lose g 1",
                        has_activation=True)
        fire(game, ev, players[0].player_id)
        self.assertEqual(players[0].gold_score, 7)
        self.assertEqual(players[1].gold_score, 9)
        self.assertEqual(players[2].gold_score, 9)

    def test_gold_floored(self):
        game, players = make_game(2, gold=2)
        ev = make_event(21, "The Key and Blade",
                        activation_effect="active_lose g 3 + others_lose g 1",
                        has_activation=True)
        fire(game, ev, players[0].player_id)
        self.assertEqual(players[0].gold_score, 0)
        self.assertEqual(players[1].gold_score, 1)


# --- The Wizards of Nae (active player optional gain action) ---------------

class WizardsOfNaeTests(unittest.TestCase):
    def _event(self):
        return make_event(18, "The Wizards of Nae",
                          activation_effect="active_may gain_action pay=m:3",
                          has_activation=True)

    def test_prompt_opens_in_action_phase(self):
        game, players = make_game(2, phase="action", magic=5)
        game.actions_remaining = 1
        fire(game, self._event(), players[0].player_id)
        self.assertEqual(game.action_required.get("action"), "event_gain_action")
        self.assertEqual(game.pending_required_choice.get("player_id"), players[0].player_id)

    def test_accept_pays_and_grants_action(self):
        game, players = make_game(2, phase="action", magic=5)
        game.actions_remaining = 1
        fire(game, self._event(), players[0].player_id)
        game.act_on_required_action(players[0].player_id, "accept")
        self.assertEqual(players[0].magic_score, 2)
        self.assertEqual(game.actions_remaining, 2)
        self.assertEqual(game.pending_required_choice, None)

    def test_revealed_after_final_action_still_offers_extra_action(self):
        game, players = make_game(2, phase="action", magic=5)
        game.actions_remaining = 0
        game.action_required = {"id": players[0].player_id, "action": "standard_action"}
        game.exhausted_stack.append(self._event())

        game.events.reveal_exhausted_onto_stack(game.citizen_grid[0])
        game.finish_turn_if_no_actions_remaining()

        self.assertEqual(game.phase, "action")
        self.assertEqual(game.actions_remaining, 0)
        self.assertEqual(game.action_required.get("action"), "event_gain_action")
        self.assertEqual(game.pending_required_choice.get("player_id"), players[0].player_id)

        game.act_on_required_action(players[0].player_id, "accept")
        self.assertEqual(players[0].magic_score, 2)
        self.assertEqual(game.actions_remaining, 1)
        self.assertEqual(game.phase, "action")

    def test_skip_costs_nothing(self):
        game, players = make_game(2, phase="action", magic=5)
        game.actions_remaining = 1
        fire(game, self._event(), players[0].player_id)
        game.act_on_required_action(players[0].player_id, "skip")
        self.assertEqual(players[0].magic_score, 5)
        self.assertEqual(game.actions_remaining, 1)

    def test_skipped_when_unaffordable(self):
        game, players = make_game(2, phase="action", magic=2)
        game.actions_remaining = 1
        fire(game, self._event(), players[0].player_id)
        self.assertNotEqual(game.action_required.get("action"), "event_gain_action")

    def test_skipped_outside_action_phase(self):
        game, players = make_game(2, phase="harvest", magic=5)
        fire(game, self._event(), players[0].player_id)
        self.assertNotEqual(game.action_required.get("action"), "event_gain_action")

    def test_accept_sets_usable_actions_to_three(self):
        game, players = make_game(2, phase="action", magic=5)
        game.actions_remaining = 2
        fire(game, self._event(), players[0].player_id)
        game.act_on_required_action(players[0].player_id, "accept")
        self.assertEqual(game.actions_remaining, 3)

    def test_revealed_outside_action_phase_is_carried_to_action_phase(self):
        # Rare path: an event revealed during harvest (e.g. a payout empties a
        # stack) carries the additional-action offer to the revealing player's
        # own action phase rather than firing mid-harvest.
        game, players = make_game(2, phase="harvest", magic=5)
        game.exhausted_stack.append(self._event())

        game.events.reveal_exhausted_onto_stack(game.citizen_grid[0])
        # Not offered during harvest; carried on the pending queue, tagged to the player.
        self.assertNotEqual(game.action_required.get("action"), "event_gain_action")
        self.assertEqual(game.pending_event_activations[0]["name"], "The Wizards of Nae")
        self.assertEqual(game.pending_event_activations[0]["revealing_player_id"], players[0].player_id)

        # Entering that player's action phase drains the carried offer.
        game.phase = "action"
        game.actions_remaining = 2
        game.action_required = {"id": players[0].player_id, "action": "standard_action"}
        game.events.drain_pending_event_activations()
        self.assertEqual(game.action_required.get("action"), "event_gain_action")
        self.assertEqual(game.pending_required_choice.get("player_id"), players[0].player_id)

        game.act_on_required_action(players[0].player_id, "accept")
        self.assertEqual(players[0].magic_score, 2)
        self.assertEqual(game.actions_remaining, 3)
        self.assertEqual(game.pending_event_activations, [])

    def test_carried_offer_expires_if_owner_turn_passed(self):
        # If a carried grant somehow survives to a different active player's
        # action phase, it expires instead of leaking onto that player.
        game, players = make_game(2, phase="harvest", magic=5)
        game.exhausted_stack.append(self._event())
        game.events.reveal_exhausted_onto_stack(game.citizen_grid[0])
        self.assertEqual(game.pending_event_activations[0]["revealing_player_id"], players[0].player_id)

        # Player 2 is now the active player.
        game.turn_index = 1
        game.phase = "action"
        game.actions_remaining = 2
        game.action_required = {"id": players[1].player_id, "action": "standard_action"}
        game.events.drain_pending_event_activations()

        self.assertNotEqual(game.action_required.get("action"), "event_gain_action")
        self.assertEqual(game.pending_event_activations, [])
        self.assertEqual(game.actions_remaining, 2)


# --- Support The Empire (all may pay 5 wild for 3 VP) ----------------------

class SupportTheEmpireTests(unittest.TestCase):
    def _event(self):
        return make_event(19, "Support The Empire",
                          activation_effect="all_may self_convert pay=wild:5 gain=v:3",
                          has_activation=True)

    def test_concurrent_opens_for_affordable_players(self):
        game, players = make_game(3, gold=10, strength=2, magic=2)
        # players[2] can't afford 5 of any single resource.
        players[2].gold_score = 1
        fire(game, self._event(), players[0].player_id)
        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca["kind"], "event_self_convert")
        self.assertCountEqual(ca["pending"], [players[0].player_id, players[1].player_id])

    def test_pay_chosen_resource_and_gain_vp(self):
        game, players = make_game(2, gold=10, strength=0, magic=0)
        fire(game, self._event(), players[0].player_id)
        game.submit_concurrent_action(players[0].player_id, "g", kind="event_self_convert")
        game.submit_concurrent_action(players[1].player_id, "skip", kind="event_self_convert")
        self.assertEqual(players[0].gold_score, 5)
        self.assertEqual(players[0].victory_score, 3)
        self.assertEqual(players[1].victory_score, 0)
        self.assertIsNone(game.concurrent_action)

    def test_cannot_pay_resource_without_funds(self):
        game, players = make_game(2, gold=10, strength=2, magic=2)
        fire(game, self._event(), players[0].player_id)
        with self.assertRaises(ValueError):
            game.submit_concurrent_action(players[0].player_id, "s", kind="event_self_convert")


# --- A Call To Arms (all may banish a Soldier for 3 VP) --------------------

class CallToArmsTests(unittest.TestCase):
    def _event(self):
        return make_event(17, "A Call To Arms",
                          activation_effect="all_may banish_owned_citizen role=soldier gain=v:3",
                          has_activation=True)

    def test_only_players_with_soldiers_participate(self):
        game, players = make_game(3)
        players[0].owned_citizens.append(make_citizen(101, soldier=1))
        players[1].owned_citizens.append(make_citizen(102, worker=1))  # no soldier
        players[2].owned_citizens.append(make_citizen(103, soldier=2))
        fire(game, self._event(), players[0].player_id)
        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca["kind"], "event_banish_citizen_for_reward")
        self.assertCountEqual(ca["pending"], [players[0].player_id, players[2].player_id])

    def test_banish_grants_vp_and_removes_citizen(self):
        game, players = make_game(2)
        soldier = make_citizen(101, soldier=1)
        players[0].owned_citizens.append(soldier)
        players[1].owned_citizens.append(make_citizen(102, soldier=1))
        fire(game, self._event(), players[0].player_id)
        game.submit_concurrent_action(players[0].player_id, "0", kind="event_banish_citizen_for_reward")
        game.submit_concurrent_action(players[1].player_id, "skip", kind="event_banish_citizen_for_reward")
        self.assertEqual(players[0].victory_score, 3)
        self.assertNotIn(soldier, players[0].owned_citizens)
        self.assertIn(soldier, game.banish_pile)
        self.assertEqual(players[1].victory_score, 0)
        self.assertEqual(len(players[1].owned_citizens), 1)

    def test_cannot_banish_non_soldier(self):
        game, players = make_game(2)
        players[0].owned_citizens.append(make_citizen(101, soldier=1))
        players[0].owned_citizens.append(make_citizen(102, worker=1))
        players[1].owned_citizens.append(make_citizen(103, soldier=1))
        fire(game, self._event(), players[0].player_id)
        with self.assertRaises(ValueError):
            game.submit_concurrent_action(players[0].player_id, "1", kind="event_banish_citizen_for_reward")


# --- A Betrayal of Bonds (all must flip a citizen) -------------------------

class BetrayalOfBondsTests(unittest.TestCase):
    def _event(self):
        return make_event(22, "A Betrayal of Bonds",
                          activation_effect="all_must flip_citizen",
                          has_activation=True)

    def test_flip_concurrent_opens_for_players_with_citizens(self):
        game, players = make_game(3)
        players[0].owned_citizens.append(make_citizen(101))
        players[1].owned_citizens.append(make_citizen(102))
        # players[2] has no citizens -> not a participant
        fire(game, self._event(), players[0].player_id)
        ca = game.concurrent_action
        self.assertIsNotNone(ca)
        self.assertEqual(ca["kind"], "flip_one_citizen")
        self.assertCountEqual(ca["pending"], [players[0].player_id, players[1].player_id])

    def test_flip_marks_citizen_face_down(self):
        game, players = make_game(2)
        c0 = make_citizen(101)
        c1 = make_citizen(102)
        players[0].owned_citizens.append(c0)
        players[1].owned_citizens.append(c1)
        fire(game, self._event(), players[0].player_id)
        game.submit_concurrent_action(players[0].player_id, "0", kind="flip_one_citizen")
        game.submit_concurrent_action(players[1].player_id, "0", kind="flip_one_citizen")
        self.assertTrue(c0.is_flipped)
        self.assertTrue(c1.is_flipped)
        self.assertIsNone(game.concurrent_action)


# --- reveal plumbing + un-exhaust recycling --------------------------------

class RevealPlumbingTests(unittest.TestCase):
    def test_reveal_fires_activation_and_marks_card_inaccessible(self):
        game, players = make_game(2, gold=10)
        ev = make_event(21, "The Key and Blade",
                        activation_effect="active_lose g 3 + others_lose g 1",
                        has_activation=True)
        game.exhausted_stack.append(ev)
        stack = game.citizen_grid[0]
        game.events.reveal_exhausted_onto_stack(stack)
        self.assertIs(stack[-1], ev)
        self.assertFalse(ev.is_accessible)   # not slayable
        self.assertTrue(ev.is_visible)
        self.assertEqual(players[0].gold_score, 7)
        self.assertEqual(players[1].gold_score, 9)

    def test_spent_event_unexhausts_back_into_deck(self):
        game, players = make_game(2)
        ev = make_event(20, "Curse of The North",
                        passive_effect="roll.on_event doubles all_lose m 3",
                        has_passive=True)
        game.exhausted_stack.append(ev)
        stack = game.citizen_grid[0]
        game.events.reveal_exhausted_onto_stack(stack)
        self.assertIs(stack[-1], ev)
        popped = game.domain_effects._unexhaust_stack_top_if_present(stack)
        self.assertTrue(popped)
        self.assertEqual(stack, [])
        self.assertIn(ev, game.exhausted_stack)

    def test_monster_event_not_unexhausted(self):
        game, players = make_game(2)
        ev = make_event(2, "Giant Leech", is_monster=1)
        ev.toggle_visibility(True)
        ev.toggle_accessibility(True)
        stack = game.monster_grid[0]
        stack.append(ev)
        popped = game.domain_effects._unexhaust_stack_top_if_present(stack)
        self.assertFalse(popped)
        self.assertIs(stack[-1], ev)


# --- deferred activation queue ---------------------------------------------

class DeferredActivationTests(unittest.TestCase):
    def test_activation_queued_when_engine_busy(self):
        game, players = make_game(2, gold=10)
        # Simulate a pending per-player prompt (engine busy).
        game.action_required = {"id": players[0].player_id, "action": "choose_player"}
        ev = make_event(21, "The Key and Blade",
                        activation_effect="active_lose g 3 + others_lose g 1",
                        has_activation=True)
        game.exhausted_stack.append(ev)
        game.events.reveal_exhausted_onto_stack(game.citizen_grid[0])
        # Not fired yet — queued.
        self.assertEqual(players[0].gold_score, 10)
        self.assertEqual(len(game.pending_event_activations), 1)
        # Once the prompt clears, draining fires it.
        game.action_required = {"id": game.game_id, "action": ""}
        game.events.drain_pending_event_activations()
        self.assertEqual(players[0].gold_score, 7)
        self.assertEqual(game.pending_event_activations, [])


class SaveLoadTests(unittest.TestCase):
    def test_revealed_event_and_pending_queue_round_trip(self):
        from game_serialization import serialize_game_to_save_dict, deserialize_save_dict_to_game

        game, players = make_game(2, gold=10)
        ev = make_event(20, "Curse of The North",
                        passive_effect="roll.on_event doubles all_lose m 3",
                        has_passive=True)
        game.exhausted_stack.append(ev)
        game.events.reveal_exhausted_onto_stack(game.citizen_grid[0])
        game.pending_event_activations.append({
            "event_id": 21, "name": "The Key and Blade",
            "activation_effect": "active_lose g 3 + others_lose g 1",
            "revealing_player_id": players[0].player_id,
        })

        blob = serialize_game_to_save_dict(game)
        restored = deserialize_save_dict_to_game(blob)

        top = restored.citizen_grid[0][-1]
        self.assertEqual(getattr(top, "name", None), "Curse of The North")
        self.assertFalse(top.is_accessible)
        self.assertEqual(len(restored.pending_event_activations), 1)
        self.assertEqual(restored.pending_event_activations[0]["name"], "The Key and Blade")
        # Passive still scannable after load.
        restored.roll_events = ["doubles"]
        restored.events.apply_board_event_passive_roll_effects()
        for p in restored.player_list:
            self.assertEqual(p.magic_score, 7)


if __name__ == "__main__":
    unittest.main()
