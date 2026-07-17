"""Game entry point: holds game state, composes sub-engines.

Layout:
- This file owns `class Game`: __init__ (state setup + engine wiring) and a
  handful of small state-utility methods used by every engine
  (`_player_by_id`, `_log_game_event`, role / immunity helpers, etc.).
- Per-area behavior lives in `engines/`: lifecycle, dice, harvest, payouts,
  choose, slay, domain_effects, player_actions, endgame. Each engine receives
  the Game instance and accesses state / utilities via `self.game.<x>`.
- External callers use the explicit delegation methods on `Game`. Internal
  engine-only helpers stay on their owning engine.
"""
import time
import random
import threading
from constants import *
from cards import *
from game_models import Player, Lobby, LobbyMember, GameMember
from game_setup import DEBUG_DIE_ONE_VALUES, DEBUG_DIE_TWO_VALUES, load_game_data
from game_serialization import SummaryEncoder, GameObjectEncoder
from game_helpers import (
    _n,
    _validate_hire_or_domain_gold_payment,
    _validate_monster_slay_payment,
    _citizen_has_steal,
    _parse_domain_effect_kv,
    _parse_resource_kv,
    _player_resource_balances,
    _balances_allow_payout,
)
from game_concurrent import (
    _ChooseDukeConcurrentHandler,
    _FlipOneCitizenConcurrentHandler,
    CONCURRENT_HANDLERS,
    _new_concurrent_action,
)
from engines.lifecycle import LifecycleEngine
from engines.dice import DiceEngine
from engines.harvest import HarvestEngine
from engines.payouts import PayoutsEngine
from engines.choose import ChooseEngine
from engines.slay import SlayEngine
from engines.domain_effects import DomainEffectsEngine
from engines.player_actions import PlayerActionsEngine
from engines.endgame import EndgameEngine
from engines.events import EventsEngine
from engines.agents import AgentsEngine
from engines.relics import RelicsEngine


class Game:
    _ENGINE_ATTRS = (
        "lifecycle",
        "dice",
        "harvest",
        "payouts",
        "choose",
        "slay",
        "domain_effects",
        "player_actions",
        "endgame",
        "events",
        "agents",
        "relics",
    )

    def __init__(self, game_state):
        self.game_id = game_state['game_id']
        # When True the game was started from the lobby with the "Debug mode"
        # toggle on. Currently this flag (a) makes `roll_phase` pick dice out
        # of `DEBUG_DIE_ONE_VALUES` / `DEBUG_DIE_TWO_VALUES` instead of
        # `random.randint(1, 6)`, and (b) is set up-front by `load_game_data`
        # (extra starting resources, citizens, and roll-modifier domains).
        # See `docs/game.md` "Debug mode" section.
        self.debug_mode = bool(game_state.get('debug_mode', False))
        # The lobby preset this game was dealt from (e.g. "crimsonseas",
        # "shadowvale", "random"). Drives expansion-gated features such as the
        # Crimson Seas "map" resource: maps are only surfaced / takeable when
        # this is the Crimson Seas preset. Defaults to "current" for older
        # saves that predate the field.
        self.preset = (game_state.get('preset') or 'current')
        # Crimson Seas Goods tokens (Araby). `goods_supply` is the hidden
        # face-down stack; `goods_slots` holds the (up to 3) face-up tokens in
        # the Araby slots. Each entry is a goods type string (see
        # game_setup.GOODS_TYPES). Empty outside the Crimson Seas preset.
        self.goods_supply = list(game_state.get('goods_supply') or [])
        self.goods_slots = list(game_state.get('goods_slots') or [])
        # Crimson Seas Tome tokens (Nae Aerie). `tome_supply` is the hidden
        # face-down stack; `tome_slots` holds the (up to 3) face-up tomes in the
        # Nae Aerie slots. Each entry is a resource type string (see
        # game_setup.TOME_TYPES). Empty outside the Crimson Seas preset.
        self.tome_supply = list(game_state.get('tome_supply') or [])
        self.tome_slots = list(game_state.get('tome_slots') or [])
        # Crimson Seas Noble cards (Amarynth). `noble_supply` is the hidden
        # face-down deck; `noble_slots` holds the (up to 3) face-up Noble cards
        # in the Amarynth slots. Entries are Noble card objects (see
        # game_setup.NOBLE_SLOT_COUNT). Empty outside the Crimson Seas preset.
        self.noble_supply = list(game_state.get('noble_supply') or [])
        self.noble_slots = list(game_state.get('noble_slots') or [])
        # Crimson Seas Exekratys resource pool (the cursed island). A dict of
        # resource -> count (e.g. {"gold": 2, "strength": 2, "magic": 2}). Players
        # feed it on rolling 6s and clear it by sailing there. Empty outside the
        # Crimson Seas preset.
        self.exekratys_resources = dict(game_state.get('exekratys_resources') or {})
        # Agents optional module: 4 face-up slots + face-down deck. Empty when
        # the module was not included at setup.
        self.agents_slots = list(game_state.get('agents_slots') or [])
        self.agents_deck = list(game_state.get('agents_deck') or [])
        self.include_agents = bool(game_state.get('include_agents', False))
        # Relics optional module: each player keeps one of their dealt relics
        # (held in `player.owned_relics`); no board-level deck is kept.
        self.include_relics = bool(game_state.get('include_relics', False))
        # Per-player relic usage gate: player_id -> turn_number on which that
        # player last used their relic. A relic is usable again once the global
        # turn_number advances, so a player may use it once per turn.
        self.relic_used_turn = {
            str(k): int(v)
            for k, v in (game_state.get('relic_used_turn') or {}).items()
        }
        # Crimson Seas roll obligation: each 6 rolled (each die plus the dice
        # sum, counted separately) forces the active player to place 1 of their
        # resources into the Exekratys pool. `pending_exekratys_offerings` is the
        # number of placements still owed for the current roll; the active player
        # who owes them is `pending_exekratys_offering_player`. Drained during the
        # roll-to-harvest transition before any harvest automation runs.
        self.pending_exekratys_offerings = int(game_state.get('pending_exekratys_offerings') or 0)
        self.pending_exekratys_offering_player = game_state.get('pending_exekratys_offering_player')
        self.player_list = game_state['player_list']
        # Full duke catalog for this game's config (every duke that could be in
        # play), snapshot at setup before dealing. Used to surface a per-duke VP
        # projection list when inspecting an opponent's hidden duke. Public
        # information: it never records who owns which duke.
        self.all_dukes = list(game_state.get('all_dukes') or [])
        self.monster_grid = game_state['monster_grid']
        self.monster_stack_areas = list(game_state.get('monster_stack_areas') or [])
        self.citizen_grid = game_state['citizen_grid']
        self.domain_grid = game_state['domain_grid']
        # Finalized dice (used for all game logic checks, harvest matching, etc.).
        self.die_one = game_state['die_one']
        self.die_two = game_state['die_two']
        self.die_sum = game_state['die_sum']
        # Rolled dice (what the RNG produced before any reroll/rig/effect adjustment).
        # These are what the client should display on the dice graphic.
        self.rolled_die_one = game_state.get('rolled_die_one', self.die_one)
        self.rolled_die_two = game_state.get('rolled_die_two', self.die_two)
        self.rolled_die_sum = game_state.get('rolled_die_sum', self.die_sum)
        # Tokens describing notable things about the most recent finalized roll
        # (e.g. "doubles"). Computed from the FINAL dice in finalize_roll,
        # then read by `roll.on_event ...` passives and any later-phase card
        # that cares about what got rolled this turn. Persists until the next
        # finalize_roll.
        self.roll_events = list(game_state.get('roll_events') or [])
        self.exhausted_count = game_state['exhausted_count']
        self.exhausted_stack = list(game_state.get('exhausted_stack') or [])
        # Single global banish pile shared across all players. Cards land here
        # when something explicitly "banishes" them (truly out of play -- distinct
        # from flipped citizens, which stay on a tableau face-down). Entries are
        # the original card objects (Citizen, Monster, ...), in banish order.
        self.banish_pile = list(game_state.get('banish_pile') or [])
        # When a compound special-payout (`A + B + ...`) opens a blocking prompt
        # for leg N, legs N+1.. are stashed here so they fire after the prompt
        # resolves. None when nothing is pending.
        self.pending_payout_continuation = game_state.get('pending_payout_continuation')
        # Crimson Seas "you may Sail" bonus (Dampiar's Workshop). Holds the
        # player_id who has one free Sail available while the `may_sail` prompt is
        # open: consume_player_action lets a single sail action run without
        # spending a regular action, and resolving the sail clears this + resumes
        # the domain activation follow-up. None when no bonus sail is pending.
        self.pending_bonus_sail = game_state.get('pending_bonus_sail')
        # "You may recruit a Citizen" bonus (Town Crier agent). Holds the
        # player_id who has one free Citizen recruit available while the
        # `may_recruit` prompt is open: hire_citizen runs without spending a
        # regular action and waives the +1-per-owned-copy surcharge, then clears
        # this + resumes the activation follow-up. None when no bonus is pending.
        self.pending_bonus_recruit = game_state.get('pending_bonus_recruit')
        self.end_game_triggered = game_state.get('end_game_triggered', False)
        self.final_scores = game_state.get('final_scores', None)
        self.final_result = game_state.get('final_result', None)
        self.effects = game_state['effects']
        self.action_required = game_state['action_required']
        # Concurrent (non-ordered) prompt: all listed players must respond before progression.
        # See module-level _ChooseDukeConcurrentHandler / CONCURRENT_HANDLERS for the protocol.
        self.concurrent_action = game_state.get('concurrent_action') or None
        # Turn/tick tracking
        self.tick_id = game_state.get('tick_id', 0)
        self.turn_number = game_state.get('turn_number', 1)
        self.turn_index = game_state.get('turn_index', 0)
        # roll -> roll_pending -> harvest -> action -> action_end_pending (optional domain cleanup)
        self.phase = game_state.get('phase', 'roll')
        self.actions_remaining = game_state.get('actions_remaining', 0)
        self.harvest_processed = game_state.get('harvest_processed', False)
        self.pending_harvest_choices = game_state.get('pending_harvest_choices', [])
        # Manual harvest session (None = not in a multi-step harvest resolution)
        self.harvest_player_order = game_state.get('harvest_player_order')
        self.harvest_player_idx = game_state.get('harvest_player_idx', 0)
        self.harvest_consumed = game_state.get('harvest_consumed') or {}
        self._harvest_steal_phase_done = game_state.get('_harvest_steal_phase_done', False)
        # Pending "may slay a Monster" prompts queued by citizen harvest payouts.
        # Drained at the end of harvest (after every other harvest payout including
        # special payouts) so the prompt + slay reward always resolves last.
        # Each entry: {"player_id": ..., "source_label": ...}.
        self.pending_harvest_slays = list(game_state.get('pending_harvest_slays') or [])
        self.last_active_time = 0
        self.last_audience_time = 0
        # Display-only action shot clock (see server.py `_shot_clock_*`). Not
        # serialized; re-armed at runtime when waiting on standard_action.
        self.hurry_up_deadline = 0.0
        self.game_log = list(game_state.get('game_log') or [])
        self.pending_action_end_queue = list(game_state.get("pending_action_end_queue") or [])
        self.pending_required_choice = game_state.get("pending_required_choice")
        self._silent_harvest_batch = False
        # Between roll and harvest we allow a small "finalization window" where effects (or dev rigging)
        # may legally change the dice. When present, the engine blocks in roll_pending until finalized.
        self.pending_roll = game_state.get('pending_roll') or None
        self.pending_event_slay_cost = game_state.get('pending_event_slay_cost') or None
        # Activation effects from non-monster Event cards that were revealed while
        # the engine was busy with another prompt. Drained (fired) one at a time
        # at the next idle point. Each entry is a JSON-friendly dict:
        # {"event_id", "name", "activation_effect", "revealing_player_id"}.
        self.pending_event_activations = list(game_state.get('pending_event_activations') or [])
        # Sequential "in turn order" event resolution (e.g. Alms for the Poor,
        # Night Terror, Worthy Sacrifice). Holds the remaining player queue and
        # the per-event params while each player resolves one at a time; None
        # when no sequence is in progress. See EventsEngine._advance_sequence.
        self.pending_event_sequence = game_state.get('pending_event_sequence') or None
        # Undead Samurai Lord event: minions (monsters 57-61) set aside at setup,
        # scattered onto the board one-per-player when the Lord event is revealed.
        # `undead_samurai_pool` holds the minions not yet placed; `..._placed`
        # guards the one-time placement so a re-revealed Lord event won't re-scatter
        # (the minions already on the board stay until the Lord is slain).
        self.undead_samurai_pool = list(game_state.get('undead_samurai_pool') or [])
        self.undead_samurai_placed = bool(game_state.get('undead_samurai_placed', False))
        # Recruit the King's Guard event: the King's Guard citizens set aside at
        # setup, dropped onto the event's board stack when it is revealed and
        # pulled back here while it is un-exhausted. This holds only the guards
        # NOT currently on the board (un-hired and not in play); guards already
        # hired into a player's tableau live there permanently.
        self.kings_guard_pool = list(game_state.get('kings_guard_pool') or [])
        # When a may-slay flow's slay opens a follow-up prompt via the slain
        # monster's `special_reward` (e.g. Warg's `choose m 3 <citizens where
        # name==Peasant>`), we stash the resume info here instead of clobbering
        # the new prompt. Drained when that follow-up resolves and there is no
        # other action_required / pending_payout_continuation pending.
        # Each entry: {"player_id": ..., "resume_kind": ...}. None when idle.
        self.pending_post_slay_resume = game_state.get('pending_post_slay_resume') or None

        # If players were dealt multiple dukes, prompt every such player to keep exactly one.
        # This is a concurrent (non-ordered) action: any player may choose at any time, and
        # the game does not advance into roll/harvest/action until everyone has chosen.
        if not self.concurrent_action:
            duke_choosers = [
                p.player_id for p in self.player_list
                if getattr(p, "owned_dukes", None) and len(p.owned_dukes) > 1
            ]
            if duke_choosers:
                self.concurrent_action = _new_concurrent_action("choose_duke", duke_choosers)
                # Make sure setup-phase advance_tick blocks on the concurrent action.
                if self.phase in ("roll", "harvest", "action"):
                    self.phase = "setup"
            else:
                # No duke choice needed (e.g. 1 duke each); relic selection, if
                # any, becomes the first setup gate.
                self._begin_relic_selection_if_pending()

        if not self.game_log:
            self._log_game_event("Game started.")
        if self.concurrent_action and self.concurrent_action.get("kind") == "choose_duke":
            self._log_game_event("Waiting for each player to choose a duke to keep.")
        elif self.concurrent_action and self.concurrent_action.get("kind") == "choose_relic":
            self._log_game_event("Waiting for each player to choose a relic to keep.")

        # Wire up composed sub-engines. Each engine is a focused class holding
        # a back-reference to this Game instance.
        self.lifecycle = LifecycleEngine(self)
        self.dice = DiceEngine(self)
        self.harvest = HarvestEngine(self)
        self.payouts = PayoutsEngine(self)
        self.choose = ChooseEngine(self)
        self.slay = SlayEngine(self)
        self.domain_effects = DomainEffectsEngine(self)
        self.player_actions = PlayerActionsEngine(self)
        self.endgame = EndgameEngine(self)
        self.events = EventsEngine(self)
        self.agents = AgentsEngine(self)
        self.relics = RelicsEngine(self)
        self._assert_no_engine_method_conflicts()

    def _assert_no_engine_method_conflicts(self):
        seen = {}
        for engine_attr in self._ENGINE_ATTRS:
            engine = getattr(self, engine_attr)
            for method_name, value in vars(type(engine)).items():
                if method_name.startswith("__") or not callable(value):
                    continue
                if method_name in seen:
                    raise RuntimeError(
                        f"Engine method {method_name!r} exists on both "
                        f"{seen[method_name]!r} and {engine_attr!r}."
                    )
                seen[method_name] = engine_attr

    # Public Game API. These thin delegations make the external surface obvious
    # while engines keep ownership of their private implementation helpers.

    def current_player_id(self):
        return self.lifecycle.current_player_id()

    def harvest_slots_for_api(self):
        return self.harvest.harvest_slots_for_api()

    def advance_tick(self):
        return self.lifecycle.advance_tick()

    def consume_player_action(self, player_id, action_type=None):
        return self.lifecycle.consume_player_action(player_id, action_type=action_type)

    def finish_turn_if_no_actions_remaining(self):
        return self.lifecycle.finish_turn_if_no_actions_remaining()

    def resolve_bonus_sail_if_consumed(self):
        return self.lifecycle.resolve_bonus_sail_if_consumed()

    def resolve_bonus_recruit_if_consumed(self):
        return self.lifecycle.resolve_bonus_recruit_if_consumed()

    def finalize_roll(self, player_id, die_one=None, die_two=None):
        return self.lifecycle.finalize_roll(player_id, die_one=die_one, die_two=die_two)

    def reroll_pending_die(self, player_id, die_index):
        return self.lifecycle.reroll_pending_die(player_id, die_index)

    def reroll_both_dice(self, player_id):
        return self.lifecycle.reroll_both_dice(player_id)

    def harvest_phase(self):
        return self.harvest.harvest_phase()

    def harvest_card(self, player_id, slot_key):
        return self.harvest.harvest_card(player_id, slot_key)

    def apply_event_slay_cost(self, player_id, monster_id=None, event_id=None):
        return self.dice.apply_event_slay_cost(
            player_id,
            monster_id=monster_id,
            event_id=event_id,
        )

    def act_on_required_action(self, player_id, action):
        return self.player_actions.act_on_required_action(player_id, action)

    def submit_concurrent_action(self, player_id, response, kind=None):
        return self.player_actions.submit_concurrent_action(player_id, response, kind=kind)

    def hire_citizen(self, player_id, citizen_id, gp=0, mp=0, sp=0, tome_counts=None):
        return self.player_actions.hire_citizen(player_id, citizen_id, gp=gp, mp=mp, sp=sp, tome_counts=tome_counts)

    def slay_monster(self, player_id, monster_id, sp=0, mp=0, gp=0, event_id=None, thunder_axe=None, tome_counts=None):
        return self.player_actions.slay_monster(
            player_id,
            monster_id,
            sp=sp,
            mp=mp,
            gp=gp,
            event_id=event_id,
            thunder_axe=thunder_axe,
            tome_counts=tome_counts,
        )

    def build_domain(self, player_id, domain_id, gp=0, mp=0, sp=0, tome_counts=None):
        return self.player_actions.build_domain(player_id, domain_id, gp=gp, mp=mp, sp=sp, tome_counts=tome_counts)

    def take_resource(self, player_id, resource):
        return self.player_actions.take_resource(player_id, resource)

    def buy_goods(self, player_id, slot_indices, gp=0, mp=0, tome_payment=None):
        return self.player_actions.buy_goods(player_id, slot_indices, gp=gp, mp=mp, tome_payment=tome_payment)

    def buy_tomes(self, player_id, slot_indices, gp=0, mp=0, tome_payment=None):
        return self.player_actions.buy_tomes(player_id, slot_indices, gp=gp, mp=mp, tome_payment=tome_payment)

    def sail_exekratys(self, player_id, resource):
        return self.player_actions.sail_exekratys(player_id, resource)

    def rescue_noble(self, player_id, slot_index, resource, tome_payment=None):
        return self.player_actions.rescue_noble(player_id, slot_index, resource, tome_payment=tome_payment)

    def redeem_tomes_to_score(self, player_id, tome_payment):
        return self.player_actions.redeem_tomes_to_score(player_id, tome_payment)

    def refund_tomes_from_score(self, player_id, counts):
        return self.player_actions.refund_tomes_from_score(player_id, counts)

    def _owned_citizen_count_for_role_selector(self, player, role_selector):
        role = (role_selector or "").strip().lower()
        if not role:
            return 0
        attr = None
        if role == "holy_citizen":
            attr = "holy_count"
        elif role == "shadow_citizen":
            attr = "shadow_count"
        elif role == "soldier_citizen":
            attr = "soldier_count"
        elif role == "worker_citizen":
            attr = "worker_count"
        if not attr:
            return 0
        n = 0
        for c in list(getattr(player, "owned_citizens", []) or []):
            if getattr(c, "is_flipped", False):
                continue
            if int(getattr(c, attr, 0) or 0) > 0:
                n += 1
        return n

    def _citizen_set_flipped(self, citizen, flipped):
        """Face-down citizens do not harvest pay out and do not count for roll-phase per-role spends."""
        citizen.is_flipped = bool(flipped)
        if citizen.is_flipped:
            citizen.toggle_visibility(False)
            citizen.toggle_accessibility(False)
        else:
            citizen.toggle_visibility(True)
            citizen.toggle_accessibility(True)

    def unflip_citizen(self, player_id, citizen_idx):
        """Engine-only: restore one flipped citizen on a player's tableau (not a player-facing action).

        Used for end-of-game scoring or tooling; not exposed on the HTTP API.
        """
        player = self._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        idx = int(_n(citizen_idx))
        oc = list(getattr(player, "owned_citizens", []) or [])
        if idx < 0 or idx >= len(oc):
            raise ValueError("Invalid citizen index.")
        c = oc[idx]
        if not getattr(c, "is_flipped", False):
            raise ValueError("That citizen is not flipped.")
        self._citizen_set_flipped(c, False)

    def unflip_all_citizens_for_final_scoring(self):
        """Face-up every flipped tableau citizen before final VP/tie-break tally (engine-only)."""
        any_flipped = False
        for p in list(getattr(self, "player_list", []) or []):
            for c in list(getattr(p, "owned_citizens", []) or []):
                if getattr(c, "is_flipped", False):
                    any_flipped = True
                    self._citizen_set_flipped(c, False)
        if any_flipped:
            self._log_game_event("Final scoring: restored all flipped citizens face-up.")

    def _domain_set_flipped(self, domain, flipped):
        """Face-down domains (Sapper) have their passive power disabled and are
        hidden on the tableau. Mirrors `_citizen_set_flipped`."""
        domain.is_flipped = bool(flipped)
        if domain.is_flipped:
            domain.toggle_visibility(False)
            domain.toggle_accessibility(False)
        else:
            domain.toggle_visibility(True)
            domain.toggle_accessibility(True)

    def unflip_all_domains_for_final_scoring(self):
        """Face-up every flipped tableau domain before final scoring (engine-only).

        Sapper rules: a flipped Domain is restored face-up and scored as usual at
        the end of the game.
        """
        any_flipped = False
        for p in list(getattr(self, "player_list", []) or []):
            for d in list(getattr(p, "owned_domains", []) or []):
                if getattr(d, "is_flipped", False):
                    any_flipped = True
                    self._domain_set_flipped(d, False)
        if any_flipped:
            self._log_game_event("Final scoring: restored all flipped domains face-up.")

    def _domain_recurring_passive_on_build_turn_cooldown(self, domain):
        """Recurring domain passives cannot be used on the turn the domain was purchased."""
        acq = getattr(domain, "acquired_turn_number", None)
        if acq is None:
            return False
        try:
            return int(acq) == int(getattr(self, "turn_number", 0) or 0)
        except (TypeError, ValueError):
            return False

    def _domain_power_suppressed(self, domain):
        """Single chokepoint consulted by every domain-passive application loop:
        a domain's power does not fire if it is on its build-turn cooldown or if
        it has been flipped face-down by an opponent's Sapper agent."""
        if bool(getattr(domain, "is_flipped", False)):
            return True
        return self._domain_recurring_passive_on_build_turn_cooldown(domain)

    def _player_by_id(self, player_id):
        for p in self.player_list:
            if p.player_id == player_id:
                return p
        return None

    def _player_label(self, player_id):
        if not player_id:
            return "?"
        p = self._player_by_id(player_id)
        if p and getattr(p, "name", None):
            return p.name
        return str(player_id)[:8]

    def crimson_seas_enabled(self):
        """True when this game was dealt from the Crimson Seas preset.

        Crimson Seas adds a whole bundle of mechanics (the Sail/island board,
        maps, tomes, goods, nobles, …). All of that is gated on this single
        check. Other presets may still deal Crimson Seas citizens/monsters
        (e.g. `random`), but those cards are designed to always have a non-map
        "out", so outside the Crimson Seas preset we keep maps invisible/unusable:
        the score pill and +1 Map action are hidden, the standard-action map take
        is rejected, and map options are dropped from `choose` prompts. Any
        incidental map gain still tracks silently on `map_score`.
        """
        return (self.preset or "").strip().lower() == "crimsonseas"

    def agents_enabled(self):
        """True when the Agents module was dealt at setup."""
        return bool(self.include_agents and (self.agents_slots or self.agents_deck))

    def relics_enabled(self):
        """True when the Relics module was dealt at setup."""
        return bool(self.include_relics)

    def relic_consumes_action(self, player_id):
        """True when the player's kept relic spends a standard action when used
        (its text reads "As an action ..."). Used by the server to gate/consume
        an action around `use_relic`."""
        player = self._player_by_id(player_id)
        relics = list(getattr(player, "owned_relics", []) or []) if player else []
        if not relics:
            return False
        return bool(getattr(relics[0], "consumes_action", False))

    def relic_available_for(self, player_id):
        """True when `player_id` may use their relic right now: relics in play,
        it's their action phase, they hold a relic, and they have not already
        used it this turn."""
        if not self.relics_enabled():
            return False
        if getattr(self, "phase", None) != "action":
            return False
        if player_id != self.current_player_id():
            return False
        player = self._player_by_id(player_id)
        relics = list(getattr(player, "owned_relics", []) or []) if player else []
        if not relics:
            return False
        if self.relic_used_turn.get(str(player_id)) == int(self.turn_number):
            return False
        relic = relics[0]
        # Passive/triggered relics (Evermap, Violet Ring) fire automatically on a
        # game event; they are never clickable and never glow.
        if self.relics._relic_is_passive(relic):
            return False
        # An implemented relic the player cannot pay for must not glow / be
        # clickable; an unimplemented relic still uses the no-op stub path.
        if self.relics._relic_is_implemented(relic) and not self.relics._player_can_afford_relic(player, relic):
            return False
        # An "As an action" relic needs a standard action to spend.
        if getattr(relic, "consumes_action", False) and int(getattr(self, "actions_remaining", 0) or 0) <= 0:
            return False
        return True

    def use_relic(self, player_id):
        """Use the active player's relic for the turn. Validates the
        once-per-turn gate, then resolves the relic's effect (implemented
        relics execute their `passive_effect`; unimplemented relics fall back to
        a no-op stub that only clears the glow)."""
        if not self.relics_enabled():
            raise ValueError("Relics are not in play this game.")
        if player_id != self.current_player_id():
            raise ValueError("You can only use your relic on your turn.")
        if getattr(self, "phase", None) != "action":
            raise ValueError("You can only use your relic during your action phase.")
        player = self._player_by_id(player_id)
        relics = list(getattr(player, "owned_relics", []) or []) if player else []
        if not relics:
            raise ValueError("You have no relic to use.")
        if self.relic_used_turn.get(str(player_id)) == int(self.turn_number):
            raise ValueError("You have already used your relic this turn.")
        relic = relics[0]
        if self.relics._relic_is_passive(relic):
            raise ValueError("That relic's power is passive and triggers automatically.")
        implemented = self.relics._relic_is_implemented(relic)
        if implemented and not self.relics._player_can_afford_relic(player, relic):
            raise ValueError("You cannot afford to use that relic.")
        self.relic_used_turn[str(player_id)] = int(self.turn_number)
        if implemented:
            self.relics._apply_relic_effect(player, relic)
        else:
            self._log_game_event(
                f"{self._player_label(player_id)} used relic \"{getattr(relic, 'name', '?')}\"."
            )
        return True

    def _begin_relic_selection_if_pending(self):
        """Open the `choose_relic` concurrent gate if any player still holds
        more than one dealt relic. Returns True when a gate was opened.

        Called once at construction (when there is no duke choice) and again
        when duke selection finalizes, so relic selection always follows duke
        selection."""
        ca = getattr(self, "concurrent_action", None) or None
        if ca and (ca.get("pending") or []):
            return False
        relic_choosers = [
            p.player_id for p in self.player_list
            if getattr(p, "owned_relics", None) and len(p.owned_relics) > 1
        ]
        if not relic_choosers:
            return False
        self.concurrent_action = _new_concurrent_action("choose_relic", relic_choosers)
        if self.phase in ("roll", "harvest", "action"):
            self.phase = "setup"
        return True

    def engage_agent(self, player_id, slot_index):
        return self.agents.engage_agent(player_id, slot_index)

    def _pirate_blockade_in_play(self):
        """True if a Pirate Blockade monster event is currently on the board.

        Identified by its roll-effect marker (`block_recruit_matching_roll`) so
        the check is card-agnostic. The blockade fires its roll effect each roll
        phase, but the actual recruit/gain restriction is evaluated on demand
        (see `_pirate_blockade_blocked_roll_values`) so slaying the ship lifts
        the restriction immediately.
        """
        for grid in (self.monster_grid, self.citizen_grid, self.domain_grid):
            for stack in (grid or []):
                if not stack:
                    continue
                top = stack[-1]
                if not isinstance(top, Event) or not bool(getattr(top, "is_monster", 0)):
                    continue
                raw = (getattr(top, "roll_effect", None) or "").strip().lower()
                if raw.split(" ", 1)[0] == "block_recruit_matching_roll":
                    return True
        return False

    def _pirate_blockade_blocked_roll_values(self):
        """The set of citizen roll-match values that may not be recruited/gained
        this turn while Pirate Blockade is in play, else an empty set.

        Only active during the active player's Action Phase (the card text scopes
        the restriction to "the Action Phase"); reads this turn's FINAL dice.
        """
        if (getattr(self, "phase", None) or "") != "action":
            return set()
        if not self._pirate_blockade_in_play():
            return set()
        vals = set()
        for v in (self.die_one, self.die_two, self.die_sum):
            try:
                iv = int(v)
            except (TypeError, ValueError):
                continue
            if iv > 0:
                vals.add(iv)
        return vals

    def _citizen_blocked_by_pirate_blockade(self, citizen):
        """True if `citizen` may not be recruited/gained right now because its
        roll match equals one of the values blocked by an in-play Pirate
        Blockade."""
        if citizen is None:
            return False
        blocked = self._pirate_blockade_blocked_roll_values()
        if not blocked:
            return False
        for attr in ("roll_match1", "roll_match2"):
            try:
                rv = int(getattr(citizen, attr, 0) or 0)
            except (TypeError, ValueError):
                continue
            if rv in blocked:
                return True
        return False

    def _player_scores_line(self, player, gold_delta=0, strength_delta=0, magic_delta=0):
        if not player:
            return "G?/S?/M?/VP?/P?"
        g = int(getattr(player, "gold_score", 0) or 0) + int(gold_delta or 0)
        s = int(getattr(player, "strength_score", 0) or 0) + int(strength_delta or 0)
        m = int(getattr(player, "magic_score", 0) or 0) + int(magic_delta or 0)
        v = int(getattr(player, "victory_score", 0) or 0)
        p = int(getattr(player, "map_score", 0) or 0)
        return f"G{g}/S{s}/M{m}/VP{v}/P{p}"

    def _format_resource_payment(self, gp, sp, mp):
        gp, sp, mp = _n(gp), _n(sp), _n(mp)
        if gp == 0 and sp == 0 and mp == 0:
            return "no gold/strength/magic spent"
        parts = []
        if gp:
            parts.append(f"{gp} gold")
        if sp:
            parts.append(f"{sp} strength")
        if mp:
            parts.append(f"{mp} magic")
        return "spent " + ", ".join(parts)

    def _log_game_event(self, message):
        if not hasattr(self, "game_log") or self.game_log is None:
            self.game_log = []
        self.game_log.append({
            "tick": int(getattr(self, "tick_id", 0) or 0),
            "msg": str(message),
        })

    def _player_is_resting(self, player_or_id):
        """True if `player_or_id` (a Player or a player_id string) is the resting seat this turn."""
        rid = self.resting_player_id()
        if rid is None or player_or_id is None:
            return False
        if hasattr(player_or_id, "player_id"):
            pid = player_or_id.player_id
        else:
            pid = player_or_id
        return pid == rid

    def _player_is_negative_effect_target(self, player_or_id):
        """True if a "negative" citizen / domain / monster / event effect is allowed
        to target `player_or_id`.

        At 5 players the resting seat is "not in play" while it has the resting
        effect, so it is excluded as a target for negative effects (steal,
        all_lose, flip, banish-citizen, take-from-player, take-owned-card,
        Cursed Cavern's concurrent flip, etc.). Positive effects (e.g.
        `pay_to_player`) still resolve normally — the rule book carves out
        "negative" specifically.
        """
        return not self._player_is_resting(player_or_id)

    def resting_player_id(self):
        """Return the player_id of the "resting" player this turn, else None.

        At 5 players the rulebook adds a "resting" mechanic: each turn the
        player who would have rolled immediately before the active player
        sits the harvest out (no on-turn or off-turn payouts, no steal pre-
        phase activations, no end-of-harvest "no payout" consolation). The
        resting seat rotates with the active seat so every player rests
        exactly once every 5 turns.

        At 2-4 or 6+ players there is no resting seat and this returns None.
        """
        n = len(self.player_list)
        if n != 5:
            return None
        t = int(self.turn_index) % n
        return self.player_list[(t - 1) % n].player_id

    def _harvest_player_id_order_starting_active(self):
        n = len(self.player_list)
        if n == 0:
            return []
        t = int(self.turn_index) % n
        order = [self.player_list[(t + i) % n].player_id for i in range(n)]
        # 5-player resting: the seat immediately BEFORE the active player
        # sits the harvest out. Excluding them from the order skips both the
        # steal pre-phase scan and their normal payouts in one shot.
        resting = self.resting_player_id()
        if resting is not None:
            order = [pid for pid in order if pid != resting]
        return order

    def _active_areas(self):
        """Areas in play this game (the 5 chosen at setup), with Constants.areas as a
        fallback for legacy game state that predates `monster_stack_areas`.

        Used by anything that needs to enumerate or validate areas: count-area payouts,
        owned_monster_attributes buckets, etc. Lets expansion areas (Gnolls, Undead
        Samurai, ...) participate in `count area X` grammar without hardcoding them.
        """
        out = list(getattr(self, "monster_stack_areas", None) or [])
        return out if out else list(Constants.areas)

    def owned_monster_attributes(self, player_id):
        active_areas = self._active_areas()
        return_dict = {attr: 0 for attr in active_areas + Constants.types}
        for player in self.player_list:
            if player.player_id == player_id:
                for monster in player.owned_monsters:
                    area = getattr(monster, "area", None)
                    if area in return_dict:
                        return_dict[area] += 1
                    m_type = getattr(monster, "monster_type", None)
                    if m_type in return_dict:
                        return_dict[m_type] += 1

        return return_dict

    def _owned_monster_name_count(self, player_or_id, name):
        """Count owned monsters with an exact name match (case-insensitive)."""
        want = (name or "").strip().lower()
        if not want:
            return 0
        player = player_or_id
        if not hasattr(player, "owned_monsters"):
            player = self._player_by_id(player_or_id)
        if not player:
            return 0
        n = 0
        for monster in list(getattr(player, "owned_monsters", []) or []):
            if (getattr(monster, "name", "") or "").strip().lower() == want:
                n += 1
        return n

    def _owned_monster_type_count(self, player_or_id, monster_type):
        """Count owned monsters with an exact monster_type match (case-insensitive)."""
        want = (monster_type or "").strip().lower()
        if not want:
            return 0
        player = player_or_id
        if not hasattr(player, "owned_monsters"):
            player = self._player_by_id(player_or_id)
        if not player:
            return 0
        n = 0
        for monster in list(getattr(player, "owned_monsters", []) or []):
            if (getattr(monster, "monster_type", "") or "").strip().lower() == want:
                n += 1
        return n

    def _monster_special_cost_deltas(self, player_or_id, special_cost):
        """Return {g, s, m} slay-cost deltas from a compound special_cost string."""
        deltas = {"g": 0, "s": 0, "m": 0}
        raw = (special_cost or "").strip()
        if not raw:
            return deltas
        for part in raw.split(" + "):
            part = (part or "").strip()
            if not part:
                continue
            tokens = self.payouts._tokenize_payout(part)
            if len(tokens) < 5:
                continue
            if tokens[0].lower() != "count" or tokens[1].lower() != "owned_monster_name":
                continue
            resource = tokens[3].lower()
            if resource not in deltas:
                continue
            try:
                mult = int(tokens[4])
            except (TypeError, ValueError):
                continue
            total = self._owned_monster_name_count(player_or_id, tokens[2]) * mult
            deltas[resource] += total
        return deltas

    def _player_build_role_totals(self, player):
        """Role-icon totals usable to satisfy a Domain's build prerequisites.

        Per the Crimson Seas rules, both Citizens AND Nobles in your tableau
        contribute their Citizen Role icons toward a Domain's required roles.
        Nobles carry the same shadow/holy/soldier/worker counts as Citizens, so
        they are summed alongside them here. Starters and owned Domains never
        count. Outside Crimson Seas a player simply has no Nobles, so this is
        equivalent to the old citizen-only tally in every other mode.
        """
        totals = {"shadow": 0, "holy": 0, "soldier": 0, "worker": 0}
        role_holders = list(getattr(player, "owned_citizens", []) or []) \
            + list(getattr(player, "owned_nobles", []) or [])
        for c in role_holders:
            totals["shadow"] += int(getattr(c, "shadow_count", 0) or 0)
            totals["holy"] += int(getattr(c, "holy_count", 0) or 0)
            totals["soldier"] += int(getattr(c, "soldier_count", 0) or 0)
            totals["worker"] += int(getattr(c, "worker_count", 0) or 0)
        return totals

    def _player_has_take_immunity(self, player):
        """True if the player owns a domain granting immunity to "take" effects.

        Castle of the Seven Suns (`immunity.take`) reads, with the operator
        legend, "Opponents cannot take you" where "you" includes both the
        player AND any of their cards or Resources. So this immunity covers
        every "take" surface — citizen `steal`, domain `take_from_player`,
        and domain `take_owned` — but does not cover other operators like
        `banish` (Sunder Bay), `flip` (Cursed Cavern, monster targeted flip),
        or global `all_lose` events.

        The legacy passive string `immunity.steal` is also accepted so older
        DB rows keep working until they're migrated to `immunity.take`.
        """
        for d in list(getattr(player, "owned_domains", []) or []):
            if self._domain_power_suppressed(d):
                continue
            raw = (getattr(d, "passive_effect", None) or "")
            effect = str(raw).strip().lower()
            if effect in ("immunity.take", "immunity.steal"):
                return True
        return False

    def _player_has_action_effect_flag(self, player, flag_name):
        target = (flag_name or "").strip().lower()
        if not target:
            return False
        # Event-granted "rest of the game" flags (Blessed Lands, Dark Lord
        # Rising, ...) live on the player and have no build-turn cooldown.
        for g in list(getattr(player, "granted_effects", None) or []):
            if str(g or "").strip().lower() == target:
                return True
        for d in list(getattr(player, "owned_domains", []) or []):
            if self._domain_power_suppressed(d):
                continue
            name = str(getattr(d, "name", "") or "").strip().lower()
            text = str(getattr(d, "text", "") or "").strip().lower()
            raw = (getattr(d, "passive_effect", None) or "")
            effect = str(raw).strip().lower()
            if effect:
                if effect == target:
                    return True
                if effect.startswith("effect.add "):
                    added = effect[len("effect.add "):].strip()
                    if added == target:
                        return True
            if target == "action.browncoatssanctum":
                if name == "browncoat's sanctum" or (
                    "tomes cost" in text and "1 gold less" in text
                ):
                    return True
            if target == "action.portofdrake":
                if name == "port of drake" or (
                    "goods cost" in text and "1 gold less" in text
                ):
                    return True
            if target == "action.muratreis":
                if name == "murat reis" or (
                    "+wild" in text.replace(" ", "") and "rescuing a noble" in text
                ):
                    return True
        return False


