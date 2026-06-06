import unittest

from cards import Citizen, Event, Starter
from game import Game
from game_models import Player


def make_no_payout_starter(starter_id, gold_on=1, gold_off=1):
    """A -1/-1 starter with a flat `no_payout`/`doubles` gold payout.

    Mirrors Herald/Margrave's activation gate (never roll-matches; fires on
    the doubles and end-of-harvest no_payout outcomes) with a non-interactive
    flat payout so the harvest stays automatic.
    """
    return Starter(
        starter_id, "Test Slot Starter", -1, -1,
        gold_on, gold_off,
        0, 0, 0, 0,
        False, False, "", "",
        "test",
        "doubles_or_no_payout",
    )


def make_match1_citizen(citizen_id, gold_on=2, gold_off=1):
    """Citizen that pays gold on roll_match1=1; everything else zeroed.

    Constructor positional args (see cards.Citizen.__init__):
      citizen_id, name, gold_cost, roll_match1, roll_match2,
      shadow, holy, soldier, worker,
      g_on, g_off, s_on, s_off, m_on, m_off, vp_on, vp_off,
      has_sp_on, has_sp_off, sp_on, sp_off, special_citizen, expansion
    """
    return Citizen(
        citizen_id, f"Citizen {citizen_id}",
        2,        # gold_cost
        1, 0,     # roll_match1, roll_match2
        0, 0, 0, 0,
        gold_on, gold_off,
        0, 0, 0, 0, 0, 0,
        False, False, "", "",
        False, "test",
    )


def make_n_player_game(n, turn_index=0, with_match_citizens=True):
    players = []
    for i in range(n):
        p = Player(f"p{i+1}", f"Player {i+1}")
        # Zero starting resources so harvest deltas read as absolute gold scores.
        p.gold_score = 0
        p.strength_score = 0
        p.magic_score = 0
        p.victory_score = 0
        if with_match_citizens:
            p.owned_citizens.append(make_match1_citizen(100 + i))
        players.append(p)
    game = Game({
        "game_id": "test-game",
        "player_list": players,
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "test-game", "action": ""},
        "game_log": [],
        "turn_index": turn_index,
        "phase": "harvest",
    })
    return game, players


class FivePlayerRestingTests(unittest.TestCase):
    def test_resting_player_id_rotates_with_active_seat(self):
        game, players = make_n_player_game(5, turn_index=0)
        # Active = p1 (idx 0); resting = p5 (idx (0 - 1) % 5 == 4).
        self.assertEqual(game.resting_player_id(), players[4].player_id)
        game.turn_index = 1
        self.assertEqual(game.resting_player_id(), players[0].player_id)
        game.turn_index = 2
        self.assertEqual(game.resting_player_id(), players[1].player_id)
        game.turn_index = 3
        self.assertEqual(game.resting_player_id(), players[2].player_id)
        game.turn_index = 4
        self.assertEqual(game.resting_player_id(), players[3].player_id)

    def test_resting_player_is_none_at_other_player_counts(self):
        for n in (2, 3, 4, 6):
            game, _players = make_n_player_game(n, turn_index=0, with_match_citizens=False)
            self.assertIsNone(game.resting_player_id(), f"Expected None for {n} players")

    def test_resting_player_skips_silent_harvest(self):
        game, players = make_n_player_game(5, turn_index=0)

        game.harvest_phase()

        self.assertEqual(players[0].gold_score, 2, "Active player gets on-turn payout")
        self.assertEqual(players[1].gold_score, 1, "Off-turn player harvests")
        self.assertEqual(players[2].gold_score, 1, "Off-turn player harvests")
        self.assertEqual(players[3].gold_score, 1, "Off-turn player harvests")
        self.assertEqual(players[4].gold_score, 0, "Resting player skips harvest")

    def test_harvest_player_order_excludes_resting_seat(self):
        game, players = make_n_player_game(5, turn_index=2)

        order = game._harvest_player_id_order_starting_active()

        self.assertEqual(len(order), 4)
        self.assertEqual(order[0], players[2].player_id, "Active player first")
        # Active=p3 (idx 2), resting=p2 (idx 1). Order around the table excluding p2:
        # p3, p4, p5, p1.
        self.assertEqual(order, [
            players[2].player_id,
            players[3].player_id,
            players[4].player_id,
            players[0].player_id,
        ])
        self.assertNotIn(players[1].player_id, order)

    def test_resting_seat_excluded_from_no_payout_starter_payout(self):
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=False)
        # Every player owns a flat no_payout starter; nobody has dice-matching
        # cards, so the end-of-harvest no_payout leg fires its depicted payout.
        for p in players:
            p.owned_starters.append(make_no_payout_starter(200 + int(p.player_id[1:])))

        game.advance_tick()

        self.assertEqual(players[0].gold_score, 1,
                         "Active player's no_payout starter pays its on-turn amount")
        for p in players[1:4]:
            self.assertEqual(p.gold_score, 1,
                             "Off-turn players' no_payout starter pays out")
        self.assertEqual(players[4].gold_score, 0,
                         "Resting player's no_payout starter must not fire")

    def test_no_slot_starter_means_nothing_on_no_payout(self):
        # A board with no -1/-1 starter at all: the no_payout outcome grants
        # nothing and opens no consolation prompt.
        game, players = make_n_player_game(4, turn_index=0, with_match_citizens=False)

        game.advance_tick()

        self.assertIsNone(game.concurrent_action)
        for p in players:
            self.assertEqual(p.gold_score, 0)
            self.assertEqual(p.strength_score, 0)
            self.assertEqual(p.magic_score, 0)

    def test_four_player_game_has_no_resting_seat(self):
        game, players = make_n_player_game(4, turn_index=0)

        order = game._harvest_player_id_order_starting_active()

        self.assertEqual(len(order), 4)
        self.assertEqual(set(order), {p.player_id for p in players})
        self.assertIsNone(game.resting_player_id())


def make_all_lose_event(amount=2, resource="g"):
    e = Event(
        9000, "Test Plague",
        2,                      # roll_match1
        f"all_lose {resource} {amount}",
        True,                   # has_roll_effect
        False,                  # is_monster
        False, False, "", "",   # activation/passive
        0, 0,                   # strength_cost, magic_cost
        "Plague",               # monster_type
        0, 0, 0, 0,             # rewards
        False, "",              # has_special_reward, special_reward
        "test",
    )
    return e


class RestingNegativeEffectImmunityTests(unittest.TestCase):
    """The resting seat is "not in play" for negative citizen / domain / monster
    / event effects. These tests verify that the resting seat is filtered out
    of every player-targeting candidate list across the engine.
    """

    def test_helper_rejects_resting_seat_at_5_players(self):
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=False)
        # Resting at turn_index=0 is players[4].
        self.assertFalse(game._player_is_negative_effect_target(players[4]))
        self.assertFalse(game._player_is_negative_effect_target(players[4].player_id))
        for p in players[:4]:
            self.assertTrue(game._player_is_negative_effect_target(p))

    def test_helper_allows_everyone_at_4_players(self):
        game, players = make_n_player_game(4, turn_index=0, with_match_citizens=False)
        for p in players:
            self.assertTrue(game._player_is_negative_effect_target(p))

    def test_steal_excludes_resting_victim(self):
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=False)
        # Give every non-active player some gold so they would be valid victims
        # in absence of the resting rule.
        for p in players[1:]:
            p.gold_score = 5

        active = players[0].player_id
        game.harvest._execute_steal_payout("steal g 1", active)

        prc = game.pending_required_choice or {}
        victim_ids = [opt.get("victim_id") for opt in (prc.get("victim_options") or [])]
        self.assertEqual(set(victim_ids), {players[1].player_id, players[2].player_id, players[3].player_id})
        self.assertNotIn(players[4].player_id, victim_ids,
                         "Resting seat must not appear in steal victim options")

    def test_all_lose_event_skips_resting_player(self):
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=False)
        for p in players:
            p.gold_score = 5

        evt = make_all_lose_event(amount=2, resource="g")
        game.dice._execute_event_roll_effect(evt, players[0].player_id)

        for p in players[:4]:
            self.assertEqual(p.gold_score, 3, f"{p.player_id} should have lost 2 gold")
        self.assertEqual(players[4].gold_score, 5,
                         "Resting seat must not lose resources to negative events")

    def test_concurrent_flip_excludes_resting_player(self):
        # Every player has an unflipped citizen, but only the non-resting four
        # should be prompted for the Cursed Cavern flip.
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=True)

        game.dice._begin_concurrent_flip_one_citizen(players[0].player_id)

        ca = game.concurrent_action or {}
        pending = list(ca.get("pending") or [])
        self.assertEqual(set(pending), {p.player_id for p in players[:4]})
        self.assertNotIn(players[4].player_id, pending,
                         "Resting seat must not be a Cursed Cavern target")

    def test_targeted_flip_excludes_resting_player(self):
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=True)

        active = players[0].player_id
        game.payouts._execute_flip_citizen_payout("flip_citizen targeted", active)

        prc = game.pending_required_choice or {}
        opt_ids = [opt.get("player_id") for opt in (prc.get("options") or [])]
        self.assertEqual(set(opt_ids), {players[1].player_id, players[2].player_id, players[3].player_id})
        self.assertNotIn(players[4].player_id, opt_ids)

    def test_sunder_bay_excludes_resting_player(self):
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=True)

        active = players[0].player_id
        game.payouts._execute_banish_player_citizen_payout(active)

        prc = game.pending_required_choice or {}
        opt_ids = [opt.get("player_id") for opt in (prc.get("options") or [])]
        self.assertEqual(set(opt_ids), {players[1].player_id, players[2].player_id, players[3].player_id})
        self.assertNotIn(players[4].player_id, opt_ids)

    def test_manipulate_take_excludes_resting_but_pay_does_not(self):
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=False)
        for p in players[1:]:
            p.gold_score = 3

        kv = {"take": "g:1"}
        parsed_take, _ = game.domain_effects._manipulate_candidates_other_players(
            players[0].player_id, "take", kv,
        )
        take_ids = [o["player_id"] for o in (parsed_take or {}).get("options", [])]
        self.assertEqual(set(take_ids), {players[1].player_id, players[2].player_id, players[3].player_id})
        self.assertNotIn(players[4].player_id, take_ids)

        # pay_to_player is a positive effect for the target — resting must NOT be filtered.
        kv_pay = {"pay": "g:1"}
        parsed_pay, _ = game.domain_effects._manipulate_candidates_other_players(
            players[0].player_id, "pay", kv_pay,
        )
        pay_ids = [o["player_id"] for o in (parsed_pay or {}).get("options", [])]
        self.assertIn(players[4].player_id, pay_ids,
                      "Resting seat is still a valid pay_to_player target (positive effect)")
        self.assertEqual(set(pay_ids), {p.player_id for p in players[1:]})

    def test_take_owned_card_excludes_resting_player(self):
        # Every non-active player has a citizen. take_owned_card must skip resting.
        game, players = make_n_player_game(5, turn_index=0, with_match_citizens=True)

        active_player = game._player_by_id(players[0].player_id)
        game.domain_effects._prompt_take_owned_card(
            active_player,
            "Test Domain",
            {"kind": "citizen", "pick": "random", "optional": False},
        )

        prc = game.pending_required_choice or {}
        opt_ids = [opt.get("player_id") for opt in (prc.get("options") or [])]
        self.assertEqual(set(opt_ids), {players[1].player_id, players[2].player_id, players[3].player_id})
        self.assertNotIn(players[4].player_id, opt_ids)


if __name__ == "__main__":
    unittest.main()
