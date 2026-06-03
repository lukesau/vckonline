"""LifecycleEngine -- composed sub-engine of Game.

This engine owns one area of game behavior; each method body retains its
original logic from the pre-split Game class. Access game state via `self.game.<attr>`, call cross-engine
methods via `self.game.<engine>.<method>` (e.g. `self.game.payouts.foo()`),
and call shared state utilities via `self.game.<util>` (e.g.
`self.game._log_game_event(...)`).
"""
import random
import time
from constants import *
from cards import *
from game_setup import DEBUG_DIE_ONE_VALUES, DEBUG_DIE_TWO_VALUES
from game_helpers import (
    _n,
    _validate_hire_or_domain_gold_payment,
    _validate_monster_slay_payment,
    _citizen_has_steal,
    _parse_domain_effect_kv,
    _parse_resource_kv,
    _player_resource_balances,
    _balances_allow_payout,
    _GAME_LOG_MAX,
)
from game_concurrent import CONCURRENT_HANDLERS, _new_concurrent_action


class LifecycleEngine:
    def __init__(self, game):
        self.game = game

    def current_player_id(self):
        if not self.game.player_list:
            return None
        if self.game.turn_index < 0 or self.game.turn_index >= len(self.game.player_list):
            self.game.turn_index = 0
        return self.game.player_list[self.game.turn_index].player_id

    def start_new_turn_if_needed(self):
        if self.game.phase != 'roll':
            return
        if self.game.actions_remaining != 0:
            self.game.actions_remaining = 0

    def is_blocked_on_concurrent_action(self):
        """True iff a concurrent (non-ordered) prompt still has pending participants."""
        ca = getattr(self.game, "concurrent_action", None) or None
        if not ca:
            return False
        return bool(ca.get("pending"))

    def advance_tick(self):
        """
        Advance the game by one deterministic tick.
        This is intentionally small-grained so the server can call it implicitly.
        """
        if self.game.phase == 'game_over':
            return False

        # Block on any active concurrent (non-ordered) prompt first.
        if self.is_blocked_on_concurrent_action():
            return False

        # Block only on required player choices (not on standard action prompts)
        if self.game.action_required and self.game.action_required.get("id") and self.game.action_required.get("id") != self.game.game_id:
            aa = str(self.game.action_required.get("action", "") or "")
            if (
                self.game.action_required.get("action") == "bonus_resource_choice"
                or aa == "manual_harvest"
                or aa == "harvest_optional_exchange"
                or aa == "harvest_steal"
                or aa == "harvest_wild_gain_exchange"
                or aa == "harvest_wild_cost_exchange"
                or aa == "choose_domain_reward"
                or aa == "choose_monster_slay"
                or aa == "slay_monster_payment"
                or aa.startswith("choose ")
                or aa.startswith("choose_player")
                or aa.startswith("choose_monster")
                or aa.startswith("choose_owned")
                or aa == "domain_self_convert"
                or aa == "domain_choose_resource"
                or aa == "event_slay_cost_choice"
                or aa == "event_gain_action"
                or aa == "event_active_choose"
                or aa == "event_sequence"
                or aa == "choose_domain_to_build"
            ):
                return False

        # Fire any activation effects from non-monster Event cards that were
        # revealed while the engine was busy. Draining one may itself open a
        # prompt / concurrent action; if so, the loop above will block on the
        # next advance_tick until it resolves.
        if getattr(self.game, "pending_event_activations", None):
            self.game.events.drain_pending_event_activations()
            if self.is_blocked_on_concurrent_action():
                return False
            ar2 = self.game.action_required or {}
            if ar2.get("id") and ar2.get("id") != self.game.game_id and str(ar2.get("action", "") or "") not in ("", "standard_action"):
                return False

        if self.game.phase == "setup":
            # Setup only progresses when required choices are resolved.
            # Once no longer blocked, begin the normal turn loop.
            blocked_ar = bool(
                self.game.action_required
                and self.game.action_required.get("id")
                and self.game.action_required.get("id") != self.game.game_id
            )
            if not blocked_ar:
                self.game.phase = "roll"
                self.game.tick_id += 1
                self.game._log_game_event("Setup complete; turns begin.")
                return True
            return False

        if self.game.phase == 'roll':
            self.roll_phase()
            self.game.tick_id += 1
            who = self.game._player_label(self.current_player_id())
            rd1 = int(getattr(self.game, "rolled_die_one", 0) or 0)
            rd2 = int(getattr(self.game, "rolled_die_two", 0) or 0)
            rds = int(getattr(self.game, "rolled_die_sum", rd1 + rd2) or (rd1 + rd2))
            self.game._log_game_event(
                f"Turn {int(self.game.turn_number)} ({who}): rolled {rd1}+{rd2}={rds}."
            )
            return True

        if self.game.phase == 'roll_pending':
            # Waiting for the roll to be finalized (possibly changed by an effect / dev rig).
            return False

        if self.game.phase == 'action_end_pending':
            # End-of-action domain prompts (pay/take vs another player). Same blocking rules as
            # finishing the action phase with actions_remaining == 0.
            aid = self.game.action_required.get("id") if self.game.action_required else None
            aact = str(self.game.action_required.get("action", "") or "") if self.game.action_required else ""
            if aid and aid != self.game.game_id and aact and aact != "standard_action":
                return False
            if self.game.pending_action_end_queue:
                return False
            finisher = self.game._player_label(self.current_player_id())
            if not self.game.end_game_triggered:
                reason = self.game.endgame._check_end_game_condition()
                if reason:
                    self.game.end_game_triggered = True
                    self.game._log_game_event(f"End-game condition met ({reason}); finishing this round.")
            self._reveal_hidden_domain_stack_tops()
            self.game.turn_index = (self.game.turn_index + 1) % max(1, len(self.game.player_list))
            self.game.turn_number = int(self.game.turn_number) + 1
            if self.game.end_game_triggered and self.game.player_list[self.game.turn_index].is_first:
                self.game._log_game_event(f"{finisher} ended their turn.")
                self.game.endgame._finalize_game()
                return True
            self.game.phase = 'roll'
            self.game.actions_remaining = 0
            self.game.action_required["id"] = self.game.game_id
            self.game.action_required["action"] = ""
            self.game.tick_id += 1
            self.game._log_game_event(f"{finisher} ended their turn.")
            progressed = False
            while self.game.phase in ('roll', 'harvest'):
                if not self.advance_tick():
                    break
                progressed = True
            return True or progressed

        if self.game.phase == 'harvest':
            # Manual harvest: players resolve matching starters/citizens in turn order (active player first).
            if not getattr(self.game, "harvest_processed", False):
                if getattr(self.game, "harvest_player_order", None) is None:
                    for p in self.game.player_list:
                        p.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
                    self.game.harvest_consumed = {}
                    self.game.harvest_player_idx = 0
                    self.game.harvest_player_order = self.game._harvest_player_id_order_starting_active()
                    self.game._harvest_steal_phase_done = False
                    resting_pid = self.game.resting_player_id()
                    if resting_pid is not None:
                        self.game._log_game_event(
                            f"{self.game._player_label(resting_pid)} is resting (5-player rule); no harvest this turn."
                        )
                    # Harvest-phase domain passives (e.g. Jousting Field) must run after deltas are
                    # cleared for the new harvest round, not during finalize_roll (which ran before
                    # this reset and would lose passive contributions from harvest_delta tracking).
                    active = self.game._player_by_id(self.current_player_id())
                    self.game.harvest._apply_harvest_jousting_passive(active)
                self.game.harvest._harvest_run_automation_until_blocked()
            # Harvest may open an unordered concurrent gate (e.g. concurrent
            # non-steal harvest decisions). If that happens inside this
            # advance_tick call, we must pause here so we don't jump into the
            # action phase while `concurrent_action.pending` is still non-empty.
            if self.is_blocked_on_concurrent_action():
                return False

            # If harvest triggered a required choice, pause progression here.
            if self.game.action_required and self.game.action_required.get("id") and self.game.action_required.get("id") != self.game.game_id:
                self.game.phase = 'harvest'
                self.game.tick_id += 1
                if self.game.action_required.get("action") == "manual_harvest":
                    return False
                return True

            self.game.phase = 'action'
            # baseline actions per turn; may become effect-driven later
            self.game.actions_remaining = max(0, int(self.game.actions_remaining) or 2)
            # During action phase, mark that we're waiting on the active player to act.
            self.game.action_required["id"] = self.current_player_id()
            self.game.action_required["action"] = "standard_action"
            self.game.tick_id += 1
            ap = self.game._player_label(self.current_player_id())
            self.game._log_game_event(
                f"Harvest finished; {ap}'s action phase ({int(self.game.actions_remaining)} action(s))."
            )
            active = self.game._player_by_id(self.current_player_id())
            self.game.domain_effects._apply_action_start_domain_passives(active)
            # Offer any additional-action grant (e.g. The Wizards of Nae) that was
            # revealed earlier this turn outside the Action Phase. Drained here so
            # the active player can pay for the extra action and spend it now.
            self.game.events.drain_pending_event_activations()
            return True

        if self.game.phase == 'action':
            # Action ticks are driven by explicit player actions; if we're out of actions, advance seat.
            if int(self.game.actions_remaining) > 0:
                # Ensure action_required stays on the active player during their action window.
                self.game.action_required["id"] = self.current_player_id()
                self.game.action_required["action"] = "standard_action"
                return False
            aid = self.game.action_required.get("id") if self.game.action_required else None
            aact = str(self.game.action_required.get("action", "") or "") if self.game.action_required else ""
            if aid and aid != self.game.game_id and aact and aact != "standard_action":
                return False
            finisher = self.game._player_label(self.current_player_id())
            if not self.game.end_game_triggered:
                reason = self.game.endgame._check_end_game_condition()
                if reason:
                    self.game.end_game_triggered = True
                    self.game._log_game_event(f"End-game condition met ({reason}); finishing this round.")
            self._reveal_hidden_domain_stack_tops()
            self.game.turn_index = (self.game.turn_index + 1) % max(1, len(self.game.player_list))
            self.game.turn_number = int(self.game.turn_number) + 1
            if self.game.end_game_triggered and self.game.player_list[self.game.turn_index].is_first:
                self.game._log_game_event(f"{finisher} ended their turn.")
                self.game.endgame._finalize_game()
                return True
            self.game.phase = 'roll'
            self.game.actions_remaining = 0
            # Leaving action phase: clear the standard action prompt.
            self.game.action_required["id"] = self.game.game_id
            self.game.action_required["action"] = ""
            self.game.tick_id += 1
            self.game._log_game_event(f"{finisher} ended their turn.")

            # Auto-run the beginning-of-turn roll/harvest so the game lands in action phase.
            progressed = False
            while self.game.phase in ('roll', 'harvest'):
                if not self.advance_tick():
                    break
                progressed = True
            return True or progressed

        # Unknown phase; reset safely
        self.game.phase = 'roll'
        self.game.tick_id += 1
        return True

    # ----------------------------------------------------------------------
    # Standard action consumption
    # ----------------------------------------------------------------------

    def _refresh_action_phase_required(self, player_id):
        """
        After a consume / rollback, set action_required to the appropriate idle
        state for the action phase. Leaves non-idle prompts (choose_*,
        domain_self_convert, etc.) untouched.
        """
        ar = getattr(self.game, "action_required", None)
        if not isinstance(ar, dict):
            return
        aa = str(ar.get("action", "") or "")
        if aa not in ("", "standard_action"):
            return
        ar.clear()
        ar["id"] = player_id
        ar["action"] = "standard_action"

    def consume_player_action(self, player_id, action_type=None):
        """
        Consume one regular action for the active player.

        When this drops actions_remaining to 0, the turn is not advanced here:
        the caller must apply the hire/build/slay/take first, then call
        finish_turn_if_no_actions_remaining() so logs and engine state stay ordered.
        """
        if self.game.phase == "action_end_pending":
            return False

        if self.is_blocked_on_concurrent_action():
            return False

        if self.game.phase != 'action':
            # If an action comes in early, fast-forward to action phase.
            while self.advance_tick():
                if self.game.phase == 'action':
                    break

        # Block while waiting on any active per-player prompt that isn't the
        # idle "standard_action" placeholder. This includes the new immediate
        # slay prompts (choose_monster_slay / slay_monster_payment), as well as
        # the existing choose_* / harvest_* / domain_self_convert prompts.
        if self.game.action_required and self.game.action_required.get("id") and self.game.action_required.get("id") != self.game.game_id:
            aa = str(self.game.action_required.get("action", "") or "")
            blocking = aa in (
                "bonus_resource_choice",
                "manual_harvest",
                "harvest_optional_exchange",
                "harvest_steal",
                "harvest_wild_gain_exchange",
                "harvest_wild_cost_exchange",
                "choose_domain_reward",
                "domain_self_convert",
                "domain_choose_resource",
                "choose_monster_slay",
                "slay_monster_payment",
                "choose_domain_to_build",
                "event_gain_action",
                "event_active_choose",
                "event_sequence",
            ) or aa.startswith("choose ") or aa.startswith("choose_player") or aa.startswith(
                "choose_monster"
            ) or aa.startswith("choose_owned")
            if blocking:
                return False

        if player_id != self.current_player_id():
            return False

        if self.game.actions_remaining is None:
            self.game.actions_remaining = 2
        regulars = int(self.game.actions_remaining)
        if regulars <= 0:
            return False

        self.game.actions_remaining = regulars - 1
        self.game._last_consumed_action_marker = ("regular", None)

        self.game.tick_id += 1
        self._refresh_action_phase_required(player_id)
        return True

    def rollback_last_consumed_action(self):
        """Undo the most recent consume_player_action when the underlying action failed."""
        marker = getattr(self.game, "_last_consumed_action_marker", None)
        if not marker:
            self.game.actions_remaining = int(getattr(self.game, "actions_remaining", 0)) + 1
            self.game.tick_id = int(getattr(self.game, "tick_id", 0)) - 1
            return
        kind_a, _kind_b = marker
        if kind_a == "regular":
            self.game.actions_remaining = int(getattr(self.game, "actions_remaining", 0)) + 1
        self.game.tick_id = int(getattr(self.game, "tick_id", 0)) - 1
        self.game._last_consumed_action_marker = None
        self._refresh_action_phase_required(self.current_player_id())

    def finish_turn_if_no_actions_remaining(self):
        """After a successful standard action, advance roll/harvest if the turn was just spent."""
        if getattr(self.game, "phase", None) != "action" or int(getattr(self.game, "actions_remaining", 0) or 0) != 0:
            return
        if self.is_blocked_on_concurrent_action():
            return
        ar = getattr(self.game, "action_required", None) or {}
        aid = ar.get("id")
        aact = str(ar.get("action", "") or "").strip()
        if aid and aid != self.game.game_id and aact not in ("", "standard_action"):
            return
        if self.game.domain_effects._start_action_end_domain_sequence(self.current_player_id()):
            return
        self.advance_tick()

    def roll_phase(self):
        # Roll the RNG dice first (display value). In debug mode the value
        # sets are constrained (see DEBUG_DIE_ONE_VALUES / DEBUG_DIE_TWO_VALUES
        # in game_setup.py) so the granted roll-modifier domains can steer
        # each die to any value 1..6. Everything downstream of this point
        # (pending_roll, finalize_roll, _apply_roll_modification, harvest
        # matching, roll_events) is unchanged -- only the source distribution
        # of d1/d2 differs.
        if self.game.debug_mode:
            d1 = random.choice(DEBUG_DIE_ONE_VALUES)
            d2 = random.choice(DEBUG_DIE_TWO_VALUES)
        else:
            d1 = random.randint(1, 6)
            d2 = random.randint(1, 6)
        ds = d1 + d2
        self.game.rolled_die_one = d1
        self.game.rolled_die_two = d2
        self.game.rolled_die_sum = ds

        # Start a "pending roll" window. For now we always open the window; later effects
        # can choose to auto-finalize or pause based on game state.
        self.game.pending_roll = {"rolled_die_one": d1, "rolled_die_two": d2, "rolled_die_sum": ds}
        self.game.phase = "roll_pending"
        self.game.action_required["id"] = self.current_player_id()
        self.game.action_required["action"] = "finalize_roll"
        # Reset per-turn Twilight Palace re-roll token.
        self.game._pending_reroll_twilight_used = False
        # Reset per-turn Blood Moon Palace re-roll token.
        self.game._pending_reroll_blood_moon_used = False

        # Default final dice are unset until finalized.
        # (We intentionally do not touch self.game.die_one/die_two here.)

    def finalize_roll(self, player_id, die_one=None, die_two=None):
        if self.game.phase != "roll_pending":
            raise ValueError("Not waiting to finalize a roll")
        if player_id != self.current_player_id():
            raise ValueError("Only the active player may finalize the roll")

        rolled = self.game.pending_roll or {}
        rd1 = int(rolled.get("rolled_die_one") or 0)
        rd2 = int(rolled.get("rolled_die_two") or 0)
        if rd1 < 1 or rd1 > 6 or rd2 < 1 or rd2 > 6:
            raise ValueError("Pending roll is invalid")

        fd1 = rd1 if die_one is None else int(die_one)
        fd2 = rd2 if die_two is None else int(die_two)
        if fd1 < 1 or fd1 > 6 or fd2 < 1 or fd2 > 6:
            raise ValueError("Final dice must be between 1 and 6")
        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found")
        changed = (fd1 != rd1) or (fd2 != rd2)
        if changed:
            if not self.game.dice._apply_roll_modification(player, rd1, rd2, fd1, fd2):
                raise ValueError("Illegal roll modification")

        self.game.die_one = fd1
        self.game.die_two = fd2
        self.game.die_sum = fd1 + fd2

        # Compute roll-event tokens from the FINAL dice (post-modification).
        # A player who spends modifiers to land on doubles legitimately
        # triggered doubles for this roll; the engine treats final-dice
        # doubles the same as a naturally-rolled pair. Same reasoning as why
        # the starter `activation_trigger doubles` leg reads
        # `self.game.die_one == self.game.die_two` -- both views agree on what "the
        # roll" was.
        self.game.roll_events = self.game.dice._compute_roll_events(fd1, fd2)
        self.game.dice._apply_roll_on_event_passives()
        self.game.dice._apply_board_event_roll_effects(fd1, fd2)
        self.game.events.apply_board_event_passive_roll_effects()

        self.game.pending_roll = None
        # Move into harvest exactly like the old post-roll transition.
        self.game.phase = "harvest"
        self.game.harvest_processed = False
        self.game.harvest_player_order = None
        self.game.harvest_player_idx = 0
        self.game.harvest_consumed = {}
        self.game._harvest_steal_phase_done = False

        # Clear the finalize prompt; harvest/action will set prompts as needed.
        # But preserve action_required when an event roll effect needs a player choice.
        if (self.game.action_required.get("action") or "") != "event_slay_cost_choice":
            self.game.action_required["id"] = self.game.game_id
            self.game.action_required["action"] = ""
        # Fire Northern Wall optional Minion-banish (only if nothing else is pending).
        if not (self.game.action_required.get("action") or ""):
            self.game.payouts._maybe_fire_northern_wall_banish(player_id)
        self.game.tick_id += 1
        who = self.game._player_label(self.current_player_id())
        if fd1 == rd1 and fd2 == rd2:
            self.game._log_game_event(
                f"Turn {int(self.game.turn_number)} ({who}): roll finalized at {fd1}+{fd2}={self.game.die_sum}."
            )
        else:
            self.game._log_game_event(
                f"Turn {int(self.game.turn_number)} ({who}): roll changed {rd1}+{rd2}={rd1+rd2} -> {fd1}+{fd2}={self.game.die_sum}."
            )

    def reroll_pending_die(self, player_id, die_index):
        """Re-roll one die during the roll_pending phase (Twilight Palace passive).

        die_index: 1 or 2. Generates a new random value, updates pending_roll,
        and marks the Twilight Palace token as consumed for this roll phase.
        """
        if self.game.phase != "roll_pending":
            raise ValueError("Not in roll_pending phase.")
        if player_id != self.current_player_id():
            raise ValueError("Only the active player may re-roll a die.")
        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        if not self.game._player_has_action_effect_flag(player, "roll.reroll_one_die"):
            raise ValueError("Player does not own Twilight Palace (or it is on build-turn cooldown).")
        if getattr(self.game, "_pending_reroll_twilight_used", False):
            raise ValueError("Twilight Palace re-roll already used this roll phase.")
        die_index = int(die_index)
        if die_index not in (1, 2):
            raise ValueError("die_index must be 1 or 2.")
        rolled = self.game.pending_roll or {}
        new_val = random.randint(1, 6)
        if die_index == 1:
            old_val = int(rolled.get("rolled_die_one", 1) or 1)
            rolled["rolled_die_one"] = new_val
            self.game.rolled_die_one = new_val
        else:
            old_val = int(rolled.get("rolled_die_two", 1) or 1)
            rolled["rolled_die_two"] = new_val
            self.game.rolled_die_two = new_val
        rolled["rolled_die_sum"] = int(rolled.get("rolled_die_one", 1)) + int(rolled.get("rolled_die_two", 1))
        self.game.rolled_die_sum = rolled["rolled_die_sum"]
        self.game.pending_roll = rolled
        self.game._pending_reroll_twilight_used = True
        self.game.tick_id += 1
        who = self.game._player_label(player_id)
        self.game._log_game_event(
            f"Turn {int(self.game.turn_number)} ({who}): Twilight Palace re-rolled die {die_index}: "
            f"{old_val} → {new_val}."
        )

    def reroll_both_dice(self, player_id):
        """Re-roll both dice during the roll_pending phase (Blood Moon Palace passive).

        Costs 2 Magic. Generates new random values for both dice, updates
        pending_roll, and marks the Blood Moon Palace token as consumed for
        this roll phase.
        """
        if self.game.phase != "roll_pending":
            raise ValueError("Not in roll_pending phase.")
        if player_id != self.current_player_id():
            raise ValueError("Only the active player may re-roll the dice.")
        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        if not self.game._player_has_action_effect_flag(player, "roll.reroll_both_dice_pay_magic_2"):
            raise ValueError("Player does not own Blood Moon Palace (or it is on build-turn cooldown).")
        if getattr(self.game, "_pending_reroll_blood_moon_used", False):
            raise ValueError("Blood Moon Palace re-roll already used this roll phase.")
        if int(getattr(player, "magic_score", 0) or 0) < 2:
            raise ValueError("Not enough Magic to use Blood Moon Palace (costs 2).")
        player.magic_score = int(player.magic_score) - 2
        rolled = self.game.pending_roll or {}
        old_one = int(rolled.get("rolled_die_one", 1) or 1)
        old_two = int(rolled.get("rolled_die_two", 1) or 1)
        new_one = random.randint(1, 6)
        new_two = random.randint(1, 6)
        rolled["rolled_die_one"] = new_one
        rolled["rolled_die_two"] = new_two
        rolled["rolled_die_sum"] = new_one + new_two
        self.game.rolled_die_one = new_one
        self.game.rolled_die_two = new_two
        self.game.rolled_die_sum = new_one + new_two
        self.game.pending_roll = rolled
        self.game._pending_reroll_blood_moon_used = True
        self.game.tick_id += 1
        who = self.game._player_label(player_id)
        self.game._log_game_event(
            f"Turn {int(self.game.turn_number)} ({who}): Blood Moon Palace re-rolled both dice: "
            f"({old_one},{old_two}) → ({new_one},{new_two}), sum {new_one + new_two} (cost 2 Magic)."
        )

    def _reveal_hidden_domain_stack_tops(self):
        """Face up domain stack tops that were left hidden after a purchase (until turn end)."""
        for domain_stack in getattr(self.game, "domain_grid", None) or []:
            if not domain_stack:
                continue
            top = domain_stack[-1]
            if getattr(top, "domain_id", None) is None:
                continue
            if getattr(top, "is_visible", True):
                continue
            top.toggle_visibility(True)
            top.toggle_accessibility(True)

    def action_phase(self):
        return

    def play_turn(self):
        self.roll_phase()
        self.game.harvest.harvest_phase()
        self.action_phase()

