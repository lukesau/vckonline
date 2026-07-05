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
                or aa == "exekratys_offering"
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
                or aa == "relic_wild_exchange"
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
            self._refresh_finishing_player_tomes()
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
            # Crimson Seas: drain any owed Exekratys 6-roll placements before
            # harvest automation kicks off. Opening a prompt blocks this tick.
            if (
                not getattr(self.game, "harvest_processed", False)
                and int(getattr(self.game, "pending_exekratys_offerings", 0) or 0) > 0
            ):
                if self.game.dice._maybe_open_exekratys_offering_prompt(
                    getattr(self.game, "pending_exekratys_offering_player", None)
                ):
                    return False
            # Manual harvest: players resolve matching starters/citizens in turn order (active player first).
            if not getattr(self.game, "harvest_processed", False):
                if getattr(self.game, "harvest_player_order", None) is None:
                    self.game.harvest._ensure_harvest_round_initialized()
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

            if not getattr(self.game, "harvest_processed", False):
                return False

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
                # Don't clobber a live per-player prompt that is still awaiting
                # input (e.g. a Dampiar's Workshop `may_sail` bonus, or a chained
                # activation choose/banish prompt opened by a granted domain).
                # Overwriting it with `standard_action` here breaks the bonus-sail
                # detection so the next sail is charged as a regular action and
                # silently eats the player's remaining action. Only (re)assert the
                # idle placeholder when nothing else is being asked.
                ar = self.game.action_required if isinstance(self.game.action_required, dict) else {}
                aid = ar.get("id")
                aact = str(ar.get("action", "") or "")
                if aid and aid != self.game.game_id and aact and aact != "standard_action":
                    return False
                # Ensure action_required stays on the active player during their action window.
                self.game.action_required["id"] = self.current_player_id()
                self.game.action_required["action"] = "standard_action"
                return False
            aid = self.game.action_required.get("id") if self.game.action_required else None
            aact = str(self.game.action_required.get("action", "") or "") if self.game.action_required else ""
            if aid and aid != self.game.game_id and aact and aact != "standard_action":
                return False
            # End-of-action domain prompts (e.g. King Tower) must run before the
            # turn ends. The standard action handlers reach them via
            # finish_turn_if_no_actions_remaining(), but an action that opened a
            # follow-up prompt (e.g. slaying Wendigo and then resolving its "gain
            # a citizen" reward) resumes through advance_tick instead. Start the
            # sequence here too; if it opens a prompt, block until it resolves.
            if self.game.domain_effects._start_action_end_domain_sequence(self.current_player_id()):
                return False
            finisher = self.game._player_label(self.current_player_id())
            if not self.game.end_game_triggered:
                reason = self.game.endgame._check_end_game_condition()
                if reason:
                    self.game.end_game_triggered = True
                    self.game._log_game_event(f"End-game condition met ({reason}); finishing this round.")
            self._reveal_hidden_domain_stack_tops()
            self._refresh_finishing_player_tomes()
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

        # Crimson Seas "you may Sail" bonus (Dampiar's Workshop). While the
        # may_sail prompt is open for this player, a single sail action runs for
        # free: it does not spend a regular action and is not blocked by the
        # may_sail prompt below. The bonus + prompt are cleared once the sail
        # succeeds (resolve_bonus_sail_if_consumed); a failed sail rolls back to
        # the still-open prompt so the player can retry.
        if (
            action_type in ("buy_goods", "buy_tomes", "rescue_noble", "sail_exekratys")
            and getattr(self.game, "pending_bonus_sail", None) == player_id
            and str((self.game.action_required or {}).get("action", "")) == "may_sail"
            and player_id == self.current_player_id()
        ):
            self.game._last_consumed_action_marker = ("bonus_sail", None)
            self.game.tick_id += 1
            return True

        # "You may recruit a Citizen" bonus (Town Crier agent). While the
        # may_recruit prompt is open for this player, a single hire_citizen runs
        # for free: no regular action spent, and not blocked by the may_recruit
        # prompt below. Cleared once the recruit succeeds
        # (resolve_bonus_recruit_if_consumed); a failed hire rolls back to the
        # still-open prompt so the player can retry or decline.
        if (
            action_type == "hire_citizen"
            and getattr(self.game, "pending_bonus_recruit", None) == player_id
            and str((self.game.action_required or {}).get("action", "")) == "may_recruit"
            and player_id == self.current_player_id()
        ):
            self.game._last_consumed_action_marker = ("bonus_recruit", None)
            self.game.tick_id += 1
            return True

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
                "may_sail",
                "may_recruit",
                "event_gain_action",
                "event_active_choose",
                "event_sequence",
                "relic_wild_exchange",
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

    def resolve_bonus_sail_if_consumed(self):
        """Finalize a Dampiar's Workshop free Sail after the sail action succeeded.

        Returns True when the just-completed sail consumed the may_sail bonus
        (so the caller skips the normal finish_turn handling): clears the bonus
        flag + the may_sail prompt and resumes the domain activation follow-up,
        which restores standard_action or ends the turn as appropriate.
        """
        if getattr(self.game, "_last_consumed_action_marker", None) != ("bonus_sail", None):
            return False
        self.game._last_consumed_action_marker = None
        self.game.pending_bonus_sail = None
        ar = self.game.action_required if isinstance(self.game.action_required, dict) else None
        if ar and str(ar.get("action", "")) == "may_sail":
            ar["action"] = ""
            ar["id"] = self.game.game_id
        self.game.pending_required_choice = None
        self.game.domain_effects._resume_after_domain_activation_follow_up()
        # The action that granted the bonus may have been the player's last one.
        # _resume_* clears the prompt (and fires end-of-action domains) but does
        # not advance the seat when actions are exhausted; advance_tick finishes
        # the turn. It self-guards (no-op while actions remain or a prompt is
        # still open) and does not re-fire the end-of-action queue.
        self.advance_tick()
        return True

    def resolve_bonus_recruit_if_consumed(self):
        """Finalize a Town Crier free recruit after the hire action succeeded.

        Returns True when the just-completed hire consumed the may_recruit bonus
        (so the caller skips the normal finish_turn handling): clears the bonus
        flag + the may_recruit prompt and resumes the activation follow-up, which
        restores standard_action or ends the turn as appropriate.
        """
        if getattr(self.game, "_last_consumed_action_marker", None) != ("bonus_recruit", None):
            return False
        self.game._last_consumed_action_marker = None
        self.game.pending_bonus_recruit = None
        ar = self.game.action_required if isinstance(self.game.action_required, dict) else None
        if ar and str(ar.get("action", "")) == "may_recruit":
            ar["action"] = ""
            ar["id"] = self.game.game_id
        self.game.pending_required_choice = None
        self.game.domain_effects._resume_after_domain_activation_follow_up()
        # The action that granted the bonus may have been the player's last one.
        # _resume_* clears the prompt (and fires end-of-action domains) but does
        # not advance the seat when actions are exhausted; advance_tick finishes
        # the turn. It self-guards (no-op while actions remain or a prompt is
        # still open) and does not re-fire the end-of-action queue.
        self.advance_tick()
        return True

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
        self.game.harvest._clear_stale_harvest_concurrent_gate()

        # Clear only the leftover finalize prompt; preserve choices opened by
        # roll effects (event slay cost, Flaming Devourer, etc.).
        if (self.game.action_required.get("action") or "") == "finalize_roll":
            self.game.action_required["id"] = self.game.game_id
            self.game.action_required["action"] = ""
        # Fire Northern Wall optional Minion-banish (only if nothing else is pending).
        if not (self.game.action_required.get("action") or ""):
            self.game.payouts._maybe_fire_northern_wall_banish(player_id)
        # Crimson Seas: each 6 rolled (each die plus the dice sum, counted
        # separately) obliges the active player to place 1 resource into the
        # Exekratys pool. Record the obligation; the prompt is opened lazily in
        # advance_tick so it sequences after any other roll-phase prompt.
        if self.game.crimson_seas_enabled():
            sixes = sum(1 for v in (fd1, fd2, fd1 + fd2) if v == 6)
            if sixes:
                roller = self.game._player_by_id(player_id)
                # Avery Hollow (Domain #67): "During your Roll Phase, you don't
                # lose Wild on a 6." The owner is exempt from the offering when
                # they are the one who rolled the 6(s).
                if roller and self.game._player_has_action_effect_flag(roller, "roll.exekratys_immune"):
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} rolled a 6 but is protected from the "
                        f"Exekratys offering (Avery Hollow)."
                    )
                else:
                    self.game.pending_exekratys_offerings = sixes
                    self.game.pending_exekratys_offering_player = player_id
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
        """Defensive end-of-turn sweep: face up any domain stack top still hidden.

        Building a Domain now reveals the next card immediately (base-rules step
        5), so this should be a no-op in normal play. Kept as a safety net for
        any path that leaves a domain top face-down."""
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

    def _refresh_finishing_player_tomes(self):
        """End-of-turn Tome refresh (Crimson Seas): flip all of the finishing
        player's face-down (spent-this-turn) tomes back face-up. Called for the
        player whose turn is ending, before the seat advances."""
        player = self.game._player_by_id(self.current_player_id())
        if not player:
            return
        for tome in getattr(player, "owned_tomes", None) or []:
            if getattr(tome, "is_flipped", False):
                tome.is_flipped = False

    def action_phase(self):
        return

    def play_turn(self):
        self.roll_phase()
        self.game.harvest.harvest_phase()
        self.action_phase()

