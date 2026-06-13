"""Tests for the optional Relics module: inclusion gating, dealing, and the
post-duke relic-selection concurrent gate.

These mirror the Agents tests (`tests/test_game_agents.py`). The selection-flow
tests build minimal in-memory games and need no DB; the dealing tests load
canonical relic rows from the live DB and skip when the tunnel is down."""

import contextlib
import importlib.util
import io
import socket
import unittest
from unittest.mock import patch

from cards import Citizen, Domain, Duke, Monster, Relic
from game import Game
from game_models import LobbyMember, Player
from game_serialization import (
    serialize_game_to_save_dict,
    deserialize_save_dict_to_game,
)
from game_setup import (
    load_game_data,
    _should_include_relics,
    _relic_count_per_player,
)


def _db_ready():
    if importlib.util.find_spec("mariadb") is None:
        return False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.25)
    try:
        return sock.connect_ex(("127.0.0.1", 3306)) == 0
    finally:
        sock.close()


def _make_duke(duke_id, name="Duke"):
    return Duke(duke_id, name, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "base")


def _make_relic(relic_id, name="Relic"):
    return Relic(relic_id, name, None, f"{name} power text.")


def _make_citizen(citizen_id, name="Citizen", *, gold_cost=0,
                  shadow=0, holy=0, soldier=0, worker=0):
    card = Citizen(
        citizen_id,
        name,
        gold_cost,
        2, 0,
        shadow, holy, soldier, worker,
        0, 0,
        0, 0,
        0, 0,
        0, 0,
        False,
        False,
        "",
        "",
        False,
        "base",
    )
    card.toggle_visibility(True)
    card.toggle_accessibility(True)
    return card


def _make_domain(domain_id, name="Domain", *, gold_cost=0,
                 shadow=0, holy=0, soldier=0, worker=0, vp_reward=0):
    card = Domain(
        domain_id,
        name,
        gold_cost,
        shadow, holy, soldier, worker,
        vp_reward,
        False,
        False,
        "",
        "",
        "",
        "base",
    )
    card.toggle_visibility(True)
    card.toggle_accessibility(True)
    return card


def _make_monster(monster_id, name="Monster", *, strength_cost=0, magic_cost=0,
                  vp_reward=0, monster_type="Minion"):
    card = Monster(
        monster_id,
        name,
        "Forest",
        monster_type,
        1,
        strength_cost,
        magic_cost,
        vp_reward,
        0, 0, 0,
        False,
        "",
        False,
        "",
        False,
        "base",
    )
    card.toggle_visibility(True)
    card.toggle_accessibility(True)
    return card


def _make_setup_game(*, relics_per_player=2, dukes_per_player=2, include_relics=True,
                     n_players=2):
    """A fresh game sitting in setup with each player holding several dukes and
    (optionally) relics, so Game.__init__ opens the choose_duke gate."""
    players = []
    for i in range(1, n_players + 1):
        p = Player(f"p{i}", f"Player {i}")
        p.owned_dukes = [_make_duke(100 * i + j, f"Duke{i}-{j}") for j in range(dukes_per_player)]
        p.owned_relics = [_make_relic(10 * i + j, f"Relic{i}-{j}") for j in range(relics_per_player)]
        players.append(p)
    return Game({
        "game_id": "relics-setup",
        "preset": "base",
        "include_relics": include_relics,
        "player_list": players,
        "monster_grid": [[] for _ in range(5)],
        "monster_stack_areas": [],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": [[] for _ in range(5)],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
        "action_required": {"id": "relics-setup", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "setup",
        "actions_remaining": 0,
    })


def _make_action_game(*, active="p1", turn_number=3, phase="action", relic_used_turn=None,
                      p1_has_relic=True):
    """A 2-player game in the action phase with each player holding one kept
    relic, for exercising the once-per-turn relic-use gate."""
    p1 = Player("p1", "Player 1")
    if p1_has_relic:
        p1.owned_relics = [_make_relic(5, "Gold Bastion")]
    p2 = Player("p2", "Player 2")
    p2.owned_relics = [_make_relic(6, "Lich Sword")]
    return Game({
        "game_id": "relics-action",
        "preset": "base",
        "include_relics": True,
        "player_list": [p1, p2],
        "monster_grid": [[] for _ in range(5)],
        "monster_stack_areas": [],
        "citizen_grid": [[] for _ in range(10)],
        "domain_grid": [[] for _ in range(5)],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
        "action_required": {"id": active, "action": "standard_action"},
        "game_log": [],
        "turn_index": 0 if active == "p1" else 1,
        "turn_number": turn_number,
        "phase": phase,
        "actions_remaining": 2,
        "relic_used_turn": relic_used_turn or {},
    })


def _make_effect_game(effect, name="Relic", *, player_resources=None, turn_number=3,
                      citizen_grid=None, domain_grid=None, monster_grid=None,
                      consumes_action=False, actions_remaining=2):
    """A 2-player action-phase game where p1 holds one kept relic carrying a real
    effect string, for exercising group-1 resource powers."""
    p1 = Player("p1", "Player 1")
    p1.owned_relics = [Relic(5, name, effect, f"{name} power text.", consumes_action=consumes_action)]
    for k, v in (player_resources or {}).items():
        setattr(p1, k, v)
    p2 = Player("p2", "Player 2")
    return Game({
        "game_id": "relics-effect",
        "preset": "base",
        "include_relics": True,
        "player_list": [p1, p2],
        "monster_grid": monster_grid if monster_grid is not None else [[] for _ in range(5)],
        "monster_stack_areas": [],
        "citizen_grid": citizen_grid if citizen_grid is not None else [[] for _ in range(10)],
        "domain_grid": domain_grid if domain_grid is not None else [[] for _ in range(5)],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
        "action_required": {"id": "p1", "action": "standard_action"},
        "game_log": [],
        "turn_index": 0,
        "turn_number": turn_number,
        "phase": "action",
        "actions_remaining": actions_remaining,
        "relic_used_turn": {},
    })


class RelicResourceEffectTests(unittest.TestCase):
    def test_gold_bastion_grants_strength_and_gold(self):
        game = _make_effect_game("s 1 + g 1", "Gold Bastion",
                                 player_resources={"strength_score": 0, "gold_score": 0})
        game.use_relic("p1")
        p1 = game.player_list[0]
        self.assertEqual(p1.strength_score, 1)
        self.assertEqual(p1.gold_score, 1)

    def test_gold_bastion_always_available_no_cost(self):
        game = _make_effect_game("s 1 + g 1", "Gold Bastion")
        self.assertTrue(game.relic_available_for("p1"))

    def test_lich_sword_pays_strength_gains_magic(self):
        game = _make_effect_game("s -1 + m 3", "Lich Sword",
                                 player_resources={"strength_score": 2, "magic_score": 0})
        game.use_relic("p1")
        p1 = game.player_list[0]
        self.assertEqual(p1.strength_score, 1)
        self.assertEqual(p1.magic_score, 3)

    def test_lich_sword_unaffordable_blocks_glow_and_use(self):
        game = _make_effect_game("s -1 + m 3", "Lich Sword",
                                 player_resources={"strength_score": 0})
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_philosophers_tome_trades_magic_for_gold_and_vp(self):
        game = _make_effect_game("m -4 + g 3 + v 1", "Philosopher's Tome",
                                 player_resources={"magic_score": 5, "gold_score": 0,
                                                   "victory_score": 0})
        game.use_relic("p1")
        p1 = game.player_list[0]
        self.assertEqual(p1.magic_score, 1)
        self.assertEqual(p1.gold_score, 3)
        self.assertEqual(p1.victory_score, 1)

    def test_philosophers_tome_unaffordable_blocks_use(self):
        game = _make_effect_game("m -4 + g 3 + v 1", "Philosopher's Tome",
                                 player_resources={"magic_score": 3})
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_effect_relic_used_once_per_turn(self):
        game = _make_effect_game("s 1 + g 1", "Gold Bastion",
                                 player_resources={"strength_score": 0, "gold_score": 0})
        game.use_relic("p1")
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")
        # The effect applied exactly once.
        self.assertEqual(game.player_list[0].strength_score, 1)
        self.assertEqual(game.player_list[0].gold_score, 1)


class RelicBanishGainEffectTests(unittest.TestCase):
    def test_dragon_orb_banishes_owned_monster_and_gains_gold(self):
        game = _make_effect_game("banish_owned monster + g 5", "Dragon Orb",
                                 player_resources={"gold_score": 0},
                                 consumes_action=True)
        p1 = game.player_list[0]
        monster = _make_monster(80, "Ogre")
        p1.owned_monsters = [monster]

        self.assertTrue(game.relic_available_for("p1"))
        game.use_relic("p1")
        self.assertEqual(game.action_required.get("action"), "choose_owned_card")
        self.assertEqual(game.pending_required_choice.get("kind"), "banish_owned_card")
        self.assertEqual(game.pending_required_choice.get("card_kind"), "monster")

        game.act_on_required_action("p1", "choose_owned_card 1")
        self.assertEqual(p1.owned_monsters, [])
        self.assertIn(monster, game.banish_pile)
        self.assertEqual(p1.gold_score, 5)

    def test_dragon_orb_unavailable_without_owned_monster(self):
        game = _make_effect_game("banish_owned monster + g 5", "Dragon Orb",
                                 consumes_action=True)
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_staff_of_urdr_banishes_owned_citizen_and_gains_magic(self):
        game = _make_effect_game("banish_owned citizen + m 4", "Staff of Urdr",
                                 player_resources={"magic_score": 0},
                                 consumes_action=True)
        p1 = game.player_list[0]
        citizen = _make_citizen(81, "Scribe")
        p1.owned_citizens = [citizen]

        self.assertTrue(game.relic_available_for("p1"))
        game.use_relic("p1")
        self.assertEqual(game.action_required.get("action"), "choose_owned_card")
        self.assertEqual(game.pending_required_choice.get("kind"), "banish_owned_card")
        self.assertEqual(game.pending_required_choice.get("card_kind"), "citizen")

        game.act_on_required_action("p1", "choose_owned_card 1")
        self.assertEqual(p1.owned_citizens, [])
        self.assertIn(citizen, game.banish_pile)
        self.assertEqual(p1.magic_score, 4)

    def test_staff_of_urdr_unavailable_without_owned_citizen(self):
        game = _make_effect_game("banish_owned citizen + m 4", "Staff of Urdr",
                                 consumes_action=True)
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_fire_lance_banishes_center_minion_and_gains_gold(self):
        minion = _make_monster(82, "Goblin", monster_type="Minion")
        titan = _make_monster(83, "Giant", monster_type="Titan")
        grid = [[minion], [titan]] + [[] for _ in range(3)]
        game = _make_effect_game("banish_center monster type=minion + g 2", "Fire Lance",
                                 player_resources={"gold_score": 0},
                                 monster_grid=grid, consumes_action=True)
        p1 = game.player_list[0]

        self.assertTrue(game.relic_available_for("p1"))
        game.use_relic("p1")
        prc = game.pending_required_choice
        self.assertEqual(game.action_required.get("action"), "choose_owned_card")
        self.assertEqual(prc.get("kind"), "banish_center_card")
        self.assertEqual(prc.get("card_kind"), "monster")
        self.assertEqual([o["name"] for o in prc["options"]], ["Goblin"])

        game.act_on_required_action("p1", "choose_owned_card 1")
        self.assertEqual(game.monster_grid[0], [])
        self.assertEqual(game.monster_grid[1], [titan])
        self.assertIn(minion, game.banish_pile)
        self.assertEqual(p1.gold_score, 2)

    def test_fire_lance_unavailable_without_center_minion(self):
        grid = [[_make_monster(83, "Giant", monster_type="Titan")]] + [[] for _ in range(4)]
        game = _make_effect_game("banish_center monster type=minion + g 2", "Fire Lance",
                                 monster_grid=grid, consumes_action=True)
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")


class RelicThunderAxeTests(unittest.TestCase):
    """Thunder Axe: a passive slay-cost reducer. When slaying, the owner may
    ignore up to 3 face-value Magic OR 1 face-value Strength. The waiver caps at
    the monster's printed cost (never magic spent as wild Strength)."""

    DISCOUNT = "action.slay_discount magic=3 strength=1"

    def _slay_game(self, monster, *, resources=None, name="Thunder Axe", effect=None):
        eff = effect if effect is not None else self.DISCOUNT
        grid = [[monster]] + [[] for _ in range(4)]
        return _make_effect_game(eff, name, player_resources=resources or {}, monster_grid=grid)

    def test_discount_caps_exposed(self):
        game = self._slay_game(_make_monster(70, "Imp", magic_cost=3))
        p1 = game.player_list[0]
        self.assertEqual(game.relics.relic_slay_discount(p1), {"magic": 3, "strength": 1})

    def test_passive_relic_not_click_usable(self):
        game = self._slay_game(_make_monster(70, "Imp", magic_cost=3))
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_magic_waiver_ignores_face_magic(self):
        monster = _make_monster(70, "Imp", magic_cost=3, strength_cost=0)
        game = self._slay_game(monster, resources={"magic_score": 0, "strength_score": 0})
        game.slay_monster("p1", 70, sp=0, mp=0, thunder_axe="magic")
        self.assertEqual([m.name for m in game.player_list[0].owned_monsters], ["Imp"])

    def test_magic_waiver_partial_when_face_below_cap(self):
        monster = _make_monster(70, "Imp", magic_cost=2, strength_cost=0)
        game = self._slay_game(monster, resources={"magic_score": 0, "strength_score": 0})
        game.slay_monster("p1", 70, sp=0, mp=0, thunder_axe="magic")
        self.assertEqual(len(game.player_list[0].owned_monsters), 1)

    def test_strength_waiver_ignores_one_strength(self):
        monster = _make_monster(70, "Ogre", strength_cost=3, magic_cost=0)
        game = self._slay_game(monster, resources={"strength_score": 2, "magic_score": 0})
        game.slay_monster("p1", 70, sp=2, mp=0, thunder_axe="strength")
        self.assertEqual(len(game.player_list[0].owned_monsters), 1)

    def test_magic_waiver_unusable_without_face_magic(self):
        # Strength-only monster: the magic option yields no reduction (face Magic
        # is 0), so paying nothing must still fail — the wild Magic-as-Strength
        # cost cannot be waived.
        monster = _make_monster(70, "Ogre", strength_cost=3, magic_cost=0)
        game = self._slay_game(monster, resources={"strength_score": 0, "magic_score": 0})
        with self.assertRaises(ValueError):
            game.slay_monster("p1", 70, sp=0, mp=0, thunder_axe="magic")
        self.assertEqual(game.player_list[0].owned_monsters, [])

    def test_strength_waiver_does_not_cover_full_cost(self):
        # 3-strength monster, only 1 waived: paying 1 strength is still short.
        monster = _make_monster(70, "Ogre", strength_cost=3, magic_cost=0)
        game = self._slay_game(monster, resources={"strength_score": 1, "magic_score": 0})
        with self.assertRaises(ValueError):
            game.slay_monster("p1", 70, sp=1, mp=0, thunder_axe="strength")
        self.assertEqual(game.player_list[0].owned_monsters, [])

    def test_requires_ownership(self):
        monster = _make_monster(70, "Imp", magic_cost=3, strength_cost=0)
        game = self._slay_game(monster, resources={"magic_score": 0, "strength_score": 0},
                               name="Gold Bastion", effect="s 1 + g 1")
        with self.assertRaises(ValueError):
            game.slay_monster("p1", 70, sp=0, mp=0, thunder_axe="magic")
        self.assertEqual(game.player_list[0].owned_monsters, [])

    def test_no_waiver_still_requires_full_payment(self):
        monster = _make_monster(70, "Imp", magic_cost=3, strength_cost=0)
        game = self._slay_game(monster, resources={"magic_score": 0, "strength_score": 0})
        with self.assertRaises(ValueError):
            game.slay_monster("p1", 70, sp=0, mp=0)
        self.assertEqual(game.player_list[0].owned_monsters, [])

    def test_immediate_slay_prompt_carries_face_costs(self):
        monster = _make_monster(70, "Imp", magic_cost=3, strength_cost=1)
        game = self._slay_game(monster, resources={"magic_score": 0, "strength_score": 0})
        game.slay._open_immediate_slay_prompt("p1", "Test Effect")
        game.act_on_required_action("p1", "choose_monster_slay 1")
        prc = game.pending_required_choice
        self.assertEqual(prc.get("stage"), "pay_for_slay")
        self.assertEqual(prc.get("face_magic_cost"), 3)
        self.assertEqual(prc.get("face_strength_cost"), 1)

    def test_immediate_slay_applies_thunder_axe_magic(self):
        monster = _make_monster(70, "Imp", magic_cost=3, strength_cost=0)
        game = self._slay_game(monster, resources={"magic_score": 0, "strength_score": 0})
        game.slay._open_immediate_slay_prompt("p1", "Test Effect")
        game.act_on_required_action("p1", "choose_monster_slay 1")
        # Pay nothing thanks to the magic waiver (3 face Magic ignored).
        game.act_on_required_action("p1", "slay_pay 0 0 0 0 0 0 axe:magic")
        self.assertEqual([m.name for m in game.player_list[0].owned_monsters], ["Imp"])

    def test_immediate_slay_thunder_axe_magic_unusable_without_face_magic(self):
        monster = _make_monster(70, "Ogre", strength_cost=3, magic_cost=0)
        game = self._slay_game(monster, resources={"magic_score": 0, "strength_score": 0})
        game.slay._open_immediate_slay_prompt("p1", "Test Effect")
        game.act_on_required_action("p1", "choose_monster_slay 1")
        # Magic waiver does nothing on a 0-face-Magic monster; the prompt stays open.
        game.act_on_required_action("p1", "slay_pay 0 0 0 0 0 0 axe:magic")
        self.assertEqual(game.action_required.get("action"), "slay_monster_payment")
        self.assertEqual(game.player_list[0].owned_monsters, [])


class RelicWildExchangeEffectTests(unittest.TestCase):
    """Treant Chest: pay 3 of any one resource, gain 5 of any one resource."""

    def test_unusable_without_three_of_any_resource(self):
        game = _make_effect_game("exchange wild 3 wild 5", "Treant Chest",
                                 player_resources={"gold_score": 2, "strength_score": 2,
                                                   "magic_score": 2})
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_usable_with_three_of_one_resource(self):
        game = _make_effect_game("exchange wild 3 wild 5", "Treant Chest",
                                 player_resources={"gold_score": 0, "strength_score": 0,
                                                   "magic_score": 3})
        self.assertTrue(game.relic_available_for("p1"))

    def test_pay_options_only_include_resources_with_three(self):
        game = _make_effect_game("exchange wild 3 wild 5", "Treant Chest",
                                 player_resources={"gold_score": 5, "strength_score": 2,
                                                   "magic_score": 3})
        game.use_relic("p1")
        self.assertEqual(game.action_required.get("action"), "relic_wild_exchange")
        prc = game.pending_required_choice
        self.assertEqual(prc.get("stage"), "pay")
        self.assertEqual({o["resource"] for o in prc["cost_options"]}, {"g", "m"})
        self.assertFalse(game.relic_available_for("p1"))

    def test_pay_then_gain_different_resources(self):
        game = _make_effect_game("exchange wild 3 wild 5", "Treant Chest",
                                 player_resources={"gold_score": 0, "strength_score": 0,
                                                   "magic_score": 4})
        game.use_relic("p1")
        game.act_on_required_action("p1", "relic_pay m")
        p1 = game.player_list[0]
        self.assertEqual(p1.magic_score, 1)
        self.assertEqual(game.pending_required_choice.get("stage"), "gain")
        game.act_on_required_action("p1", "relic_gain g")
        self.assertEqual(p1.gold_score, 5)
        self.assertEqual(p1.magic_score, 1)
        self.assertNotEqual(game.action_required.get("action"), "relic_wild_exchange")

    def test_pay_and_gain_same_resource_nets_positive(self):
        game = _make_effect_game("exchange wild 3 wild 5", "Treant Chest",
                                 player_resources={"gold_score": 3, "strength_score": 0,
                                                   "magic_score": 0})
        game.use_relic("p1")
        game.act_on_required_action("p1", "relic_pay g")
        self.assertEqual(game.player_list[0].gold_score, 0)
        game.act_on_required_action("p1", "relic_gain g")
        self.assertEqual(game.player_list[0].gold_score, 5)

    def test_invalid_pay_resource_is_ignored(self):
        game = _make_effect_game("exchange wild 3 wild 5", "Treant Chest",
                                 player_resources={"gold_score": 0, "strength_score": 0,
                                                   "magic_score": 3})
        game.use_relic("p1")
        # Strength has only 0; paying it is not an option and must be ignored.
        game.act_on_required_action("p1", "relic_pay s")
        self.assertEqual(game.pending_required_choice.get("stage"), "pay")
        self.assertEqual(game.player_list[0].magic_score, 3)

    def test_used_once_per_turn_after_full_flow(self):
        game = _make_effect_game("exchange wild 3 wild 5", "Treant Chest",
                                 player_resources={"gold_score": 0, "strength_score": 0,
                                                   "magic_score": 3})
        game.use_relic("p1")
        game.act_on_required_action("p1", "relic_pay m")
        game.act_on_required_action("p1", "relic_gain s")
        self.assertEqual(game.player_list[0].strength_score, 5)
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_save_load_round_trip_mid_exchange(self):
        game = _make_effect_game("exchange wild 3 wild 5", "Treant Chest",
                                 player_resources={"gold_score": 0, "strength_score": 0,
                                                   "magic_score": 3})
        game.use_relic("p1")
        game.act_on_required_action("p1", "relic_pay m")
        reloaded = deserialize_save_dict_to_game(serialize_game_to_save_dict(game))
        self.assertEqual(reloaded.action_required.get("action"), "relic_wild_exchange")
        self.assertEqual(reloaded.pending_required_choice.get("stage"), "gain")
        reloaded.act_on_required_action("p1", "relic_gain g")
        self.assertEqual(reloaded.player_list[0].gold_score, 5)


class RelicDomainPassiveTests(unittest.TestCase):
    """Evermap (ignore 1 missing role icon when building) and Violet Ring (+2 VP
    on buying a Domain). Both are passive/triggered, not click-to-use."""

    def _build_game(self, relic_effect, relic_name, domain, *, citizens=None):
        p1 = Player("p1", "Player 1")
        p1.gold_score = 10
        p1.strength_score = 10
        p1.magic_score = 10
        p1.victory_score = 0
        p1.owned_relics = [Relic(3, relic_name, relic_effect, f"{relic_name} text.")]
        p1.owned_citizens = list(citizens or [])
        p2 = Player("p2", "Player 2")
        game = Game({
            "game_id": "relics-domain",
            "preset": "base",
            "include_relics": True,
            "player_list": [p1, p2],
            "monster_grid": [[] for _ in range(5)],
            "monster_stack_areas": [],
            "citizen_grid": [[] for _ in range(10)],
            "domain_grid": [[domain], [], [], [], []],
            "die_one": 1, "die_two": 2, "die_sum": 3,
            "exhausted_count": 0,
            "exhausted_stack": [],
            "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
            "action_required": {"id": "p1", "action": "standard_action"},
            "game_log": [],
            "turn_index": 0,
            "turn_number": 1,
            "phase": "action",
            "actions_remaining": 3,
            "relic_used_turn": {},
        })
        return game, p1

    def test_evermap_allows_build_missing_exactly_one_icon(self):
        domain = _make_domain(99, "Keep", gold_cost=0, soldier=1)
        game, p1 = self._build_game("action.build_domain ignore_requirement 1",
                                    "Evermap", domain)
        game.player_actions.build_domain("p1", 99)
        self.assertEqual([d.name for d in p1.owned_domains], ["Keep"])

    def test_evermap_does_not_allow_missing_two_icons(self):
        domain = _make_domain(99, "Keep", gold_cost=0, soldier=2)
        game, p1 = self._build_game("action.build_domain ignore_requirement 1",
                                    "Evermap", domain)
        with self.assertRaises(ValueError):
            game.player_actions.build_domain("p1", 99)
        self.assertEqual(p1.owned_domains, [])

    def test_evermap_covers_one_missing_when_other_role_satisfied(self):
        # Needs soldier 1 + holy 1; player has the soldier, missing only holy (1).
        domain = _make_domain(99, "Keep", gold_cost=0, soldier=1, holy=1)
        game, p1 = self._build_game(
            "action.build_domain ignore_requirement 1", "Evermap", domain,
            citizens=[_make_citizen(50, "Footman", soldier=1)],
        )
        game.player_actions.build_domain("p1", 99)
        self.assertEqual(len(p1.owned_domains), 1)

    def test_without_evermap_missing_one_icon_still_fails(self):
        domain = _make_domain(99, "Keep", gold_cost=0, soldier=1)
        game, p1 = self._build_game("action.build_domain v 2", "Violet Ring", domain)
        with self.assertRaises(ValueError):
            game.player_actions.build_domain("p1", 99)
        self.assertEqual(p1.owned_domains, [])

    def test_evermap_offered_through_bonus_build(self):
        domain = _make_domain(99, "Keep", gold_cost=0, soldier=1)
        game, p1 = self._build_game("action.build_domain ignore_requirement 1",
                                    "Evermap", domain)
        game.payouts._execute_build_domain_activation_payout("p1")
        opts = (game.pending_required_choice or {}).get("options") or []
        self.assertTrue(any(int(o.get("domain_id", -1)) == 99 for o in opts))

    def test_violet_ring_grants_two_vp_on_build(self):
        domain = _make_domain(99, "Keep", gold_cost=0)
        game, p1 = self._build_game("action.build_domain v 2", "Violet Ring", domain)
        game.player_actions.build_domain("p1", 99)
        self.assertEqual(p1.victory_score, 2)

    def test_violet_ring_stacks_with_domain_vp_reward(self):
        domain = _make_domain(99, "Keep", gold_cost=0, vp_reward=1)
        game, p1 = self._build_game("action.build_domain v 2", "Violet Ring", domain)
        game.player_actions.build_domain("p1", 99)
        self.assertEqual(p1.victory_score, 3)

    def test_passive_relic_not_click_usable(self):
        domain = _make_domain(99, "Keep", gold_cost=0)
        for effect, name in (("action.build_domain v 2", "Violet Ring"),
                             ("action.build_domain ignore_requirement 1", "Evermap")):
            game, p1 = self._build_game(effect, name, domain)
            self.assertFalse(game.relic_available_for("p1"))
            with self.assertRaises(ValueError):
                game.use_relic("p1")


class RelicBonusActionEffectTests(unittest.TestCase):
    def test_mask_of_asteraten_gains_strength_and_opens_slay_prompt(self):
        grid = [[_make_monster(50, "Goblin", strength_cost=2, vp_reward=1)]] + [[] for _ in range(4)]
        game = _make_effect_game("s 1 + slay", "Mask of Asteraten",
                                 player_resources={"strength_score": 0, "magic_score": 0},
                                 monster_grid=grid)
        game.use_relic("p1")
        p1 = game.player_list[0]
        self.assertEqual(p1.strength_score, 1)
        self.assertEqual(game.action_required.get("action"), "choose_monster_slay")
        self.assertEqual(game.pending_required_choice.get("kind"), "immediate_slay")
        self.assertFalse(game.relic_available_for("p1"))

    def test_mask_of_asteraten_slay_prompt_can_be_declined(self):
        grid = [[_make_monster(50, "Goblin")]] + [[] for _ in range(4)]
        game = _make_effect_game("s 1 + slay", "Mask of Asteraten",
                                 player_resources={"strength_score": 0},
                                 monster_grid=grid)
        game.use_relic("p1")
        game.act_on_required_action("p1", "skip")
        self.assertEqual(game.player_list[0].strength_score, 1)
        self.assertNotEqual(game.action_required.get("action"), "choose_monster_slay")

    def test_st_aquilas_statue_gains_gold_and_opens_recruit_prompt(self):
        grid = [[_make_citizen(40, "Peasant", gold_cost=1)]] + [[] for _ in range(9)]
        game = _make_effect_game("g 1 + recruit", "St. Aquila's Statue",
                                 player_resources={"gold_score": 0},
                                 citizen_grid=grid)
        game.use_relic("p1")
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 1)
        self.assertEqual(game.action_required.get("action"), "may_recruit")
        self.assertEqual(game.pending_bonus_recruit, "p1")
        self.assertFalse(game.relic_available_for("p1"))

    def test_st_aquilas_statue_skips_recruit_prompt_when_no_citizens(self):
        game = _make_effect_game("g 1 + recruit", "St. Aquila's Statue",
                                 player_resources={"gold_score": 0})
        game.use_relic("p1")
        self.assertEqual(game.player_list[0].gold_score, 1)
        self.assertNotEqual(game.action_required.get("action"), "may_recruit")
        self.assertIsNone(game.pending_bonus_recruit)

    def test_st_aquilas_last_action_recruit_advances_turn(self):
        # Regression: an "as an action" relic used as the player's LAST action
        # opens a may_recruit bonus prompt; completing the bonus recruit must end
        # the turn. The server skips finish_turn when the bonus is consumed, so
        # resolve_bonus_recruit_if_consumed has to advance the seat itself.
        grid = [[_make_citizen(40, "Peasant", gold_cost=1)]] + [[] for _ in range(9)]
        game = _make_effect_game("g 1 + recruit", "St. Aquila's Statue",
                                 player_resources={"gold_score": 5},
                                 citizen_grid=grid, consumes_action=True,
                                 actions_remaining=1)
        # Mirror the server: spend the action, resolve the relic, then complete
        # the free recruit through the pending_bonus_recruit path.
        self.assertTrue(game.consume_player_action("p1", action_type="use_relic"))
        game.use_relic("p1")
        game.finish_turn_if_no_actions_remaining()
        self.assertEqual(game.action_required.get("action"), "may_recruit")

        self.assertTrue(game.consume_player_action("p1", action_type="hire_citizen"))
        game.hire_citizen("p1", 40, 1, 0, 0)
        consumed = game.resolve_bonus_recruit_if_consumed()
        self.assertTrue(consumed)
        if not consumed:
            game.finish_turn_if_no_actions_remaining()

        # The turn must have advanced off p1 rather than hanging on a cleared,
        # action-less prompt.
        self.assertEqual([c.name for c in game.player_list[0].owned_citizens], ["Peasant"])
        self.assertEqual(game.turn_index, 1)
        self.assertNotEqual(game.action_required.get("action"), "may_recruit")
        self.assertIsNone(game.pending_bonus_recruit)

    def test_cornelius_ring_gains_gold_and_opens_domain_build_prompt(self):
        grid = [[_make_domain(60, "Test Keep", gold_cost=3)]] + [[] for _ in range(4)]
        game = _make_effect_game("g 1 + build_domain", "Cornelius Ring",
                                 player_resources={"gold_score": 2, "magic_score": 0},
                                 domain_grid=grid)
        game.use_relic("p1")
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 3)
        self.assertEqual(game.action_required.get("action"), "choose_domain_to_build")
        self.assertEqual(game.pending_required_choice.get("kind"), "domain_build_opportunity")
        self.assertEqual(game.pending_required_choice["options"][0]["domain_id"], 60)
        self.assertFalse(game.relic_available_for("p1"))

    def test_cornelius_ring_build_prompt_can_build_domain(self):
        grid = [[_make_domain(60, "Test Keep", gold_cost=3)]] + [[] for _ in range(4)]
        game = _make_effect_game("g 1 + build_domain", "Cornelius Ring",
                                 player_resources={"gold_score": 2, "magic_score": 0},
                                 domain_grid=grid)
        game.use_relic("p1")
        game.act_on_required_action("p1", "build_domain_pick 1")
        self.assertEqual(game.action_required.get("action"), "build_domain_payment")
        game.act_on_required_action("p1", "build_pay 3 0 0 0 0")
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 0)
        self.assertEqual([d.name for d in p1.owned_domains], ["Test Keep"])
        self.assertNotIn(game.action_required.get("action"),
                         ("build_domain_payment", "choose_domain_to_build"))

    def test_cornelius_ring_no_affordable_domain_keeps_gold(self):
        grid = [[_make_domain(60, "Test Keep", gold_cost=5)]] + [[] for _ in range(4)]
        game = _make_effect_game("g 1 + build_domain", "Cornelius Ring",
                                 player_resources={"gold_score": 1, "magic_score": 0},
                                 domain_grid=grid)
        game.use_relic("p1")
        self.assertEqual(game.player_list[0].gold_score, 2)
        self.assertNotEqual(game.action_required.get("action"), "choose_domain_to_build")


class RelicConsumesActionTests(unittest.TestCase):
    """The `consumes_action` flag drives whether using a relic spends a standard
    action. Action accounting happens in the server handler, so these tests
    simulate that flow: consume_player_action(use_relic) -> use_relic."""

    def test_flag_serialized_and_exposed(self):
        game = _make_effect_game("s 1 + g 1", "Gold Bastion", consumes_action=True)
        self.assertTrue(game.relic_consumes_action("p1"))
        free = _make_effect_game("g 1 + build_domain", "Cornelius Ring", consumes_action=False)
        self.assertFalse(free.relic_consumes_action("p1"))

    def test_flag_round_trips_through_save(self):
        game = _make_effect_game("s 1 + g 1", "Gold Bastion", consumes_action=True)
        reloaded = deserialize_save_dict_to_game(serialize_game_to_save_dict(game))
        self.assertTrue(reloaded.relic_consumes_action("p1"))
        self.assertTrue(reloaded.player_list[0].owned_relics[0].consumes_action)

    def test_action_relic_unavailable_with_no_actions_left(self):
        game = _make_effect_game("s 1 + g 1", "Gold Bastion",
                                 consumes_action=True, actions_remaining=0)
        self.assertFalse(game.relic_available_for("p1"))

    def test_free_relic_available_with_no_actions_left(self):
        game = _make_effect_game("g 1 + build_domain", "Cornelius Ring",
                                 player_resources={"gold_score": 0},
                                 consumes_action=False, actions_remaining=0,
                                 domain_grid=[[] for _ in range(5)])
        self.assertTrue(game.relic_available_for("p1"))

    def test_server_flow_consumes_one_action(self):
        game = _make_effect_game("s 1 + g 1", "Gold Bastion",
                                 player_resources={"strength_score": 0, "gold_score": 0},
                                 consumes_action=True, actions_remaining=2)
        # Mirror server: spend the action, then resolve the relic.
        self.assertTrue(game.consume_player_action("p1", action_type="use_relic"))
        game.use_relic("p1")
        self.assertEqual(game.actions_remaining, 1)
        p1 = game.player_list[0]
        self.assertEqual(p1.strength_score, 1)
        self.assertEqual(p1.gold_score, 1)


class RelicUseGateTests(unittest.TestCase):
    def test_available_on_owner_action_turn(self):
        game = _make_action_game()
        self.assertTrue(game.relic_available_for("p1"))
        self.assertFalse(game.relic_available_for("p2"))

    def test_use_marks_relic_used_and_clears_availability(self):
        game = _make_action_game(turn_number=3)
        game.use_relic("p1")
        self.assertFalse(game.relic_available_for("p1"))
        self.assertEqual(game.relic_used_turn.get("p1"), 3)

    def test_cannot_use_twice_in_one_turn(self):
        game = _make_action_game()
        game.use_relic("p1")
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_cannot_use_off_turn(self):
        game = _make_action_game(active="p1")
        with self.assertRaises(ValueError):
            game.use_relic("p2")

    def test_cannot_use_outside_action_phase(self):
        game = _make_action_game(phase="roll")
        self.assertFalse(game.relic_available_for("p1"))
        with self.assertRaises(ValueError):
            game.use_relic("p1")

    def test_available_again_next_turn(self):
        game = _make_action_game(turn_number=4, relic_used_turn={"p1": 3})
        self.assertTrue(game.relic_available_for("p1"))

    def test_used_turn_round_trips_through_save(self):
        game = _make_action_game(turn_number=3)
        game.use_relic("p1")
        reloaded = deserialize_save_dict_to_game(serialize_game_to_save_dict(game))
        self.assertEqual(reloaded.relic_used_turn.get("p1"), 3)
        self.assertFalse(reloaded.relic_available_for("p1"))


class ShouldIncludeRelicsTests(unittest.TestCase):
    def test_debug_non_crimsonseas_includes(self):
        self.assertTrue(_should_include_relics("base", debug_mode=True))
        self.assertTrue(_should_include_relics("random", debug_mode=True))

    def test_debug_crimsonseas_excludes(self):
        self.assertFalse(_should_include_relics("crimsonseas", debug_mode=True))

    def test_draft_follows_vote(self):
        self.assertTrue(_should_include_relics("draft", draft_selections={"include_relics": True}))
        self.assertFalse(_should_include_relics("draft", draft_selections={"include_relics": False}))
        self.assertFalse(_should_include_relics("draft", draft_selections={}))

    def test_draft_relics_independent_of_agents(self):
        # An agents-yes vote must not implicitly enable relics.
        self.assertFalse(_should_include_relics("draft", draft_selections={"include_agents": True}))

    @patch("game_setup.random.random", return_value=0.1)
    def test_random_includes_on_low_roll(self, _mock):
        self.assertTrue(_should_include_relics("random"))

    @patch("game_setup.random.random", return_value=0.9)
    def test_random_excludes_on_high_roll(self, _mock):
        self.assertFalse(_should_include_relics("random"))

    def test_base_preset_excludes(self):
        self.assertFalse(_should_include_relics("base"))


class RelicCountPerPlayerTests(unittest.TestCase):
    def test_matches_duke_count_below_five_players(self):
        self.assertEqual(_relic_count_per_player(2, 2), 2)
        self.assertEqual(_relic_count_per_player(3, 4), 3)
        self.assertEqual(_relic_count_per_player(3, 4, available_relics=12), 3)

    def test_falls_back_to_two_when_bans_make_three_impossible(self):
        self.assertEqual(_relic_count_per_player(3, 4, available_relics=11), 2)
        self.assertEqual(_relic_count_per_player(3, 3, available_relics=8), 2)

    def test_capped_at_two_for_five_players(self):
        self.assertEqual(_relic_count_per_player(3, 5), 2)
        self.assertEqual(_relic_count_per_player(2, 5), 2)
        self.assertEqual(_relic_count_per_player(3, 5, available_relics=9), 0)

    def test_disables_when_less_than_two_each_available(self):
        self.assertEqual(_relic_count_per_player(3, 4, available_relics=7), 0)


class RelicSelectionFlowTests(unittest.TestCase):
    def test_relic_gate_opens_after_duke_selection(self):
        game = _make_setup_game()
        self.assertEqual(game.concurrent_action.get("kind"), "choose_duke")

        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")

        # Duke selection done -> relic selection is now the active gate.
        self.assertIsNotNone(game.concurrent_action)
        self.assertEqual(game.concurrent_action.get("kind"), "choose_relic")
        self.assertEqual(set(game.concurrent_action.get("pending")), {"p1", "p2"})

    def test_keeping_one_relic_discards_the_rest(self):
        game = _make_setup_game(relics_per_player=2)
        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")

        keep_ids = {}
        for p in game.player_list:
            keep = p.owned_relics[1]
            keep_ids[p.player_id] = keep.relic_id
            game.submit_concurrent_action(p.player_id, str(keep.relic_id), kind="choose_relic")

        self.assertIsNone(game.concurrent_action)
        for p in game.player_list:
            self.assertEqual(len(p.owned_relics), 1)
            self.assertEqual(p.owned_relics[0].relic_id, keep_ids[p.player_id])

    def test_invalid_relic_choice_rejected(self):
        game = _make_setup_game()
        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")
        with self.assertRaises(ValueError):
            game.submit_concurrent_action("p1", "99999", kind="choose_relic")

    def test_no_relic_gate_when_module_disabled(self):
        game = _make_setup_game(include_relics=False, relics_per_player=0)
        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")
        # No relics dealt -> no relic gate; setup proceeds.
        self.assertIsNone(game.concurrent_action)

    def test_save_load_round_trip_across_relic_gate(self):
        game = _make_setup_game()
        for p in game.player_list:
            game.submit_concurrent_action(p.player_id, str(p.owned_dukes[0].duke_id), kind="choose_duke")
        # Mid relic-selection: persist and rehydrate.
        reloaded = deserialize_save_dict_to_game(serialize_game_to_save_dict(game))
        self.assertTrue(reloaded.include_relics)
        self.assertTrue(reloaded.relics_enabled())
        self.assertEqual(reloaded.concurrent_action.get("kind"), "choose_relic")
        for p in reloaded.player_list:
            self.assertEqual(len(p.owned_relics), 2)
        for p in reloaded.player_list:
            reloaded.submit_concurrent_action(p.player_id, str(p.owned_relics[0].relic_id), kind="choose_relic")
        self.assertIsNone(reloaded.concurrent_action)


@unittest.skipUnless(
    _db_ready(),
    "requires active DB tunnel and mariadb module; run source ./activate_with_env.sh first",
)
class RelicsSetupIntegrationTests(unittest.TestCase):
    def _players(self, n):
        return [LobbyMember(f"Player {i}", f"p{i}") for i in range(1, n + 1)]

    def _load(self, preset, players, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_game_data(f"relics-setup-{preset}", preset, players, **kwargs)

    def test_debug_base_deals_relics(self):
        state = self._load("base", self._players(2), debug_mode=True, duke_select_count=2)
        self.assertTrue(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 2)

    def test_duke_count_three_deals_three_relics(self):
        state = self._load("base", self._players(2), debug_mode=True, duke_select_count=3)
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 3)

    def test_five_players_capped_at_two_relics(self):
        state = self._load("base", self._players(5), debug_mode=True, duke_select_count=3)
        self.assertTrue(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 2)

    @patch("game_setup.banned_relic_ids", return_value={1, 2})
    def test_four_players_with_relic_bans_falls_back_to_two(self, _mock):
        state = self._load("base", self._players(4), debug_mode=True, duke_select_count=3)
        self.assertTrue(state.get("include_relics"))
        seen_ids = set()
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 2)
            seen_ids |= {r.relic_id for r in player.owned_relics}
        self.assertNotIn(1, seen_ids)
        self.assertNotIn(2, seen_ids)

    def test_debug_crimsonseas_skips_relics(self):
        state = self._load("crimsonseas", self._players(2), debug_mode=True)
        self.assertFalse(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 0)

    def test_base_without_debug_skips_relics(self):
        state = self._load("base", self._players(2), debug_mode=False)
        self.assertFalse(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 0)

    @patch("game_setup.random.random", return_value=0.1)
    def test_random_includes_relics(self, _mock):
        state = self._load("random", self._players(2))
        self.assertTrue(state.get("include_relics"))
        for player in state["player_list"]:
            self.assertEqual(len(player.owned_relics), 2)


if __name__ == "__main__":
    unittest.main()
