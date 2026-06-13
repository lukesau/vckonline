"""Tests for the Agents optional module (setup gating + engage/recycle)."""

import contextlib
import importlib.util
import io
import socket
import unittest
from unittest.mock import patch

from cards import Agent, Citizen, Domain, Monster
from game import Game
from game_models import LobbyMember, Player


def _make_citizen(citizen_id, name, *, shadow=0, holy=0, soldier=0, worker=0):
    c = Citizen(
        citizen_id=citizen_id,
        name=name,
        gold_cost=0,
        roll_match1=2, roll_match2=0,
        shadow_count=shadow, holy_count=holy, soldier_count=soldier, worker_count=worker,
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
from game_setup import (
    AGENT_SLOT_COUNT,
    _should_include_agents,
    load_game_data,
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


def _make_monster(monster_id, name, *, strength_cost=2, magic_cost=0, vp_reward=1):
    m = Monster(
        monster_id, name, "Forest", "Minion", 1,
        strength_cost, magic_cost,
        vp_reward, 0, 0, 0,
        False, "",
        False, "",
        False, "base",
    )
    m.toggle_visibility(True)
    m.toggle_accessibility(True)
    return m


def _make_action_game(agents_slots, agents_deck=None, player_resources=None, citizen_grid=None,
                      monster_grid=None):
    p1 = Player("p1", "Player 1")
    if player_resources:
        for k, v in player_resources.items():
            setattr(p1, k, v)
    return Game({
        "game_id": "test-agents",
        "preset": "base",
        "include_agents": True,
        "player_list": [p1],
        "monster_grid": monster_grid if monster_grid is not None else [[] for _ in range(5)],
        "citizen_grid": citizen_grid if citizen_grid is not None else [[] for _ in range(10)],
        "domain_grid": [[] for _ in range(5)],
        "agents_slots": list(agents_slots),
        "agents_deck": list(agents_deck or []),
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
        "action_required": {"id": "p1", "action": "standard_action"},
        "game_log": [],
        "turn_index": 0,
        "phase": "action",
        "actions_remaining": 2,
    })


class ShouldIncludeAgentsTests(unittest.TestCase):
    def test_debug_non_crimsonseas_includes(self):
        self.assertTrue(_should_include_agents("base", debug_mode=True))
        self.assertTrue(_should_include_agents("random", debug_mode=True))

    def test_debug_crimsonseas_excludes(self):
        self.assertFalse(_should_include_agents("crimsonseas", debug_mode=True))

    def test_draft_follows_vote(self):
        self.assertTrue(_should_include_agents("draft", draft_selections={"include_agents": True}))
        self.assertFalse(_should_include_agents("draft", draft_selections={"include_agents": False}))
        self.assertFalse(_should_include_agents("draft", draft_selections={}))

    @patch("game_setup.random.random", return_value=0.1)
    def test_random_includes_on_low_roll(self, _mock):
        self.assertTrue(_should_include_agents("random"))

    @patch("game_setup.random.random", return_value=0.9)
    def test_random_excludes_on_high_roll(self, _mock):
        self.assertFalse(_should_include_agents("random"))

    def test_base_preset_excludes(self):
        self.assertFalse(_should_include_agents("base"))


@unittest.skipUnless(
    _db_ready(),
    "requires active DB tunnel and mariadb module; run source ./activate_with_env.sh first",
)
class AgentsSetupIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.players = [LobbyMember("Player 1", "p1"), LobbyMember("Player 2", "p2")]

    def _load(self, preset, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return load_game_data(f"agents-setup-{preset}", preset, self.players, **kwargs)

    def test_debug_base_deals_agents(self):
        state = self._load("base", debug_mode=True)
        self.assertTrue(state.get("include_agents"))
        self.assertEqual(len(state.get("agents_slots") or []), AGENT_SLOT_COUNT)
        self.assertTrue(len(state.get("agents_deck") or []) > 0)

    def test_debug_crimsonseas_skips_agents(self):
        state = self._load("crimsonseas", debug_mode=True)
        self.assertFalse(state.get("agents_slots"))
        self.assertFalse(state.get("agents_deck"))

    @patch("game_setup.random.random", return_value=0.1)
    def test_random_includes_agents(self, _mock):
        state = self._load("random")
        self.assertTrue(state.get("include_agents"))
        self.assertEqual(len(state.get("agents_slots") or []), AGENT_SLOT_COUNT)

    def test_base_without_debug_skips_agents(self):
        state = self._load("base", debug_mode=False)
        self.assertFalse(state.get("include_agents"))
        self.assertFalse(state.get("agents_slots"))


class EngageAgentTests(unittest.TestCase):
    def _captain(self):
        return Agent(
            6, "Captain",
            "s -10 + v 5",
            "Pay 10 Strength to gain 5 Victory Points.",
        )

    def _stub(self):
        return Agent(1, "Abbot", None, "Not implemented.")

    def test_unaffordable_engage_rejected(self):
        game = _make_action_game([self._captain()], player_resources={"strength_score": 5})
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_unimplemented_engage_rejected(self):
        game = _make_action_game([self._stub()], player_resources={"strength_score": 100})
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_captain_pays_and_recycles(self):
        captain = self._captain()
        next_agent = Agent(7, "Prefect", "m -10 + v 5", "")
        deck = [next_agent]
        game = _make_action_game([captain], deck, player_resources={
            "strength_score": 10,
            "gold_score": 0,
            "magic_score": 0,
            "victory_score": 0,
        })

        game.engage_agent("p1", 0)

        p1 = game.player_list[0]
        self.assertEqual(p1.strength_score, 0)
        self.assertEqual(p1.victory_score, 5)
        self.assertIs(game.agents_slots[0], next_agent)
        self.assertEqual(game.agents_deck[0], captain)
        self.assertEqual(len(game.agents_deck), 1)

    def test_treasurer_pays_gold(self):
        treasurer = Agent(
            15, "Treasurer",
            "g -10 + v 5",
            "Pay 10 Gold to gain 5 Victory Points.",
        )
        replacement = Agent(99, "Replacement", None, "")
        game = _make_action_game([treasurer], [replacement], player_resources={
            "gold_score": 10,
            "strength_score": 0,
            "magic_score": 0,
            "victory_score": 0,
        })
        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 0)
        self.assertEqual(p1.victory_score, 5)


class AbbotPublicanTests(unittest.TestCase):
    def _abbot(self):
        return Agent(
            1, "Abbot",
            "m -5 + v 1 + <citizens where role==holy>",
            "Pay 5 Magic to gain 1 Victory Point and gain a Holy Citizen.",
        )

    def _publican(self):
        return Agent(
            11, "Publican",
            "g -5 + v 1 + <citizens where role==shadow>",
            "Pay 5 Gold to gain 1 Victory Point and gain a Shadow Citizen.",
        )

    def test_abbot_unaffordable_rejected(self):
        grid = [[_make_citizen(20, "Cleric", holy=1)]] + [[] for _ in range(9)]
        game = _make_action_game([self._abbot()], [Agent(99, "X", None, "")],
                                  player_resources={"magic_score": 4}, citizen_grid=grid)
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_abbot_pays_magic_gains_vp_and_opens_holy_choice(self):
        holy = _make_citizen(20, "Cleric", holy=1)
        grid = [[holy]] + [[] for _ in range(9)]
        game = _make_action_game([self._abbot()], [Agent(99, "X", None, "")],
                                  player_resources={
                                      "magic_score": 5, "gold_score": 0,
                                      "strength_score": 0, "victory_score": 0,
                                  }, citizen_grid=grid)
        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        # Magic spent + VP gained immediately from the self_convert leg.
        self.assertEqual(p1.magic_score, 0)
        self.assertEqual(p1.victory_score, 1)
        # The citizen choose prompt is open.
        self.assertTrue(str(game.action_required.get("action", "")).lower().startswith("choose"))
        # Resolve the choose to take the Holy citizen.
        game.act_on_required_action("p1", "choose 1")
        names = [c.name for c in p1.owned_citizens]
        self.assertIn("Cleric", names)

    def test_publican_pays_gold_gains_vp_and_shadow(self):
        shadow = _make_citizen(21, "Rogue", shadow=1)
        grid = [[shadow]] + [[] for _ in range(9)]
        game = _make_action_game([self._publican()], [Agent(99, "X", None, "")],
                                  player_resources={
                                      "gold_score": 5, "magic_score": 0,
                                      "strength_score": 0, "victory_score": 0,
                                  }, citizen_grid=grid)
        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 0)
        self.assertEqual(p1.victory_score, 1)
        game.act_on_required_action("p1", "choose 1")
        names = [c.name for c in p1.owned_citizens]
        self.assertIn("Rogue", names)

    def test_abbot_recycles_slot_immediately(self):
        holy = _make_citizen(20, "Cleric", holy=1)
        grid = [[holy]] + [[] for _ in range(9)]
        replacement = Agent(99, "Replacement", None, "")
        abbot = self._abbot()
        game = _make_action_game([abbot], [replacement],
                                 player_resources={"magic_score": 5}, citizen_grid=grid)
        game.engage_agent("p1", 0)
        # Slot already refilled with the deck top even though the choose prompt
        # is still open.
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0], abbot)


def _make_domain(domain_id, name, passive_effect="", *, acquired_turn_number=None):
    d = Domain(
        domain_id, name, 0,
        0, 0, 0, 0,
        1,
        False, bool(passive_effect),
        passive_effect, "", "", "base",
        acquired_turn_number=acquired_turn_number,
    )
    d.toggle_visibility(True)
    d.toggle_accessibility(True)
    return d


def _make_two_player_action_game(agents_slots, agents_deck=None, p1_resources=None,
                                 p2_citizens=None, p2_domains=None, p2_monsters=None,
                                 p1_citizens=None, p1_domains=None,
                                 p2_resources=None, monster_stack_areas=None,
                                 citizen_grid=None):
    p1 = Player("p1", "Player 1")
    if p1_resources:
        for k, v in p1_resources.items():
            setattr(p1, k, v)
    if p1_citizens:
        p1.owned_citizens = list(p1_citizens)
    if p1_domains:
        p1.owned_domains = list(p1_domains)
    p2 = Player("p2", "Player 2")
    if p2_resources:
        for k, v in p2_resources.items():
            setattr(p2, k, v)
    if p2_citizens:
        p2.owned_citizens = list(p2_citizens)
    if p2_domains:
        p2.owned_domains = list(p2_domains)
    if p2_monsters:
        p2.owned_monsters = list(p2_monsters)
    return Game({
        "game_id": "test-agents-2p",
        "preset": "base",
        "include_agents": True,
        "player_list": [p1, p2],
        "monster_grid": [[] for _ in range(5)],
        "monster_stack_areas": list(monster_stack_areas or []),
        "citizen_grid": citizen_grid if citizen_grid is not None else [[] for _ in range(10)],
        "domain_grid": [[] for _ in range(5)],
        "agents_slots": list(agents_slots),
        "agents_deck": list(agents_deck or []),
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {"roll_phase": [], "harvest_phase": [], "action_phase": []},
        "action_required": {"id": "p1", "action": "standard_action"},
        "game_log": [],
        "turn_index": 0,
        "phase": "action",
        "actions_remaining": 2,
    })


class AssassinTests(unittest.TestCase):
    def _assassin(self):
        return Agent(
            2, "Assassin",
            "g -3 + flip_opponent_citizen",
            "Pay 3 Gold to flip a Citizen from another player's tableau. "
            "While flipped, that Citizen does not activate in the Harvest Phase.",
        )

    def test_unaffordable_engage_rejected(self):
        victim = _make_citizen(30, "Rogue", shadow=1)
        game = _make_two_player_action_game(
            [self._assassin()], [Agent(99, "X", None, "")],
            p1_resources={"gold_score": 2}, p2_citizens=[victim])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_no_target_engage_rejected(self):
        # Opponent has no unflipped citizens -> cannot engage at all.
        game = _make_two_player_action_game(
            [self._assassin()], [Agent(99, "X", None, "")],
            p1_resources={"gold_score": 10}, p2_citizens=[])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_pays_gold_flips_and_recycles(self):
        victim = _make_citizen(30, "Rogue", shadow=1)
        victim.is_flipped = False
        assassin = self._assassin()
        replacement = Agent(99, "Replacement", None, "")
        game = _make_two_player_action_game(
            [assassin], [replacement],
            p1_resources={"gold_score": 10, "strength_score": 0,
                          "magic_score": 0, "victory_score": 0},
            p2_citizens=[victim])

        game.engage_agent("p1", 0)

        p1 = game.player_list[0]
        # 3 Gold paid immediately; the flip prompt is now open.
        self.assertEqual(p1.gold_score, 7)
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "choose_player")
        # Slot recycled eagerly even while the prompt is open.
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0], assassin)

        # Resolve the two-stage flip prompt: pick the opponent, then the citizen.
        game.act_on_required_action("p1", "choose_player 1")
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "choose_owned_card")
        game.act_on_required_action("p1", "choose_owned_card 1")
        self.assertTrue(victim.is_flipped)


class TownCrierTests(unittest.TestCase):
    def _town_crier(self):
        return Agent(
            14, "Town Crier",
            "g -3 + v 1 + recruit",
            "Pay 3 Gold to gain 1 Victory Point and you may recruit a Citizen, "
            "ignoring increased Gold cost for owning copies of that Citizen.",
        )

    def test_unaffordable_engage_rejected(self):
        grid = [[_make_citizen(40, "Peasant")]] + [[] for _ in range(9)]
        game = _make_action_game([self._town_crier()], [Agent(99, "X", None, "")],
                                 player_resources={"gold_score": 2}, citizen_grid=grid)
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_pays_gold_vp_opens_may_recruit_and_recycles(self):
        grid = [[_make_citizen(40, "Peasant")]] + [[] for _ in range(9)]
        replacement = Agent(99, "Replacement", None, "")
        game = _make_action_game([self._town_crier()], [replacement],
                                 player_resources={
                                     "gold_score": 5, "victory_score": 0,
                                     "magic_score": 0, "strength_score": 0,
                                 }, citizen_grid=grid)
        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 2)
        self.assertEqual(p1.victory_score, 1)
        self.assertEqual(game.action_required.get("action"), "may_recruit")
        self.assertEqual(game.pending_bonus_recruit, "p1")
        # Slot recycled eagerly even while the may_recruit prompt is open.
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0].name, "Town Crier")

    def test_bonus_recruit_waives_duplicate_surcharge(self):
        owned_peasant = _make_citizen(41, "Peasant")
        grid_peasant = _make_citizen(40, "Peasant")
        grid_peasant.gold_cost = 2
        grid = [[grid_peasant]] + [[] for _ in range(9)]
        game = _make_action_game([self._town_crier()], [Agent(99, "X", None, "")],
                                 player_resources={
                                     "gold_score": 5, "victory_score": 0,
                                     "magic_score": 0, "strength_score": 0,
                                 }, citizen_grid=grid)
        game.player_list[0].owned_citizens = [owned_peasant]

        game.engage_agent("p1", 0)
        self.assertEqual(game.action_required.get("action"), "may_recruit")

        # The bonus recruit pays the base cost (2g) only — the +1 duplicate
        # surcharge is waived — and does not consume a regular action.
        self.assertTrue(game.consume_player_action("p1", action_type="hire_citizen"))
        game.hire_citizen("p1", 40, gp=2)
        self.assertTrue(game.resolve_bonus_recruit_if_consumed())

        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 0)
        self.assertEqual([c.name for c in p1.owned_citizens].count("Peasant"), 2)
        self.assertIsNone(game.pending_bonus_recruit)
        self.assertNotEqual(game.action_required.get("action"), "may_recruit")

    def test_decline_recruit_resumes(self):
        grid = [[_make_citizen(40, "Peasant")]] + [[] for _ in range(9)]
        game = _make_action_game([self._town_crier()], [Agent(99, "X", None, "")],
                                 player_resources={"gold_score": 5, "victory_score": 0},
                                 citizen_grid=grid)
        game.engage_agent("p1", 0)
        self.assertEqual(game.action_required.get("action"), "may_recruit")
        game.act_on_required_action("p1", "skip")
        self.assertIsNone(game.pending_bonus_recruit)
        self.assertNotEqual(game.action_required.get("action"), "may_recruit")

    def test_no_citizens_skips_prompt(self):
        grid = [[] for _ in range(10)]
        game = _make_action_game([self._town_crier()], [Agent(99, "X", None, "")],
                                 player_resources={
                                     "gold_score": 5, "victory_score": 0,
                                     "magic_score": 0, "strength_score": 0,
                                 }, citizen_grid=grid)
        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 2)
        self.assertEqual(p1.victory_score, 1)
        self.assertIsNone(game.pending_bonus_recruit)
        self.assertNotEqual(game.action_required.get("action"), "may_recruit")


class SquireTests(unittest.TestCase):
    def _squire(self):
        return Agent(
            13, "Squire",
            "g -1 + s 3 + slay",
            "Pay 1 Gold to gain 3 Strength and you may immediately slay a Monster.",
        )

    def test_unaffordable_engage_rejected(self):
        grid = [[_make_monster(50, "Goblin")]] + [[] for _ in range(4)]
        game = _make_action_game([self._squire()], [Agent(99, "X", None, "")],
                                 player_resources={"gold_score": 0}, monster_grid=grid)
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_pays_gold_strength_opens_slay_and_recycles(self):
        grid = [[_make_monster(50, "Goblin", strength_cost=2, vp_reward=1)]] + [[] for _ in range(4)]
        replacement = Agent(99, "Replacement", None, "")
        game = _make_action_game([self._squire()], [replacement],
                                 player_resources={
                                     "gold_score": 5, "strength_score": 0,
                                     "magic_score": 0, "victory_score": 0,
                                 }, monster_grid=grid)
        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 4)
        self.assertEqual(p1.strength_score, 3)
        self.assertEqual(game.action_required.get("action"), "choose_monster_slay")
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0].name, "Squire")

        # Resolve the two-stage may-slay prompt: pick the monster, then pay.
        game.act_on_required_action("p1", "choose_monster_slay 1")
        self.assertEqual(game.action_required.get("action"), "slay_monster_payment")
        game.act_on_required_action("p1", "slay_pay 0 2 0")
        self.assertEqual(p1.strength_score, 1)
        self.assertEqual(p1.victory_score, 1)
        self.assertEqual([m.name for m in p1.owned_monsters], ["Goblin"])
        self.assertNotEqual(game.action_required.get("action"), "slay_monster_payment")

    def test_decline_slay_keeps_resources(self):
        grid = [[_make_monster(50, "Goblin")]] + [[] for _ in range(4)]
        game = _make_action_game([self._squire()], [Agent(99, "X", None, "")],
                                 player_resources={"gold_score": 5, "strength_score": 0},
                                 monster_grid=grid)
        game.engage_agent("p1", 0)
        self.assertEqual(game.action_required.get("action"), "choose_monster_slay")
        game.act_on_required_action("p1", "skip")
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 4)
        self.assertEqual(p1.strength_score, 3)
        self.assertEqual(p1.owned_monsters, [])
        self.assertNotEqual(game.action_required.get("action"), "choose_monster_slay")

    def test_no_monster_skips_prompt(self):
        game = _make_action_game([self._squire()], [Agent(99, "X", None, "")],
                                 player_resources={
                                     "gold_score": 5, "strength_score": 0,
                                     "magic_score": 0, "victory_score": 0,
                                 })
        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 4)
        self.assertEqual(p1.strength_score, 3)
        self.assertNotEqual(game.action_required.get("action"), "choose_monster_slay")


class SapperTests(unittest.TestCase):
    def _sapper(self):
        return Agent(
            12, "Sapper",
            "s -3 + flip_opponent_domain",
            "Pay 3 Strength to flip a Domain from another player's tableau. While "
            "flipped, that Domain power may not be used. At the end of the game, "
            "flip the Domain face-up and score it as usual.",
        )

    def test_unaffordable_engage_rejected(self):
        dom = _make_domain(3, "Emerald Stronghold", "effect.add action.emeraldstronghold")
        game = _make_two_player_action_game(
            [self._sapper()], [Agent(99, "X", None, "")],
            p1_resources={"strength_score": 2}, p2_domains=[dom])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_no_target_engage_rejected(self):
        game = _make_two_player_action_game(
            [self._sapper()], [Agent(99, "X", None, "")],
            p1_resources={"strength_score": 10}, p2_domains=[])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_pays_strength_flips_disables_power_and_recycles(self):
        dom = _make_domain(3, "Emerald Stronghold", "effect.add action.emeraldstronghold")
        sapper = self._sapper()
        replacement = Agent(99, "Replacement", None, "")
        game = _make_two_player_action_game(
            [sapper], [replacement],
            p1_resources={"strength_score": 5, "gold_score": 0,
                          "magic_score": 0, "victory_score": 0},
            p2_domains=[dom])
        p2 = game.player_list[1]
        # Power is live before the flip.
        self.assertTrue(game._player_has_action_effect_flag(p2, "action.emeraldstronghold"))

        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.strength_score, 2)
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "choose_player")
        # Slot recycled eagerly while the prompt is still open.
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0], sapper)

        game.act_on_required_action("p1", "choose_player 1")
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "choose_owned_card")
        game.act_on_required_action("p1", "choose_owned_card 1")

        self.assertTrue(dom.is_flipped)
        self.assertFalse(dom.is_visible)
        # The flipped domain's passive power is suppressed.
        self.assertFalse(game._player_has_action_effect_flag(p2, "action.emeraldstronghold"))

    def test_endgame_restores_flipped_domain(self):
        dom = _make_domain(3, "Emerald Stronghold", "effect.add action.emeraldstronghold")
        game = _make_two_player_action_game(
            [self._sapper()], [Agent(99, "X", None, "")],
            p1_resources={"strength_score": 5}, p2_domains=[dom])
        game.engage_agent("p1", 0)
        game.act_on_required_action("p1", "choose_player 1")
        game.act_on_required_action("p1", "choose_owned_card 1")
        self.assertTrue(dom.is_flipped)

        game.unflip_all_domains_for_final_scoring()
        p2 = game.player_list[1]
        self.assertFalse(dom.is_flipped)
        self.assertTrue(dom.is_visible)
        self.assertTrue(game._player_has_action_effect_flag(p2, "action.emeraldstronghold"))

    def test_flipped_state_survives_card_roundtrip(self):
        dom = _make_domain(3, "Emerald Stronghold", "effect.add action.emeraldstronghold")
        dom.is_flipped = True
        dom.toggle_visibility(False)
        restored = Domain.from_dict(dom.to_dict())
        self.assertTrue(restored.is_flipped)


class BaronBruteSquadKingsHeraldTests(unittest.TestCase):
    def _baron(self):
        return Agent(
            3, "Baron",
            "g -5 + count owned_domains v 1",
            "Pay 5 Gold to gain 1 Victory Point for each Domain you own.",
        )

    def _brute_squad(self):
        return Agent(
            5, "Brute Squad",
            "g -10 + <citizens> + banish_center citizen",
            "Pay 10 Gold to gain a Citizen and banish a Citizen from the center stacks.",
        )

    def _kings_herald(self):
        return Agent(
            9, "King's Herald",
            "banish_owned citizen + v 2",
            "Banish a Citizen from your own tableau to gain 2 Victory Points.",
        )

    def test_baron_pays_gold_and_gains_vp_per_owned_domain(self):
        domains = [
            _make_domain(50, "Domain A"),
            _make_domain(51, "Domain B"),
            _make_domain(52, "Domain C"),
        ]
        game = _make_two_player_action_game(
            [self._baron()], [Agent(99, "X", None, "")],
            p1_resources={"gold_score": 5, "strength_score": 0, "magic_score": 0, "victory_score": 0},
            p1_domains=domains)

        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 0)
        self.assertEqual(p1.victory_score, 3)

    def test_baron_unaffordable_rejected(self):
        game = _make_two_player_action_game(
            [self._baron()], [Agent(99, "X", None, "")],
            p1_resources={"gold_score": 4},
            p1_domains=[_make_domain(50, "Domain A")])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_brute_squad_gains_citizen_then_banishes_center_citizen(self):
        recruit = _make_citizen(60, "Recruit", worker=1)
        banish_target = _make_citizen(61, "Target", shadow=1)
        grid = [[recruit], [banish_target]] + [[] for _ in range(8)]
        brute = self._brute_squad()
        replacement = Agent(99, "Replacement", None, "")
        game = _make_two_player_action_game(
            [brute], [replacement],
            p1_resources={"gold_score": 10, "strength_score": 0, "magic_score": 0, "victory_score": 0},
            citizen_grid=grid)

        game.engage_agent("p1", 0)
        p1 = game.player_list[0]
        self.assertEqual(p1.gold_score, 0)
        self.assertEqual(str(game.action_required.get("action", "")).split()[0], "choose")
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0], brute)

        game.act_on_required_action("p1", "choose 1")
        self.assertIn(recruit, p1.owned_citizens)
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "choose_owned_card")
        self.assertEqual((game.pending_required_choice or {}).get("kind"), "banish_center_card")

        game.act_on_required_action("p1", "choose_owned_card 1")
        self.assertIn(banish_target, game.banish_pile)
        self.assertNotIn(banish_target, p1.owned_citizens)

    def test_brute_squad_rejected_without_center_citizen(self):
        game = _make_two_player_action_game(
            [self._brute_squad()], [Agent(99, "X", None, "")],
            p1_resources={"gold_score": 10},
            citizen_grid=[[] for _ in range(10)])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_kings_herald_banishes_owned_citizen_for_vp(self):
        citizen = _make_citizen(70, "Courtier", holy=1)
        herald = self._kings_herald()
        replacement = Agent(99, "Replacement", None, "")
        game = _make_two_player_action_game(
            [herald], [replacement],
            p1_resources={"gold_score": 0, "strength_score": 0, "magic_score": 0, "victory_score": 0},
            p1_citizens=[citizen])

        game.engage_agent("p1", 0)
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "choose_owned_card")
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0], herald)

        game.act_on_required_action("p1", "choose_owned_card 1")
        p1 = game.player_list[0]
        self.assertEqual(p1.owned_citizens, [])
        self.assertIn(citizen, game.banish_pile)
        self.assertEqual(p1.victory_score, 2)

    def test_kings_herald_rejected_without_owned_citizen(self):
        game = _make_two_player_action_game(
            [self._kings_herald()], [Agent(99, "X", None, "")],
            p1_citizens=[])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)


class BishopTests(unittest.TestCase):
    def _bishop(self):
        return Agent(
            4, "Bishop",
            "steal g 5 m 5 victim_vp=1",
            "Steal 5 Gold or 5 Magic from another player. That player gains 1 Victory Point.",
        )

    def test_no_target_rejected_when_only_opponent_is_immune(self):
        castle = _make_domain(26, "Castle of the Seven Suns", "immunity.take")
        game = _make_two_player_action_game(
            [self._bishop()], [Agent(99, "X", None, "")],
            p2_domains=[castle], p2_resources={"gold_score": 10})
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_steal_gold_two_stage_and_victim_gains_vp(self):
        bishop = self._bishop()
        replacement = Agent(99, "Replacement", None, "")
        game = _make_two_player_action_game(
            [bishop], [replacement],
            p1_resources={"gold_score": 0, "strength_score": 0, "magic_score": 0, "victory_score": 0},
            p2_resources={"gold_score": 10, "magic_score": 10, "victory_score": 0})

        game.engage_agent("p1", 0)
        # Free engage opens the steal prompt; slot recycled eagerly.
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "harvest_steal")
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0], bishop)

        game.act_on_required_action("p1", "steal_victim 1")
        # Two resource options -> a resource sub-prompt opens.
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "harvest_steal")
        self.assertEqual((game.pending_required_choice or {}).get("stage"), "resource")

        game.act_on_required_action("p1", "steal_resource 1")  # g 5
        p1, p2 = game.player_list
        self.assertEqual(p1.gold_score, 5)
        self.assertEqual(p2.gold_score, 5)
        self.assertEqual(p2.victory_score, 1)
        self.assertNotEqual(str(game.action_required.get("action", "")).strip(), "harvest_steal")

    def test_steal_magic_choice(self):
        game = _make_two_player_action_game(
            [self._bishop()], [Agent(99, "X", None, "")],
            p1_resources={"gold_score": 0, "strength_score": 0, "magic_score": 0, "victory_score": 0},
            p2_resources={"gold_score": 10, "magic_score": 10, "victory_score": 0})
        game.engage_agent("p1", 0)
        game.act_on_required_action("p1", "steal_victim 1")
        game.act_on_required_action("p1", "steal_resource 2")  # m 5
        p1, p2 = game.player_list
        self.assertEqual(p1.magic_score, 5)
        self.assertEqual(p2.magic_score, 5)
        self.assertEqual(p2.victory_score, 1)

    def test_steal_clamps_to_available_but_still_grants_vp(self):
        game = _make_two_player_action_game(
            [self._bishop()], [Agent(99, "X", None, "")],
            p1_resources={"gold_score": 0, "strength_score": 0, "magic_score": 0, "victory_score": 0},
            p2_resources={"gold_score": 3, "magic_score": 0, "victory_score": 0})
        game.engage_agent("p1", 0)
        game.act_on_required_action("p1", "steal_victim 1")
        game.act_on_required_action("p1", "steal_resource 1")  # g 5 -> clamps to 3
        p1, p2 = game.player_list
        self.assertEqual(p1.gold_score, 3)
        self.assertEqual(p2.gold_score, 0)
        self.assertEqual(p2.victory_score, 1)


class GreenWitchHuntressTests(unittest.TestCase):
    def _green_witch(self):
        return Agent(
            7, "Green Witch",
            "take_owned monster random to=stack victim_vp=1",
            "Take a random Monster from another player's tableau and return it to "
            "its stack. That player gains 1 Victory Point.",
        )

    def _huntress(self):
        return Agent(
            8, "Huntress",
            "take_owned monster random to=self victim_vp=1",
            "Take a random Monster from another player's tableau. That player "
            "gains 1 Victory Point.",
        )

    def test_huntress_takes_monster_to_self_and_grants_victim_vp(self):
        mon = _make_monster(40, "Goblin")
        huntress = self._huntress()
        replacement = Agent(99, "Replacement", None, "")
        game = _make_two_player_action_game(
            [huntress], [replacement],
            p2_monsters=[mon], p2_resources={"victory_score": 0})

        game.engage_agent("p1", 0)
        # Free engage opens the choose_player prompt; slot recycled eagerly.
        self.assertEqual(str(game.action_required.get("action", "")).strip(), "choose_player")
        self.assertIs(game.agents_slots[0], replacement)
        self.assertEqual(game.agents_deck[0], huntress)

        game.act_on_required_action("p1", "choose_player 1")
        p1, p2 = game.player_list
        self.assertEqual(len(p2.owned_monsters), 0)
        self.assertIn(mon, p1.owned_monsters)
        self.assertEqual(p2.victory_score, 1)

    def test_green_witch_returns_monster_to_stack_and_grants_victim_vp(self):
        mon = _make_monster(41, "Ogre")  # area "Forest"
        game = _make_two_player_action_game(
            [self._green_witch()], [Agent(99, "X", None, "")],
            p2_monsters=[mon], p2_resources={"victory_score": 0},
            monster_stack_areas=["Forest", "A", "B", "C", "D"])

        game.engage_agent("p1", 0)
        game.act_on_required_action("p1", "choose_player 1")
        p1, p2 = game.player_list
        self.assertEqual(len(p2.owned_monsters), 0)
        # Returned to its stack, not given to the engaging player.
        self.assertNotIn(mon, p1.owned_monsters)
        self.assertIn(mon, game.monster_grid[0])
        self.assertEqual(p2.victory_score, 1)

    def test_no_monster_target_rejected(self):
        game = _make_two_player_action_game(
            [self._huntress()], [Agent(99, "X", None, "")],
            p2_monsters=[])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)

    def test_take_immunity_blocks_engage(self):
        mon = _make_monster(42, "Wraith")
        castle = _make_domain(26, "Castle of the Seven Suns", "immunity.take")
        game = _make_two_player_action_game(
            [self._green_witch()], [Agent(99, "X", None, "")],
            p2_monsters=[mon], p2_domains=[castle])
        with self.assertRaises(ValueError):
            game.engage_agent("p1", 0)


if __name__ == "__main__":
    unittest.main()
