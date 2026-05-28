import time
import random
from constants import *
from cards import *
import threading
from game_models import Player, Lobby, LobbyMember, GameMember
from game_setup import DEBUG_DIE_ONE_VALUES, DEBUG_DIE_TWO_VALUES, load_game_data
from game_serialization import SummaryEncoder, GameObjectEncoder


def _n(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _validate_hire_or_domain_gold_payment(player, scaled_gold_cost, gp, sp, mp, allow_strength=False):
    gp, sp, mp = _n(gp), _n(sp), _n(mp)
    if gp < 0 or sp < 0 or mp < 0:
        raise ValueError("Invalid payment (negative amounts).")
    if sp != 0 and not allow_strength:
        raise ValueError("Strength cannot be spent on hiring citizens or building domains.")
    scaled_gold_cost = int(scaled_gold_cost or 0)
    if allow_strength:
        total = gp + sp + mp
        if total < scaled_gold_cost:
            raise ValueError("Payment does not cover the gold cost.")
        if total != scaled_gold_cost:
            raise ValueError("Payment must exactly match the gold cost.")
        if int(getattr(player, "gold_score", 0)) < gp or int(getattr(player, "magic_score", 0)) < mp \
                or int(getattr(player, "strength_score", 0)) < sp:
            raise ValueError("Insufficient resources.")
    else:
        if scaled_gold_cost > 0 and mp > 0 and gp < 1:
            raise ValueError("Must pay at least 1 gold to use magic as wild.")
        total = gp + mp
        if total < scaled_gold_cost:
            raise ValueError("Payment does not cover the gold cost.")
        if total != scaled_gold_cost:
            raise ValueError("Payment must exactly match the gold cost.")
        if int(getattr(player, "gold_score", 0)) < gp or int(getattr(player, "magic_score", 0)) < mp:
            raise ValueError("Insufficient resources.")


def _citizen_has_steal(citizen, on_turn):
    """Return True if this citizen's relevant payout (on- or off-turn) is a steal effect."""
    if not citizen:
        return False
    field = "special_payout_on_turn" if on_turn else "special_payout_off_turn"
    val = (getattr(citizen, field, None) or "").strip().lower()
    return val.startswith("steal")


def _parse_domain_effect_kv(effect):
    out = {}
    for p in (effect or "").split():
        if "=" in p:
            k, v = p.split("=", 1)
            out[(k or "").strip().lower()] = (v or "").strip()
    return out


def _parse_resource_kv(spec):
    """
    'g:3' / 'vp:1' / 'm:1' -> (letter, amount) with vp mapped to 'v'.
    """
    if not spec or ":" not in spec:
        return None, 0
    kind, rest = spec.split(":", 1)
    kind = (kind or "").strip().lower()
    try:
        n = int((rest or "").strip())
    except (TypeError, ValueError):
        return None, 0
    if kind == "vp":
        kind = "v"
    if kind not in ("g", "s", "m", "v"):
        return None, 0
    return kind, n


def _validate_monster_slay_payment(player, strength_cost, magic_min, gold_cost, gp, sp, mp):
    gp, sp, mp = _n(gp), _n(sp), _n(mp)
    gold_cost = int(gold_cost or 0)
    if gold_cost > 0:
        if gp != gold_cost:
            raise ValueError(f"Must pay exactly {gold_cost} gold (no substitution allowed).")
        if int(getattr(player, "gold_score", 0)) < gp:
            raise ValueError("Insufficient gold.")
    elif gp != 0:
        raise ValueError("Gold cannot be spent on slaying monsters.")
    strength_cost = int(strength_cost or 0)
    magic_min = int(magic_min or 0)
    if sp < 0 or mp < 0 or mp < magic_min:
        raise ValueError("Invalid monster payment.")
    wild_magic = mp - magic_min
    if sp + wild_magic < strength_cost:
        raise ValueError("Payment does not cover strength cost.")
    if strength_cost > 0 and wild_magic > 0 and sp < 1:
        raise ValueError("Must pay at least 1 strength to use magic as wild for slaying.")
    if int(getattr(player, "strength_score", 0)) < sp or int(getattr(player, "magic_score", 0)) < mp:
        raise ValueError("Insufficient resources.")


def _player_resource_balances(player):
    if not player:
        return None
    return {
        "g": int(getattr(player, "gold_score", 0)),
        "s": int(getattr(player, "strength_score", 0)),
        "m": int(getattr(player, "magic_score", 0)),
        "v": int(getattr(player, "victory_score", 0)),
    }


def _balances_allow_payout(balances, payout_vec):
    """balances: dict g,s,m,v; payout_vec: [dg, ds, dm, dv]."""
    if not balances:
        return False
    keys = ("g", "s", "m", "v")
    for i, k in enumerate(keys):
        if int(balances.get(k, 0)) + int(payout_vec[i]) < 0:
            return False
    return True


# ---------------------------------------------------------------------------
# Concurrent (non-ordered) action subsystem.
#
# A "concurrent action" is a gate where many players must each submit a
# response before the game can advance, but their submissions are unordered
# (any participant may respond at any time). This is intentionally separate
# from the per-player `action_required` field, which is used for sequential,
# turn-based prompts (e.g. action phase, manual harvest).
#
# To add a new kind, register a handler in CONCURRENT_HANDLERS. The handler
# implements:
#
#   apply(game, player_id, response)
#       Validate + apply this player's response. Raise ValueError on bad
#       input. The response payload is opaque to the engine (handler-defined).
#
#   finalize(game)
#       Optional. Runs once after every participant has submitted. Use this
#       for any cross-player resolution that has to happen after all
#       responses are in. Side-effects on individual players that don't
#       depend on others should generally happen in apply().
#
# The engine itself only knows: "while there's a concurrent_action with
# pending players, do not advance".
# ---------------------------------------------------------------------------


class _ChooseDukeConcurrentHandler:
    """Each player keeps exactly one of their dealt dukes."""

    def apply(self, game, player_id, response):
        try:
            chosen_id = int(str(response).strip())
        except Exception:
            raise ValueError("Invalid duke selection.")
        for p in game.player_list:
            if p.player_id != player_id:
                continue
            dukes = list(getattr(p, "owned_dukes", []) or [])
            if not dukes:
                raise ValueError("No dukes to choose from.")
            chosen = None
            for d in dukes:
                if int(getattr(d, "duke_id", -1)) == chosen_id:
                    chosen = d
                    break
            if chosen is None:
                raise ValueError("Selected duke not found.")
            p.owned_dukes = [chosen]
            return
        raise ValueError("Player not found.")

    def finalize(self, game):
        return


class _FlipOneCitizenConcurrentHandler:
    """Each pending player chooses one unflipped citizen on their tableau to flip face-down (e.g. Cursed Cavern)."""

    def apply(self, game, player_id, response):
        try:
            idx = int(str(response).strip())
        except (TypeError, ValueError):
            raise ValueError("Invalid citizen choice (send tableau index).")
        player = game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        oc = list(getattr(player, "owned_citizens", []) or [])
        if idx < 0 or idx >= len(oc):
            raise ValueError("Invalid citizen index.")
        cit = oc[idx]
        if getattr(cit, "is_flipped", False):
            raise ValueError("That citizen is already flipped.")
        game._citizen_set_flipped(cit, True)
        game._log_game_event(
            f"{game._player_label(player_id)} flipped citizen \"{getattr(cit, 'name', '?')}\" face-down "
            f"(Cursed Cavern)."
        )

    def finalize(self, game):
        return


CONCURRENT_HANDLERS = {
    "choose_duke": _ChooseDukeConcurrentHandler(),
    "flip_one_citizen": _FlipOneCitizenConcurrentHandler(),
}

# Append-only server log included in serialized game state (same for every client).
_GAME_LOG_MAX = 400


def _new_concurrent_action(kind, participant_ids, data=None):
    """Build a concurrent_action dict for the given kind + participants."""
    if kind not in CONCURRENT_HANDLERS:
        raise ValueError(f"Unknown concurrent action kind: {kind}")
    pids = [pid for pid in participant_ids if pid]
    return {
        "kind": kind,
        "pending": list(pids),
        "completed": [],
        "responses": {},
        "data": dict(data or {}),
    }


class Game:
    def __init__(self, game_state):
        self.game_id = game_state['game_id']
        # When True the game was started from the lobby with the "Debug mode"
        # toggle on. Currently this flag (a) makes `roll_phase` pick dice out
        # of `DEBUG_DIE_ONE_VALUES` / `DEBUG_DIE_TWO_VALUES` instead of
        # `random.randint(1, 6)`, and (b) is set up-front by `load_game_data`
        # (extra starting resources, citizens, and roll-modifier domains).
        # See `docs/game.md` "Debug mode" section.
        self.debug_mode = bool(game_state.get('debug_mode', False))
        self.player_list = game_state['player_list']
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
        self.game_log = list(game_state.get('game_log') or [])
        self.pending_action_end_queue = list(game_state.get("pending_action_end_queue") or [])
        self.pending_required_choice = game_state.get("pending_required_choice")
        self._silent_harvest_batch = False
        # Between roll and harvest we allow a small "finalization window" where effects (or dev rigging)
        # may legally change the dice. When present, the engine blocks in roll_pending until finalized.
        self.pending_roll = game_state.get('pending_roll') or None
        self.pending_event_slay_cost = game_state.get('pending_event_slay_cost') or None

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

        if not self.game_log:
            self._log_game_event("Game started.")
        if self.concurrent_action and self.concurrent_action.get("kind") == "choose_duke":
            self._log_game_event("Waiting for each player to choose a duke to keep.")

    def current_player_id(self):
        if not self.player_list:
            return None
        if self.turn_index < 0 or self.turn_index >= len(self.player_list):
            self.turn_index = 0
        return self.player_list[self.turn_index].player_id

    def start_new_turn_if_needed(self):
        if self.phase != 'roll':
            return
        if self.actions_remaining != 0:
            self.actions_remaining = 0

    def is_blocked_on_concurrent_action(self):
        """True iff a concurrent (non-ordered) prompt still has pending participants."""
        ca = getattr(self, "concurrent_action", None) or None
        if not ca:
            return False
        return bool(ca.get("pending"))

    def advance_tick(self):
        """
        Advance the game by one deterministic tick.
        This is intentionally small-grained so the server can call it implicitly.
        """
        if self.phase == 'game_over':
            return False

        # Block on any active concurrent (non-ordered) prompt first.
        if self.is_blocked_on_concurrent_action():
            return False

        # Block only on required player choices (not on standard action prompts)
        if self.action_required and self.action_required.get("id") and self.action_required.get("id") != self.game_id:
            aa = str(self.action_required.get("action", "") or "")
            if (
                self.action_required.get("action") == "bonus_resource_choice"
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
                or aa == "event_slay_cost_choice"
                or aa == "choose_domain_to_build"
            ):
                return False

        if self.phase == "setup":
            # Setup only progresses when required choices are resolved.
            # Once no longer blocked, begin the normal turn loop.
            blocked_ar = bool(
                self.action_required
                and self.action_required.get("id")
                and self.action_required.get("id") != self.game_id
            )
            if not blocked_ar:
                self.phase = "roll"
                self.tick_id += 1
                self._log_game_event("Setup complete; turns begin.")
                return True
            return False

        if self.phase == 'roll':
            self.roll_phase()
            self.tick_id += 1
            who = self._player_label(self.current_player_id())
            rd1 = int(getattr(self, "rolled_die_one", 0) or 0)
            rd2 = int(getattr(self, "rolled_die_two", 0) or 0)
            rds = int(getattr(self, "rolled_die_sum", rd1 + rd2) or (rd1 + rd2))
            self._log_game_event(
                f"Turn {int(self.turn_number)} ({who}): rolled {rd1}+{rd2}={rds}."
            )
            return True

        if self.phase == 'roll_pending':
            # Waiting for the roll to be finalized (possibly changed by an effect / dev rig).
            return False

        if self.phase == 'action_end_pending':
            # End-of-action domain prompts (pay/take vs another player). Same blocking rules as
            # finishing the action phase with actions_remaining == 0.
            aid = self.action_required.get("id") if self.action_required else None
            aact = str(self.action_required.get("action", "") or "") if self.action_required else ""
            if aid and aid != self.game_id and aact and aact != "standard_action":
                return False
            if self.pending_action_end_queue:
                return False
            finisher = self._player_label(self.current_player_id())
            if not self.end_game_triggered:
                reason = self._check_end_game_condition()
                if reason:
                    self.end_game_triggered = True
                    self._log_game_event(f"End-game condition met ({reason}); finishing this round.")
            self._reveal_hidden_domain_stack_tops()
            self.turn_index = (self.turn_index + 1) % max(1, len(self.player_list))
            self.turn_number = int(self.turn_number) + 1
            if self.end_game_triggered and self.player_list[self.turn_index].is_first:
                self._log_game_event(f"{finisher} ended their turn.")
                self._finalize_game()
                return True
            self.phase = 'roll'
            self.actions_remaining = 0
            self.action_required["id"] = self.game_id
            self.action_required["action"] = ""
            self.tick_id += 1
            self._log_game_event(f"{finisher} ended their turn.")
            progressed = False
            while self.phase in ('roll', 'harvest'):
                if not self.advance_tick():
                    break
                progressed = True
            return True or progressed

        if self.phase == 'harvest':
            # Manual harvest: players resolve matching starters/citizens in turn order (active player first).
            if not getattr(self, "harvest_processed", False):
                if getattr(self, "harvest_player_order", None) is None:
                    for p in self.player_list:
                        p.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
                    self.harvest_consumed = {}
                    self.harvest_player_idx = 0
                    self.harvest_player_order = self._harvest_player_id_order_starting_active()
                    self._harvest_steal_phase_done = False
                    resting_pid = self.resting_player_id()
                    if resting_pid is not None:
                        self._log_game_event(
                            f"{self._player_label(resting_pid)} is resting (5-player rule); no harvest this turn."
                        )
                    # Harvest-phase domain passives (e.g. Jousting Field) must run after deltas are
                    # cleared for the new harvest round, not during finalize_roll (which ran before
                    # this reset and would lose passive contributions from harvest_delta tracking).
                    active = self._player_by_id(self.current_player_id())
                    self._apply_harvest_jousting_passive(active)
                self._harvest_run_automation_until_blocked()

            # If harvest triggered a required choice, pause progression here.
            if self.action_required and self.action_required.get("id") and self.action_required.get("id") != self.game_id:
                self.phase = 'harvest'
                self.tick_id += 1
                if self.action_required.get("action") == "manual_harvest":
                    return False
                return True

            self.phase = 'action'
            # baseline actions per turn; may become effect-driven later
            self.actions_remaining = max(0, int(self.actions_remaining) or 2)
            # During action phase, mark that we're waiting on the active player to act.
            self.action_required["id"] = self.current_player_id()
            self.action_required["action"] = "standard_action"
            self.tick_id += 1
            ap = self._player_label(self.current_player_id())
            self._log_game_event(
                f"Harvest finished; {ap}'s action phase ({int(self.actions_remaining)} action(s))."
            )
            active = self._player_by_id(self.current_player_id())
            self._apply_action_start_domain_passives(active)
            return True

        if self.phase == 'action':
            # Action ticks are driven by explicit player actions; if we're out of actions, advance seat.
            if int(self.actions_remaining) > 0:
                # Ensure action_required stays on the active player during their action window.
                self.action_required["id"] = self.current_player_id()
                self.action_required["action"] = "standard_action"
                return False
            aid = self.action_required.get("id") if self.action_required else None
            aact = str(self.action_required.get("action", "") or "") if self.action_required else ""
            if aid and aid != self.game_id and aact and aact != "standard_action":
                return False
            finisher = self._player_label(self.current_player_id())
            if not self.end_game_triggered:
                reason = self._check_end_game_condition()
                if reason:
                    self.end_game_triggered = True
                    self._log_game_event(f"End-game condition met ({reason}); finishing this round.")
            self._reveal_hidden_domain_stack_tops()
            self.turn_index = (self.turn_index + 1) % max(1, len(self.player_list))
            self.turn_number = int(self.turn_number) + 1
            if self.end_game_triggered and self.player_list[self.turn_index].is_first:
                self._log_game_event(f"{finisher} ended their turn.")
                self._finalize_game()
                return True
            self.phase = 'roll'
            self.actions_remaining = 0
            # Leaving action phase: clear the standard action prompt.
            self.action_required["id"] = self.game_id
            self.action_required["action"] = ""
            self.tick_id += 1
            self._log_game_event(f"{finisher} ended their turn.")

            # Auto-run the beginning-of-turn roll/harvest so the game lands in action phase.
            progressed = False
            while self.phase in ('roll', 'harvest'):
                if not self.advance_tick():
                    break
                progressed = True
            return True or progressed

        # Unknown phase; reset safely
        self.phase = 'roll'
        self.tick_id += 1
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
        ar = getattr(self, "action_required", None)
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
        if self.phase == "action_end_pending":
            return False

        if self.is_blocked_on_concurrent_action():
            return False

        if self.phase != 'action':
            # If an action comes in early, fast-forward to action phase.
            while self.advance_tick():
                if self.phase == 'action':
                    break

        # Block while waiting on any active per-player prompt that isn't the
        # idle "standard_action" placeholder. This includes the new immediate
        # slay prompts (choose_monster_slay / slay_monster_payment), as well as
        # the existing choose_* / harvest_* / domain_self_convert prompts.
        if self.action_required and self.action_required.get("id") and self.action_required.get("id") != self.game_id:
            aa = str(self.action_required.get("action", "") or "")
            blocking = aa in (
                "bonus_resource_choice",
                "manual_harvest",
                "harvest_optional_exchange",
                "harvest_steal",
                "harvest_wild_gain_exchange",
                "harvest_wild_cost_exchange",
                "choose_domain_reward",
                "domain_self_convert",
                "choose_monster_slay",
                "slay_monster_payment",
                "choose_domain_to_build",
            ) or aa.startswith("choose ") or aa.startswith("choose_player") or aa.startswith(
                "choose_monster"
            ) or aa.startswith("choose_owned")
            if blocking:
                return False

        if player_id != self.current_player_id():
            return False

        if self.actions_remaining is None:
            self.actions_remaining = 2
        regulars = int(self.actions_remaining)
        if regulars <= 0:
            return False

        self.actions_remaining = regulars - 1
        self._last_consumed_action_marker = ("regular", None)

        self.tick_id += 1
        self._refresh_action_phase_required(player_id)
        return True

    def rollback_last_consumed_action(self):
        """Undo the most recent consume_player_action when the underlying action failed."""
        marker = getattr(self, "_last_consumed_action_marker", None)
        if not marker:
            self.actions_remaining = int(getattr(self, "actions_remaining", 0)) + 1
            self.tick_id = int(getattr(self, "tick_id", 0)) - 1
            return
        kind_a, _kind_b = marker
        if kind_a == "regular":
            self.actions_remaining = int(getattr(self, "actions_remaining", 0)) + 1
        self.tick_id = int(getattr(self, "tick_id", 0)) - 1
        self._last_consumed_action_marker = None
        self._refresh_action_phase_required(self.current_player_id())

    def finish_turn_if_no_actions_remaining(self):
        """After a successful standard action, advance roll/harvest if the turn was just spent."""
        if getattr(self, "phase", None) != "action" or int(getattr(self, "actions_remaining", 0) or 0) != 0:
            return
        if self.is_blocked_on_concurrent_action():
            return
        ar = getattr(self, "action_required", None) or {}
        aid = ar.get("id")
        aact = str(ar.get("action", "") or "").strip()
        if aid and aid != self.game_id and aact not in ("", "standard_action"):
            return
        if self._start_action_end_domain_sequence(self.current_player_id()):
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
        if self.debug_mode:
            d1 = random.choice(DEBUG_DIE_ONE_VALUES)
            d2 = random.choice(DEBUG_DIE_TWO_VALUES)
        else:
            d1 = random.randint(1, 6)
            d2 = random.randint(1, 6)
        ds = d1 + d2
        self.rolled_die_one = d1
        self.rolled_die_two = d2
        self.rolled_die_sum = ds

        # Start a "pending roll" window. For now we always open the window; later effects
        # can choose to auto-finalize or pause based on game state.
        self.pending_roll = {"rolled_die_one": d1, "rolled_die_two": d2, "rolled_die_sum": ds}
        self.phase = "roll_pending"
        self.action_required["id"] = self.current_player_id()
        self.action_required["action"] = "finalize_roll"
        # Reset per-turn Twilight Palace re-roll token.
        self._pending_reroll_twilight_used = False

        # Default final dice are unset until finalized.
        # (We intentionally do not touch self.die_one/die_two here.)

    def finalize_roll(self, player_id, die_one=None, die_two=None):
        if self.phase != "roll_pending":
            raise ValueError("Not waiting to finalize a roll")
        if player_id != self.current_player_id():
            raise ValueError("Only the active player may finalize the roll")

        rolled = self.pending_roll or {}
        rd1 = int(rolled.get("rolled_die_one") or 0)
        rd2 = int(rolled.get("rolled_die_two") or 0)
        if rd1 < 1 or rd1 > 6 or rd2 < 1 or rd2 > 6:
            raise ValueError("Pending roll is invalid")

        fd1 = rd1 if die_one is None else int(die_one)
        fd2 = rd2 if die_two is None else int(die_two)
        if fd1 < 1 or fd1 > 6 or fd2 < 1 or fd2 > 6:
            raise ValueError("Final dice must be between 1 and 6")
        player = self._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found")
        changed = (fd1 != rd1) or (fd2 != rd2)
        if changed:
            if not self._apply_roll_modification(player, rd1, rd2, fd1, fd2):
                raise ValueError("Illegal roll modification")

        self.die_one = fd1
        self.die_two = fd2
        self.die_sum = fd1 + fd2

        # Compute roll-event tokens from the FINAL dice (post-modification).
        # A player who spends modifiers to land on doubles legitimately
        # triggered doubles for this roll; the engine treats final-dice
        # doubles the same as a naturally-rolled pair. Same reasoning as why
        # the starter `activation_trigger doubles` leg reads
        # `self.die_one == self.die_two` -- both views agree on what "the
        # roll" was.
        self.roll_events = self._compute_roll_events(fd1, fd2)
        self._apply_roll_on_event_passives()
        self._apply_board_event_roll_effects(fd1, fd2)

        self.pending_roll = None
        # Move into harvest exactly like the old post-roll transition.
        self.phase = "harvest"
        self.harvest_processed = False
        self.harvest_player_order = None
        self.harvest_player_idx = 0
        self.harvest_consumed = {}
        self._harvest_steal_phase_done = False

        # Clear the finalize prompt; harvest/action will set prompts as needed.
        # But preserve action_required when an event roll effect needs a player choice.
        if (self.action_required.get("action") or "") != "event_slay_cost_choice":
            self.action_required["id"] = self.game_id
            self.action_required["action"] = ""
        # Fire Northern Wall optional Minion-banish (only if nothing else is pending).
        if not (self.action_required.get("action") or ""):
            self._maybe_fire_northern_wall_banish(player_id)
        self.tick_id += 1
        who = self._player_label(self.current_player_id())
        if fd1 == rd1 and fd2 == rd2:
            self._log_game_event(
                f"Turn {int(self.turn_number)} ({who}): roll finalized at {fd1}+{fd2}={self.die_sum}."
            )
        else:
            self._log_game_event(
                f"Turn {int(self.turn_number)} ({who}): roll changed {rd1}+{rd2}={rd1+rd2} -> {fd1}+{fd2}={self.die_sum}."
            )

    def reroll_pending_die(self, player_id, die_index):
        """Re-roll one die during the roll_pending phase (Twilight Palace passive).

        die_index: 1 or 2. Generates a new random value, updates pending_roll,
        and marks the Twilight Palace token as consumed for this roll phase.
        """
        if self.phase != "roll_pending":
            raise ValueError("Not in roll_pending phase.")
        if player_id != self.current_player_id():
            raise ValueError("Only the active player may re-roll a die.")
        player = self._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        if not self._player_has_action_effect_flag(player, "roll.reroll_one_die"):
            raise ValueError("Player does not own Twilight Palace (or it is on build-turn cooldown).")
        if getattr(self, "_pending_reroll_twilight_used", False):
            raise ValueError("Twilight Palace re-roll already used this roll phase.")
        die_index = int(die_index)
        if die_index not in (1, 2):
            raise ValueError("die_index must be 1 or 2.")
        rolled = self.pending_roll or {}
        new_val = random.randint(1, 6)
        if die_index == 1:
            old_val = int(rolled.get("rolled_die_one", 1) or 1)
            rolled["rolled_die_one"] = new_val
            self.rolled_die_one = new_val
        else:
            old_val = int(rolled.get("rolled_die_two", 1) or 1)
            rolled["rolled_die_two"] = new_val
            self.rolled_die_two = new_val
        rolled["rolled_die_sum"] = int(rolled.get("rolled_die_one", 1)) + int(rolled.get("rolled_die_two", 1))
        self.rolled_die_sum = rolled["rolled_die_sum"]
        self.pending_roll = rolled
        self._pending_reroll_twilight_used = True
        self.tick_id += 1
        who = self._player_label(player_id)
        self._log_game_event(
            f"Turn {int(self.turn_number)} ({who}): Twilight Palace re-rolled die {die_index}: "
            f"{old_val} → {new_val}."
        )

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

    def _begin_concurrent_flip_one_citizen(self, buyer_player_id):
        """Start unordered concurrent prompt: each player with ≥1 unflipped citizen picks one to flip."""
        if getattr(self, "concurrent_action", None):
            raise ValueError("Another concurrent prompt is already active.")
        targets = []
        for p in list(getattr(self, "player_list", []) or []):
            if not self._player_is_negative_effect_target(p):
                continue
            oc = list(getattr(p, "owned_citizens", []) or [])
            if any(not getattr(c, "is_flipped", False) for c in oc):
                targets.append(p.player_id)
        if not targets:
            self._log_game_event(
                f"{self._player_label(buyer_player_id)} played Cursed Cavern — no player had a citizen to flip."
            )
            return
        self.concurrent_action = _new_concurrent_action(
            "flip_one_citizen",
            targets,
            data={"buyer_id": buyer_player_id, "source": "cursed_cavern"},
        )
        self._log_game_event(
            f"{self._player_label(buyer_player_id)} played Cursed Cavern (+4 magic); "
            f"each player with citizens must choose one to flip face-down."
        )

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

    def _domain_recurring_passive_on_build_turn_cooldown(self, domain):
        """Recurring domain passives cannot be used on the turn the domain was purchased."""
        acq = getattr(domain, "acquired_turn_number", None)
        if acq is None:
            return False
        try:
            return int(acq) == int(getattr(self, "turn_number", 0) or 0)
        except (TypeError, ValueError):
            return False

    def _iter_roll_set_one_die_effects(self, player):
        """Yield owned-domain `roll.set_one_die` passive specs for the player.

        Recognized KV options:
          target=N       absolute set to N (1..6)
          subtract=N     relative: new value = old - N
          add=N          relative: new value = old + N
          cost=g:N | cost=g_per_owned_role:<role>    optional; omitted = free
        """
        for d in list(getattr(player, "owned_domains", []) or []):
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            raw = (getattr(d, "passive_effect", None) or "")
            effect = str(raw).strip()
            if not effect:
                continue
            parts = effect.split()
            head = parts[0].strip().lower()
            if head != "roll.set_one_die":
                continue
            kv = {}
            for p in parts[1:]:
                if "=" not in p:
                    continue
                k, v = p.split("=", 1)
                kv[(k or "").strip().lower()] = (v or "").strip()
            spec = self._parse_roll_set_one_die_kv(kv)
            if not spec:
                continue
            spec["domain_name"] = getattr(d, "name", "Domain")
            # domain_id identifies the source card; used by
            # _apply_roll_modification to forbid the same card firing twice in
            # one roll phase (each card text says "during your Roll Phase, you
            # may ... change one die", i.e. one activation per phase per card).
            spec["domain_id"] = getattr(d, "domain_id", None)
            yield spec

    def _parse_roll_set_one_die_kv(self, kv):
        cost_spec = kv.get("cost", "")
        target_s = kv.get("target", "")
        if target_s:
            try:
                target = int(target_s)
            except (TypeError, ValueError):
                return None
            if target < 1 or target > 6:
                return None
            return {"mode": "target", "target": target, "cost_spec": cost_spec}
        for mode_key in ("subtract", "add"):
            v = kv.get(mode_key, "")
            if not v:
                continue
            try:
                delta = int(v)
            except (TypeError, ValueError):
                return None
            if delta <= 0:
                return None
            return {"mode": mode_key, "delta": delta, "cost_spec": cost_spec}
        return None

    def _resolve_roll_effect_cost(self, player, cost_spec):
        spec = (cost_spec or "").strip().lower()
        # Empty cost = free
        if not spec:
            return {"gold": 0}
        # g:N
        if spec.startswith("g:"):
            try:
                n = int(spec.split(":", 1)[1])
            except (TypeError, ValueError):
                return None
            if n < 0:
                return None
            return {"gold": n}
        # g_per_owned_role:holy_citizen
        if spec.startswith("g_per_owned_role:"):
            role = spec.split(":", 1)[1].strip()
            n = self._owned_citizen_count_for_role_selector(player, role)
            return {"gold": n}
        if spec in ("g:per_owned_holy_citizen", "per_owned_holy_citizen"):
            n = self._owned_citizen_count_for_role_selector(player, "holy_citizen")
            return {"gold": n}
        return None

    def _apply_roll_modification(self, player, rd1, rd2, fd1, fd2):
        """Validate `(rd1, rd2) -> (fd1, fd2)` against this player's owned
        roll-modifier domains and, if legal, charge gold and write a log line
        for each applied modifier.

        Up to one modifier per CHANGED die is allowed:
          - 0 changes  -> trivially legal (no effects applied)
          - 1 change   -> exactly one matching, affordable effect applied
          - 2 changes  -> two matching effects applied, sourced by DIFFERENT
                          owned domains (each card's "during your Roll Phase,
                          you may ... change one die" text caps at one
                          activation per phase per card). Total gold cost
                          (sum of both costs) must be affordable.

        Costs are resolved up-front from the player's pre-modification state.
        That's fine because no `roll.set_one_die` cost spec we currently
        support depends on anything that mutates between picks (only static
        gold or per-owned-role counts, neither of which change mid-roll).
        """
        changed1 = (fd1 != rd1)
        changed2 = (fd2 != rd2)
        if not changed1 and not changed2:
            return True

        effects = list(self._iter_roll_set_one_die_effects(player))

        def candidates(old, new):
            """Return [(effect, gold_cost)] entries that legally produce old->new."""
            out = []
            for eff in effects:
                mode = eff.get("mode")
                if mode == "target":
                    if int(eff.get("target", 0) or 0) != int(new):
                        continue
                elif mode == "subtract":
                    if int(new) != int(old) - int(eff.get("delta", 0) or 0):
                        continue
                elif mode == "add":
                    if int(new) != int(old) + int(eff.get("delta", 0) or 0):
                        continue
                else:
                    continue
                if int(new) < 1 or int(new) > 6:
                    continue
                cost = self._resolve_roll_effect_cost(player, eff.get("cost_spec"))
                if cost is None:
                    continue
                out.append((eff, int(cost.get("gold", 0) or 0)))
            return out

        available_gold = int(getattr(player, "gold_score", 0) or 0)

        if changed1 ^ changed2:
            old, new = (rd1, fd1) if changed1 else (rd2, fd2)
            for eff, g in candidates(old, new):
                if available_gold < g:
                    continue
                self._charge_and_log_roll_modifier(player, eff, g, old, new)
                return True
            return False

        # Both dice changed: need two effects sourced by distinct domains.
        cands1 = candidates(rd1, fd1)
        cands2 = candidates(rd2, fd2)
        for eff1, g1 in cands1:
            for eff2, g2 in cands2:
                if self._roll_modifier_same_source(eff1, eff2):
                    continue
                if available_gold < g1 + g2:
                    continue
                self._charge_and_log_roll_modifier(player, eff1, g1, rd1, fd1)
                self._charge_and_log_roll_modifier(player, eff2, g2, rd2, fd2)
                return True
        return False

    def _roll_modifier_same_source(self, eff_a, eff_b):
        """Two yielded effect specs come from the same owned-domain card iff
        their `domain_id`s match (or, as a fallback for synthetic specs that
        don't carry one, their `domain_name`s do)."""
        ida = eff_a.get("domain_id")
        idb = eff_b.get("domain_id")
        if ida is not None and idb is not None:
            return ida == idb
        return (eff_a.get("domain_name") or "") == (eff_b.get("domain_name") or "")

    def _charge_and_log_roll_modifier(self, player, effect, gold_cost, old_value, new_value):
        before = self._player_scores_line(player)
        if gold_cost:
            player.gold_score = int(player.gold_score) - gold_cost
        after = self._player_scores_line(player)
        if gold_cost:
            self._log_game_event(
                f"{self._player_label(player.player_id)} used {effect.get('domain_name')} "
                f"(pay {gold_cost} gold) during roll: die {old_value} -> {new_value}; scores {before} -> {after}"
            )
        else:
            self._log_game_event(
                f"{self._player_label(player.player_id)} used {effect.get('domain_name')} "
                f"during roll: die {old_value} -> {new_value}"
            )

    def _compute_roll_events(self, die_one, die_two):
        """Return the list of event tokens for the given FINAL dice.

        Centralizes "what happened on the dice this roll" so that any listener
        (roll-phase passives now, harvest/action effects later) can ask the
        same question without re-deriving things like "were the dice
        doubles?". Called from `finalize_roll` against the post-modification
        dice so the answer agrees with `self.die_one == self.die_two` and
        with whatever the player ultimately committed to.

        Currently emitted tokens:
          doubles    -- both final dice were equal (1..6)

        Future tokens (e.g. "sum.N", "die.N", "snake_eyes") can be added here.
        """
        events = []
        try:
            d1 = int(die_one or 0)
            d2 = int(die_two or 0)
        except (TypeError, ValueError):
            return events
        if 1 <= d1 <= 6 and 1 <= d2 <= 6 and d1 == d2:
            events.append("doubles")
        return events

    def _apply_roll_on_event_passives(self):
        """Fire owned-domain `roll.on_event <event> <resource> <amount>` passives across all players.

        Grammar: `roll.on_event <event-token> <g|s|m|v> <int>`. Currently supported
        event tokens are whatever `_compute_roll_events` emits (e.g. "doubles").

        Reads `self.roll_events`, which is populated in `finalize_roll` from
        the FINAL dice (post-modification). A player who spent roll modifiers
        to land on e.g. doubles legitimately triggered the event; the engine
        treats the final dice as the source of truth.
        """
        events = set(getattr(self, "roll_events", None) or [])
        if not events:
            return
        for p in list(getattr(self, "player_list", []) or []):
            for d in list(getattr(p, "owned_domains", []) or []):
                if self._domain_recurring_passive_on_build_turn_cooldown(d):
                    continue
                raw = (getattr(d, "passive_effect", None) or "").strip()
                if not raw:
                    continue
                parts = raw.split()
                if not parts or parts[0].lower() != "roll.on_event":
                    continue
                if len(parts) < 4:
                    continue
                event = parts[1].lower()
                res = parts[2].lower()
                try:
                    amount = int(parts[3])
                except (TypeError, ValueError):
                    continue
                if res not in ("g", "s", "m", "v") or amount <= 0:
                    continue
                if event not in events:
                    continue
                before = self._player_scores_line(p)
                if res == "g":
                    p.gold_score = int(p.gold_score) + amount
                elif res == "s":
                    p.strength_score = int(p.strength_score) + amount
                elif res == "m":
                    p.magic_score = int(p.magic_score) + amount
                elif res == "v":
                    p.victory_score = int(getattr(p, "victory_score", 0)) + amount
                after = self._player_scores_line(p)
                self._log_game_event(
                    f"{self._player_label(p.player_id)} \"{getattr(d, 'name', 'Domain')}\" triggered "
                    f"({event}); scores {before} -> {after}"
                )

    def _apply_board_event_roll_effects(self, d1, d2):
        """Check all board stacks for Event cards with roll effects matching d1 or d2.

        Iterates monster_grid (plus citizen_grid, domain_grid for future-proofing).
        When an Event card's roll_match1 equals d1 or d2, fires its roll_effect.
        """
        active_player_id = self.current_player_id()
        grids = [self.monster_grid, self.citizen_grid, self.domain_grid]
        for grid in grids:
            for stack in (grid or []):
                if not stack:
                    continue
                top = stack[-1]
                if not isinstance(top, Event):
                    continue
                if not top.has_roll_effect:
                    continue
                try:
                    match_val = int(top.roll_match1 or 0)
                except (TypeError, ValueError):
                    continue
                if match_val == d1 or match_val == d2 or match_val == (d1 + d2):
                    self._execute_event_roll_effect(top, active_player_id)

    def _execute_event_roll_effect(self, event, player_id):
        """Execute an Event card's roll_effect string.

        Supported grammar:
          all_lose g|s|m N  — all players lose N of the resource (floor at 0)
          add_slay_cost g|s|m N  — active player must add N cost to a chosen
                                   accessible monster; stored as pending_event_slay_cost
        """
        raw = (event.roll_effect or "").strip()
        if not raw:
            return
        parts = raw.split()
        if len(parts) < 3:
            self._log_game_event(
                f"Event \"{event.name}\" triggered but roll_effect is malformed: {raw!r}"
            )
            return

        verb = parts[0].lower()
        resource = parts[1].lower()
        try:
            amount = int(parts[2])
        except (TypeError, ValueError):
            self._log_game_event(
                f"Event \"{event.name}\" triggered but amount is not an int: {parts[2]!r}"
            )
            return

        if verb == "all_lose":
            res_map = {"g": "gold_score", "s": "strength_score", "m": "magic_score"}
            attr = res_map.get(resource)
            if not attr:
                self._log_game_event(
                    f"Event \"{event.name}\" all_lose: unknown resource {resource!r}"
                )
                return
            for p in list(getattr(self, "player_list", []) or []):
                if not self._player_is_negative_effect_target(p):
                    self._log_game_event(
                        f"{self._player_label(p.player_id)} is resting; "
                        f"loses 0{resource} from event \"{event.name}\"."
                    )
                    continue
                current = int(getattr(p, attr, 0) or 0)
                new_val = max(0, current - amount)
                if current != new_val:
                    self._log_game_event(
                        f"{self._player_label(p.player_id)} loses {amount}{resource} "
                        f"from event \"{event.name}\" (was {current}, now {new_val})."
                    )
                else:
                    self._log_game_event(
                        f"{self._player_label(p.player_id)} loses 0{resource} "
                        f"from event \"{event.name}\" (already at {current}, floored)."
                    )
                setattr(p, attr, new_val)

        elif verb == "add_slay_cost":
            # Check if any accessible monster exists on the board.
            has_target = False
            for stack in (self.monster_grid or []):
                if not stack:
                    continue
                t = stack[-1]
                if getattr(t, "is_accessible", False) and (
                    getattr(t, "monster_id", None) is not None
                    or getattr(t, "event_id", None) is not None
                ):
                    has_target = True
                    break
            if not has_target:
                self._log_game_event(
                    f"Event \"{event.name}\" triggered add_slay_cost but no accessible "
                    f"monsters on the board; skipped."
                )
                return
            self.pending_event_slay_cost = {
                "player_id": player_id,
                "resource": resource,
                "amount": amount,
                "event_name": event.name,
            }
            self.action_required["id"] = player_id
            self.action_required["action"] = "event_slay_cost_choice"
            self._log_game_event(
                f"Event \"{event.name}\" triggered: {self._player_label(player_id)} must add "
                f"{amount}{resource} to a chosen monster's slay cost."
            )
        else:
            self._log_game_event(
                f"Event \"{event.name}\" triggered but unknown verb: {verb!r}"
            )

    def apply_event_slay_cost(self, player_id, monster_id=None, event_id=None):
        """Resolve the pending_event_slay_cost choice.

        The active player chooses an accessible monster (by monster_id or event_id)
        and we apply the extra cost modifier to that card.
        """
        pesc = getattr(self, "pending_event_slay_cost", None)
        if not pesc:
            raise ValueError("No pending event slay cost choice.")
        if str(pesc.get("player_id")) != str(player_id):
            raise ValueError("It is not your turn to resolve this event effect.")

        resource = pesc.get("resource", "s")
        amount = int(pesc.get("amount", 1) or 1)
        event_name = pesc.get("event_name", "Event")

        # Find the target card on the board.
        target = None
        if monster_id is not None:
            for stack in (self.monster_grid or []):
                if not stack:
                    continue
                t = stack[-1]
                if not getattr(t, "is_accessible", False):
                    continue
                if int(getattr(t, "monster_id", -1)) == int(monster_id):
                    target = t
                    break
        elif event_id is not None:
            for stack in (self.monster_grid or []):
                if not stack:
                    continue
                t = stack[-1]
                if not getattr(t, "is_accessible", False):
                    continue
                if int(getattr(t, "event_id", -1)) == int(event_id):
                    target = t
                    break

        if target is None:
            raise ValueError("Target monster not found or not accessible.")

        # Apply the extra cost to the card.
        if resource == "s":
            target.extra_strength_cost = int(getattr(target, "extra_strength_cost", 0) or 0) + amount
        elif resource == "m":
            target.extra_magic_cost = int(getattr(target, "extra_magic_cost", 0) or 0) + amount
        elif resource == "g":
            target.extra_gold_cost = int(getattr(target, "extra_gold_cost", 0) or 0) + amount

        self._log_game_event(
            f"{self._player_label(player_id)} applied event \"{event_name}\": "
            f"\"{getattr(target, 'name', '?')}\" slay cost +{amount}{resource}."
        )

        # Clear the pending state.
        self.pending_event_slay_cost = None
        self.action_required["id"] = self.game_id
        self.action_required["action"] = ""

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

    def _player_scores_line(self, player):
        if not player:
            return "G?/S?/M?/VP?"
        g = int(getattr(player, "gold_score", 0) or 0)
        s = int(getattr(player, "strength_score", 0) or 0)
        m = int(getattr(player, "magic_score", 0) or 0)
        v = int(getattr(player, "victory_score", 0) or 0)
        return f"G{g}/S{s}/M{m}/VP{v}"

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
        while len(self.game_log) > _GAME_LOG_MAX:
            self.game_log.pop(0)

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

    def _roll_match_count(self, card):
        d1, d2, ds = self.die_one, self.die_two, self.die_sum
        rm1 = getattr(card, "roll_match1", None)
        rm2 = getattr(card, "roll_match2", None)
        if rm1 is None:
            return False, 0
        try:
            rm2 = int(rm2) if rm2 is not None else 0
        except (TypeError, ValueError):
            rm2 = 0
        if (rm1 == d1) or (rm1 == d2) or (rm1 == ds) or (rm2 == ds):
            count = 2 if rm1 == d1 == d2 else 1
            return True, count
        return False, 0

    def _bump_harvest_delta(self, player, dg, ds, dm, dv=0):
        hd = player.harvest_delta
        hd["gold"] = int(hd.get("gold", 0)) + int(dg)
        hd["strength"] = int(hd.get("strength", 0)) + int(ds)
        hd["magic"] = int(hd.get("magic", 0)) + int(dm)
        hd["victory"] = int(hd.get("victory", 0)) + int(dv)

    def _apply_harvest_activation(self, player, starter_or_citizen, kind, on_turn):
        """
        kind: "starter" | "citizen"
        on_turn: use on-turn payout columns for the active player this harvest round.
        """
        before_scores = self._player_scores_line(player)
        card_name = getattr(starter_or_citizen, "name", "?")
        turn_lbl = "on-turn" if on_turn else "off-turn"
        # Tag any bare-verb `slay` payouts produced by this harvest activation with
        # the source card's name (used by the deferred-slay prompt at end of harvest).
        # Cleared in the outer `finally` below so the tag never leaks across cards.
        self._immediate_slay_source_label = card_name
        def _special_cmd(obj, which):
            """
            Some DB rows historically relied on a boolean has_special_payout_* flag.
            In practice, the command text being present is sufficient, so treat
            non-empty special_payout_* as the source of truth (ignoring "0").
            """
            raw = getattr(obj, which, None)
            cmd = ("" if raw is None else str(raw)).strip()
            if not cmd or cmd == "0":
                return ""
            return cmd
        try:
            if kind == "starter":
                s = starter_or_citizen
                if on_turn:
                    dg = int(getattr(s, "gold_payout_on_turn", 0) or 0)
                    ds = int(getattr(s, "strength_payout_on_turn", 0) or 0)
                    dm = int(getattr(s, "magic_payout_on_turn", 0) or 0)
                    player.gold_score = int(player.gold_score) + dg
                    player.strength_score = int(player.strength_score) + ds
                    player.magic_score = int(player.magic_score) + dm
                    self._bump_harvest_delta(player, dg, ds, dm, 0)
                    cmd = _special_cmd(s, "special_payout_on_turn")
                    if getattr(s, "has_special_payout_on_turn", False) or cmd:
                        payout = self.execute_special_payout(cmd or s.special_payout_on_turn, player.player_id)
                        player.gold_score = int(player.gold_score) + payout[0]
                        player.strength_score = int(player.strength_score) + payout[1]
                        player.magic_score = int(player.magic_score) + payout[2]
                        player.victory_score = int(player.victory_score) + payout[3]
                        self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
                else:
                    dg = int(getattr(s, "gold_payout_off_turn", 0) or 0)
                    ds = int(getattr(s, "strength_payout_off_turn", 0) or 0)
                    dm = int(getattr(s, "magic_payout_off_turn", 0) or 0)
                    player.gold_score = int(player.gold_score) + dg
                    player.strength_score = int(player.strength_score) + ds
                    player.magic_score = int(player.magic_score) + dm
                    self._bump_harvest_delta(player, dg, ds, dm, 0)
                    cmd = _special_cmd(s, "special_payout_off_turn")
                    if getattr(s, "has_special_payout_off_turn", False) or cmd:
                        payout = self.execute_special_payout(cmd or s.special_payout_off_turn, player.player_id)
                        player.gold_score = int(player.gold_score) + payout[0]
                        player.strength_score = int(player.strength_score) + payout[1]
                        player.magic_score = int(player.magic_score) + payout[2]
                        player.victory_score = int(player.victory_score) + payout[3]
                        self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
                return

            c = starter_or_citizen
            if on_turn:
                dg = int(getattr(c, "gold_payout_on_turn", 0) or 0)
                ds = int(getattr(c, "strength_payout_on_turn", 0) or 0)
                dm = int(getattr(c, "magic_payout_on_turn", 0) or 0)
                dv = int(getattr(c, "vp_payout_on_turn", 0) or 0)
                player.gold_score = int(player.gold_score) + dg
                player.strength_score = int(player.strength_score) + ds
                player.magic_score = int(player.magic_score) + dm
                player.victory_score = int(player.victory_score) + dv
                self._bump_harvest_delta(player, dg, ds, dm, dv)
                cmd = _special_cmd(c, "special_payout_on_turn")
                if getattr(c, "has_special_payout_on_turn", False) or cmd:
                    payout = self.execute_special_payout(cmd or c.special_payout_on_turn, player.player_id)
                    player.gold_score = int(player.gold_score) + payout[0]
                    player.strength_score = int(player.strength_score) + payout[1]
                    player.magic_score = int(player.magic_score) + payout[2]
                    player.victory_score = int(player.victory_score) + payout[3]
                    self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
            else:
                dg = int(getattr(c, "gold_payout_off_turn", 0) or 0)
                ds = int(getattr(c, "strength_payout_off_turn", 0) or 0)
                dm = int(getattr(c, "magic_payout_off_turn", 0) or 0)
                dv = int(getattr(c, "vp_payout_off_turn", 0) or 0)
                player.gold_score = int(player.gold_score) + dg
                player.strength_score = int(player.strength_score) + ds
                player.magic_score = int(player.magic_score) + dm
                player.victory_score = int(player.victory_score) + dv
                self._bump_harvest_delta(player, dg, ds, dm, dv)
                cmd = _special_cmd(c, "special_payout_off_turn")
                if getattr(c, "has_special_payout_off_turn", False) or cmd:
                    payout = self.execute_special_payout(cmd or c.special_payout_off_turn, player.player_id)
                    player.gold_score = int(player.gold_score) + payout[0]
                    player.strength_score = int(player.strength_score) + payout[1]
                    player.magic_score = int(player.magic_score) + payout[2]
                    player.victory_score = int(player.victory_score) + payout[3]
                    self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
        finally:
            self._immediate_slay_source_label = None
            after_scores = self._player_scores_line(player)
            if before_scores != after_scores:
                self._log_game_event(
                    f"{self._player_label(player.player_id)} harvest {kind} \"{card_name}\" "
                    f"({turn_lbl}): scores {before_scores} -> {after_scores}"
                )

    def _build_harvest_slots(self, player, consumed_keys, on_turn):
        consumed = set(consumed_keys or [])
        slots = []
        for idx, st in enumerate(getattr(player, "owned_starters", []) or []):
            ok, n = self._roll_match_count(st)
            # `activation_trigger` lets a starter fire on non-dice conditions
            # (e.g. doubles, end-of-harvest "no payout"). `doubles` is the only
            # leg evaluable in-band; `no_payout` is handled in
            # `_harvest_complete_finalize` because it depends on the final
            # harvest_delta after every other card has resolved.
            if not ok:
                trig = (getattr(st, "activation_trigger", "") or "").lower()
                if "doubles" in trig and self.die_one == self.die_two and self.die_one != 0:
                    ok, n = True, 1
            if not ok:
                continue
            sid = int(getattr(st, "starter_id", -1))
            for i in range(n):
                key = f"starter:{sid}:{idx}:{i}"
                if key not in consumed:
                    slots.append({
                        "slot_key": key,
                        "kind": "starter",
                        "card_id": sid,
                        "card_idx": idx,
                        "activation_index": i,
                        "name": getattr(st, "name", "?"),
                        "is_thief": False,
                        "_obj": st,
                    })
        for idx, cit in enumerate(getattr(player, "owned_citizens", []) or []):
            if getattr(cit, "is_flipped", False):
                continue
            ok, n = self._roll_match_count(cit)
            if not ok:
                continue
            cid = int(getattr(cit, "citizen_id", -1))
            is_thief = _citizen_has_steal(cit, on_turn)
            for i in range(n):
                key = f"citizen:{cid}:{idx}:{i}"
                if key not in consumed:
                    slots.append({
                        "slot_key": key,
                        "kind": "citizen",
                        "card_id": cid,
                        "card_idx": idx,
                        "activation_index": i,
                        "name": getattr(cit, "name", "?"),
                        "is_thief": is_thief,
                        "_obj": cit,
                    })
        return slots

    def _harvest_slots_sorted_for_simulation(self, slots):
        starters = [s for s in slots if s["kind"] == "starter"]
        citizens = [s for s in slots if s["kind"] == "citizen"]
        thieves = [s for s in citizens if s["is_thief"]]
        rest_c = [s for s in citizens if not s["is_thief"]]
        return starters + thieves + rest_c

    def _player_has_unharvested_steal_citizen(self, player, consumed_keys, on_turn):
        consumed = set(consumed_keys or [])
        for idx, cit in enumerate(getattr(player, "owned_citizens", []) or []):
            if getattr(cit, "is_flipped", False):
                continue
            if not _citizen_has_steal(cit, on_turn):
                continue
            ok, n = self._roll_match_count(cit)
            if not ok:
                continue
            cid = int(getattr(cit, "citizen_id", -1))
            for i in range(n):
                key = f"citizen:{cid}:{idx}:{i}"
                if key not in consumed:
                    return True
        return False

    def _harvest_action_blocked(self):
        if self.is_blocked_on_concurrent_action():
            return True
        aid = self.action_required.get("id") if self.action_required else None
        if not aid or aid == self.game_id:
            return False
        aa = self.action_required.get("action") or ""
        if aa in (
            "bonus_resource_choice",
            "manual_harvest",
            "harvest_optional_exchange",
            "harvest_steal",
            "harvest_wild_gain_exchange",
            "harvest_wild_cost_exchange",
            "choose_domain_reward",
            "choose_monster_slay",
            "slay_monster_payment",
        ):
            return True
        if str(aa).startswith("choose ") or str(aa).startswith("choose_player") or str(aa).startswith("choose_monster"):
            return True
        if str(aa).startswith("choose_owned"):
            return True
        if str(aa) == "domain_self_convert":
            return True
        return False

    def _harvest_complete_finalize(self):
        self.harvest_processed = True
        self.harvest_player_order = None
        self.harvest_player_idx = 0
        # Snapshot which players had any card activate this harvest BEFORE
        # resetting the bookkeeping. We gate the end-of-harvest bonus
        # (legacy bonus_resource_choice or Herald's `no_payout` trigger) on
        # "no cards of yours fired", not on "harvest_delta is zero" — those
        # diverge whenever a card activates but its payout nets nothing
        # (e.g. an `exchange` you can't afford, a `count` that finds zero
        # of the counted thing, a steal against an empty victim, etc.).
        activated_pids = {pid for pid, keys in self.harvest_consumed.items() if keys}
        self.harvest_consumed = {}
        self._harvest_steal_phase_done = False
        # Pending may-slay prompts contributed gains directly (via slay_monster), so
        # by the time we reach this finalize step they should be drained. Defensive
        # clear so a malformed entry can't pin the harvest open across phases.
        self.pending_harvest_slays = []
        self.pending_harvest_choices = []
        # 5-player resting seat: that player did not harvest at all this round,
        # so they do NOT get the missed-harvest consolation prompt either (they
        # would otherwise look identical to "had no matching cards").
        resting_pid = self.resting_player_id()
        for p in self.player_list:
            if resting_pid is not None and p.player_id == resting_pid:
                continue
            if p.player_id not in activated_pids:
                self.pending_harvest_choices.append(p.player_id)
        if self.pending_harvest_choices:
            self._activate_finalize_bonus_for(self.pending_harvest_choices[0])
        else:
            self.action_required["id"] = self.game_id
            self.action_required["action"] = ""

    def _find_owned_starter_with_trigger(self, player, trigger_substr):
        """Return the first non-flipped owned starter whose activation_trigger
        contains `trigger_substr` (case-insensitive), else None."""
        for st in getattr(player, "owned_starters", []) or []:
            if getattr(st, "is_flipped", False):
                continue
            trig = (getattr(st, "activation_trigger", "") or "").lower()
            if trigger_substr in trig:
                return st
        return None

    def _activate_finalize_bonus_for(self, player_id):
        """Open the end-of-harvest bonus prompt for `player_id`.

        If the player owns a starter with a `no_payout` activation trigger
        (Herald), fire it via the normal harvest activation pipeline (which
        opens its `choose g 1 s 1 m 1` prompt). Otherwise fall back to the
        legacy hard-coded `bonus_resource_choice` action so players without
        Herald still get the missed-harvest consolation.
        """
        player = self._player_by_id(player_id)
        if not player:
            if self.pending_harvest_choices and self.pending_harvest_choices[0] == player_id:
                self.pending_harvest_choices.pop(0)
            if self.pending_harvest_choices:
                self._activate_finalize_bonus_for(self.pending_harvest_choices[0])
            else:
                self.action_required["id"] = self.game_id
                self.action_required["action"] = ""
            return
        starter = self._find_owned_starter_with_trigger(player, "no_payout")
        if starter is not None:
            on_turn = player_id == self.current_player_id()
            self._apply_harvest_activation(player, starter, "starter", on_turn)
            # Activation normally opens a `choose ...` prompt; if it didn't (e.g.
            # malformed special_payout), advance the queue so we don't stall.
            aa = (self.action_required.get("action") or "").strip()
            aid = self.action_required.get("id")
            if aid == player_id and aa:
                return
            if self.pending_harvest_choices and self.pending_harvest_choices[0] == player_id:
                self.pending_harvest_choices.pop(0)
            if self.pending_harvest_choices:
                self._activate_finalize_bonus_for(self.pending_harvest_choices[0])
            else:
                self.action_required["id"] = self.game_id
                self.action_required["action"] = ""
            return
        # Legacy fallback: hard-coded bonus_resource_choice prompt.
        self.action_required["id"] = player_id
        self.action_required["action"] = "bonus_resource_choice"

    def _harvest_run_automation_until_blocked(self):
        # Steal pre-phase: all steal effects across all players fire first, in harvest
        # turn order (active player first, then around the board). This ensures steals
        # resolve before any normal payouts regardless of whose card it is.
        if not getattr(self, "_harvest_steal_phase_done", False):
            while True:
                if self._harvest_action_blocked():
                    return
                order = getattr(self, "harvest_player_order", None) or []
                found_steal = False
                for pid in order:
                    player = self._player_by_id(pid)
                    if not player:
                        continue
                    consumed_list = self.harvest_consumed.setdefault(pid, [])
                    on_turn = pid == self.current_player_id()
                    steal_slots = [
                        s for s in self._build_harvest_slots(player, consumed_list, on_turn)
                        if s["is_thief"]
                    ]
                    if steal_slots:
                        slot = steal_slots[0]
                        self._apply_harvest_activation(player, slot["_obj"], slot["kind"], on_turn)
                        consumed_list.append(slot["slot_key"])
                        found_steal = True
                        break  # restart scan from top of turn order
                if self._harvest_action_blocked():
                    return
                if not found_steal:
                    break  # no more steals across any player
            self._harvest_steal_phase_done = True

        # Normal harvest: process each player's remaining cards in turn order.
        while not getattr(self, "harvest_processed", False):
            if self._harvest_action_blocked():
                return
            order = getattr(self, "harvest_player_order", None) or []
            if self.harvest_player_idx >= len(order):
                # All players' regular payouts (including specials) are complete.
                # Drain any deferred may-slay prompts queued by citizen payouts; the
                # drain itself opens the next prompt or finalizes harvest when empty.
                if self.pending_harvest_slays:
                    self._drain_pending_harvest_slays()
                else:
                    self._harvest_complete_finalize()
                return
            pid = order[self.harvest_player_idx]
            player = self._player_by_id(pid)
            if not player:
                self.harvest_player_idx += 1
                continue
            consumed_list = self.harvest_consumed.get(pid)
            if consumed_list is None:
                consumed_list = []
                self.harvest_consumed[pid] = consumed_list
            on_turn = pid == self.current_player_id()
            slots = self._build_harvest_slots(player, consumed_list, on_turn)
            if not slots:
                self.harvest_player_idx += 1
                continue
            slot = self._harvest_slots_sorted_for_simulation(slots)[0]
            self._apply_harvest_activation(player, slot["_obj"], slot["kind"], on_turn)
            consumed_list.append(slot["slot_key"])
            if self._harvest_action_blocked():
                return

    def harvest_slots_for_api(self):
        if self.action_required.get("action") != "manual_harvest":
            return []
        pid = self.action_required.get("id")
        player = self._player_by_id(pid)
        if not player:
            return []
        consumed_list = self.harvest_consumed.get(pid) or []
        on_turn = pid == self.current_player_id()
        slots = self._build_harvest_slots(player, consumed_list, on_turn)
        out = []
        for s in slots:
            out.append({
                "slot_key": s["slot_key"],
                "kind": s["kind"],
                "card_id": s["card_id"],
                "card_idx": s.get("card_idx", 0),
                "activation_index": s["activation_index"],
                "name": s["name"],
                "is_thief": s["is_thief"],
            })
        return out

    def harvest_card(self, player_id, slot_key):
        if self.phase != "harvest" or getattr(self, "harvest_processed", False):
            raise ValueError("Not in harvest phase.")
        if self.action_required.get("action") != "manual_harvest":
            raise ValueError("No harvest choice is pending.")
        if self.action_required.get("id") != player_id:
            raise ValueError("It is not your turn to harvest.")
        sk = (slot_key or "").strip()
        if not sk:
            raise ValueError("slot_key required.")
        player = self._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        consumed_list = self.harvest_consumed.get(player_id)
        if consumed_list is None:
            consumed_list = []
            self.harvest_consumed[player_id] = consumed_list
        on_turn = player_id == self.current_player_id()
        slots = self._build_harvest_slots(player, consumed_list, on_turn)
        chosen = None
        for s in slots:
            if s["slot_key"] == sk:
                chosen = s
                break
        if not chosen:
            raise ValueError("Invalid harvest slot.")
        if chosen["kind"] == "citizen" and not chosen["is_thief"]:
            if self._player_has_unharvested_steal_citizen(player, consumed_list, on_turn):
                raise ValueError("Resolve steal effects before other harvest cards.")
        self._apply_harvest_activation(player, chosen["_obj"], chosen["kind"], on_turn)
        consumed_list.append(sk)
        # If the activation triggered a blocking prompt (e.g. special payout "choose ..."),
        # do NOT clear action_required here. The player must respond first, and then
        # act_on_required_action() will resume harvest automation.
        aa = (self.action_required.get("action") or "").strip()
        aid = self.action_required.get("id")
        if aid == player_id and aa and aa != "manual_harvest":
            return

        self.action_required["id"] = self.game_id
        self.action_required["action"] = ""
        self._harvest_run_automation_until_blocked()
        if self.phase == "harvest" and self.harvest_processed and not self._harvest_action_blocked():
            self.advance_tick()

    def harvest_phase(self):
        """Resolve the entire harvest non-interactively (local scripts / play_turn)."""
        for p in self.player_list:
            p.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
        active = self._player_by_id(self.current_player_id())
        self._apply_harvest_jousting_passive(active)
        resting_pid = self.resting_player_id()
        if resting_pid is not None:
            self._log_game_event(
                f"{self._player_label(resting_pid)} is resting (5-player rule); no harvest this turn."
            )
        self._silent_harvest_batch = True
        try:
            order = self._harvest_player_id_order_starting_active()
            for pid in order:
                player = self._player_by_id(pid)
                if not player:
                    continue
                on_turn = pid == self.current_player_id()
                consumed = []
                while True:
                    slots = self._harvest_slots_sorted_for_simulation(
                        self._build_harvest_slots(player, consumed, on_turn))
                    if not slots:
                        break
                    for slot in slots:
                        self._apply_harvest_activation(player, slot["_obj"], slot["kind"], on_turn)
                        consumed.append(slot["slot_key"])
        finally:
            self._silent_harvest_batch = False
        # Silent batch harvest can't open prompts; drop any deferred slay opportunities
        # that citizens may have queued. Interactive harvest drains them via
        # `_harvest_run_automation_until_blocked` -> `_drain_pending_harvest_slays`.
        if self.pending_harvest_slays:
            for entry in self.pending_harvest_slays:
                self._log_game_event(
                    f"{self._player_label(entry.get('player_id'))} skipped slay "
                    f"prompt from \"{entry.get('source_label', 'Effect')}\" (silent harvest)."
                )
            self.pending_harvest_slays = []
        for player in self.player_list:
            print(f"Player {player.name}: {player.gold_score} G, {player.strength_score} S, {player.magic_score} M,"
                  f" {player.victory_score} VP, Monsters: {len(player.owned_monsters)}, "
                  f"Citizens: {len(player.owned_citizens)}, Domains {len(player.owned_domains)}")

    def _maybe_resume_harvest_prompt(self):
        if self.phase != "harvest" or getattr(self, "harvest_processed", False):
            return
        if getattr(self, "harvest_player_order", None) is None:
            return
        if self._harvest_action_blocked():
            return
        self._harvest_run_automation_until_blocked()

    def _want_harvest_optional_exchange_prompt(self, raw_command):
        """
        During interactive harvest only: pure \"exchange pay gain\" specials pause for confirm/skip.
        Batch harvest_phase() sets _silent_harvest_batch so exchanges auto-resolve when affordable.
        """
        if getattr(self, "phase", None) != "harvest":
            return False
        if getattr(self, "_silent_harvest_batch", False):
            return False
        rc = (raw_command or "").strip()
        if " + " in rc:
            return False
        parts = rc.split()
        if len(parts) < 5:
            return False
        return parts[0].lower() == "exchange"

    def _execute_steal_payout(self, command, player_id):
        """
        Parse "steal R1 N1 [R2 N2 ...]" and build a flat prompt of (resource, amount, victim) combos.
        Format: steal g 3        — steal 3g from a chosen opponent
                steal g 3 m 3    — steal 3g or 3m from a chosen opponent (one combined choice)
        The flat options list is resource-options × opponents, presented as a single prompt.
        """
        parts = (command or "").split()
        # Parse resource options: pairs after "steal" keyword
        RESOURCES = {"g", "s", "m", "v"}
        resource_opts = []
        i = 1
        while i + 1 < len(parts):
            res = parts[i].lower()
            if res not in RESOURCES:
                break
            try:
                amt = int(parts[i + 1])
            except (TypeError, ValueError):
                break
            resource_opts.append((res, amt))
            i += 2
        if not resource_opts:
            return [-9999, 0, 0, 0]
        opponents = [p for p in self.player_list if p.player_id != player_id]
        if not opponents:
            return [0, 0, 0, 0]
        opponents = [
            p for p in opponents
            if not self._player_has_take_immunity(p)
            and self._player_is_negative_effect_target(p)
        ]
        if not opponents:
            self._log_game_event(
                f"{self._player_label(player_id)} could not steal — all opponents are immune."
            )
            return [0, 0, 0, 0]
        victim_options = []
        for opp in opponents:
            opp_name = getattr(opp, "name", None) or f"Player {opp.player_id}"
            victim_options.append({
                "victim_id": opp.player_id,
                "victim_name": opp_name,
            })
        resource_options = [
            {"resource": res, "amount": amt}
            for res, amt in resource_opts
        ]
        # Keep flat legacy options in state for older clients, but the current UI
        # resolves steal as victim first, then resource when there is a choice.
        options = []
        for victim_opt in victim_options:
            for resource_opt in resource_options:
                options.append({
                    "kind": "steal",
                    "victim_id": victim_opt["victim_id"],
                    "victim_name": victim_opt["victim_name"],
                    "resource": resource_opt["resource"],
                    "amount": resource_opt["amount"],
                })
        self.pending_required_choice = {
            "kind": "harvest_steal",
            "stage": "victim",
            "player_id": player_id,
            "victim_options": victim_options,
            "resource_options": resource_options,
            "options": options,
        }
        self.action_required["id"] = player_id
        self.action_required["action"] = "harvest_steal"
        return [0, 0, 0, 0]

    def _apply_harvest_steal_choice(self, player_id, victim_id, resource, amount):
        thief = self._player_by_id(player_id)
        victim = self._player_by_id(victim_id)
        if not thief or not victim:
            return False
        res_s = (resource or "g").strip().lower()
        want_s = int(amount or 0)
        score_map = {"g": "gold_score", "s": "strength_score", "m": "magic_score", "v": "victory_score"}
        attr_s = score_map.get(res_s)
        if not attr_s or want_s <= 0:
            return False
        have_s = int(getattr(victim, attr_s, 0) or 0)
        actual_s = min(want_s, have_s)
        before_thief = self._player_scores_line(thief)
        before_victim = self._player_scores_line(victim)
        setattr(victim, attr_s, have_s - actual_s)
        setattr(thief, attr_s, int(getattr(thief, attr_s, 0) or 0) + actual_s)
        dg = actual_s if res_s == "g" else 0
        ds = actual_s if res_s == "s" else 0
        dm = actual_s if res_s == "m" else 0
        dv = actual_s if res_s == "v" else 0
        self._bump_harvest_delta(thief, dg, ds, dm, dv)
        after_thief = self._player_scores_line(thief)
        after_victim = self._player_scores_line(victim)
        self._log_game_event(
            f"{self._player_label(player_id)} stole {actual_s}{res_s} from "
            f"{self._player_label(victim_id)}; "
            f"thief {before_thief} -> {after_thief}, "
            f"victim {before_victim} -> {after_victim}"
        )
        return True

    _WILD_SCORE_MAP = {"g": "gold_score", "s": "strength_score", "m": "magic_score", "v": "victory_score"}

    def _execute_wild_gain_exchange_payout(self, command, player_id):
        """exchange [res] [N] wild [M] — pay N of res, then choose M of any resource (g/s/m)."""
        parts = (command or "").split()
        if len(parts) < 5:
            return [-9999, 0, 0, 0]
        cost_res = parts[1].lower()
        try:
            cost_amt = int(parts[2])
            gain_amt = int(parts[4])
        except (ValueError, IndexError):
            return [-9999, 0, 0, 0]
        if cost_res not in self._WILD_SCORE_MAP or cost_amt <= 0 or gain_amt <= 0:
            return [-9999, 0, 0, 0]
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        if int(getattr(player, self._WILD_SCORE_MAP[cost_res], 0) or 0) < cost_amt:
            return [0, 0, 0, 0]
        self.pending_required_choice = {
            "kind": "harvest_wild_gain_exchange",
            "player_id": player_id,
            "cost_resource": cost_res,
            "cost_amount": cost_amt,
            "gain_amount": gain_amt,
            "command": command,
        }
        self.action_required["id"] = player_id
        self.action_required["action"] = "harvest_wild_gain_exchange"
        return [0, 0, 0, 0]

    def _apply_wild_gain_exchange_choice(self, player_id, gain_res, prc):
        """Deduct the fixed cost then award the chosen resource."""
        player = self._player_by_id(player_id)
        if not player:
            return
        cost_res = prc["cost_resource"]
        cost_amt = prc["cost_amount"]
        gain_amt = prc["gain_amount"]
        before = self._player_scores_line(player)
        setattr(player, self._WILD_SCORE_MAP[cost_res],
                int(getattr(player, self._WILD_SCORE_MAP[cost_res], 0)) - cost_amt)
        setattr(player, self._WILD_SCORE_MAP[gain_res],
                int(getattr(player, self._WILD_SCORE_MAP[gain_res], 0)) + gain_amt)
        dg = (-cost_amt if cost_res == "g" else 0) + (gain_amt if gain_res == "g" else 0)
        ds = (-cost_amt if cost_res == "s" else 0) + (gain_amt if gain_res == "s" else 0)
        dm = (-cost_amt if cost_res == "m" else 0) + (gain_amt if gain_res == "m" else 0)
        dv = (-cost_amt if cost_res == "v" else 0) + (gain_amt if gain_res == "v" else 0)
        self._bump_harvest_delta(player, dg, ds, dm, dv)
        after = self._player_scores_line(player)
        self._log_game_event(
            f"{self._player_label(player_id)} wild-gain exchange ({prc.get('command')}): "
            f"chose {gain_res}; scores {before} -> {after}"
        )

    def _execute_wild_cost_exchange_payout(self, command, player_id):
        """exchange wild [N] [res] [M] — choose which resource to pay N of, then gain M of res."""
        parts = (command or "").split()
        if len(parts) < 5:
            return [-9999, 0, 0, 0]
        try:
            cost_amt = int(parts[2])
            gain_amt = int(parts[4])
        except (ValueError, IndexError):
            return [-9999, 0, 0, 0]
        gain_res = parts[3].lower()
        if gain_res not in self._WILD_SCORE_MAP or cost_amt <= 0 or gain_amt <= 0:
            return [-9999, 0, 0, 0]
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        options = [
            {"resource": res, "amount": cost_amt}
            for res in ("g", "s", "m")
            if int(getattr(player, self._WILD_SCORE_MAP[res], 0) or 0) >= cost_amt
        ]
        if not options:
            return [0, 0, 0, 0]
        self.pending_required_choice = {
            "kind": "harvest_wild_cost_exchange",
            "player_id": player_id,
            "cost_options": options,
            "gain_resource": gain_res,
            "gain_amount": gain_amt,
            "command": command,
        }
        self.action_required["id"] = player_id
        self.action_required["action"] = "harvest_wild_cost_exchange"
        return [0, 0, 0, 0]

    def _apply_wild_cost_exchange_choice(self, player_id, cost_res, prc):
        """Deduct the chosen resource then award the fixed gain."""
        player = self._player_by_id(player_id)
        if not player:
            return
        cost_opts = prc.get("cost_options") or []
        cost_amt = next((o["amount"] for o in cost_opts if o["resource"] == cost_res), None)
        if cost_amt is None:
            return
        gain_res = prc["gain_resource"]
        gain_amt = prc["gain_amount"]
        before = self._player_scores_line(player)
        setattr(player, self._WILD_SCORE_MAP[cost_res],
                int(getattr(player, self._WILD_SCORE_MAP[cost_res], 0)) - cost_amt)
        setattr(player, self._WILD_SCORE_MAP[gain_res],
                int(getattr(player, self._WILD_SCORE_MAP[gain_res], 0)) + gain_amt)
        dg = (-cost_amt if cost_res == "g" else 0) + (gain_amt if gain_res == "g" else 0)
        ds = (-cost_amt if cost_res == "s" else 0) + (gain_amt if gain_res == "s" else 0)
        dm = (-cost_amt if cost_res == "m" else 0) + (gain_amt if gain_res == "m" else 0)
        dv = (-cost_amt if cost_res == "v" else 0) + (gain_amt if gain_res == "v" else 0)
        self._bump_harvest_delta(player, dg, ds, dm, dv)
        after = self._player_scores_line(player)
        self._log_game_event(
            f"{self._player_label(player_id)} wild-cost exchange ({prc.get('command')}): "
            f"paid {cost_res}; scores {before} -> {after}"
        )

    def _execute_grant_domain_payout(self, player_id):
        """Grant one free domain chosen from the accessible center stacks (no cost, no role check)."""
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        options = []
        for stack_idx, domain_stack in enumerate(self.domain_grid):
            if not domain_stack:
                continue
            top = domain_stack[-1]
            if getattr(top, "domain_id", None) is None:
                continue
            if not getattr(top, "is_accessible", False) or not getattr(top, "is_visible", True):
                continue
            options.append({
                "stack_idx": stack_idx,
                "domain_id": int(getattr(top, "domain_id", 0)),
                "name": getattr(top, "name", "Domain"),
            })
        source_name = getattr(self, "_immediate_slay_source_label", None) or "Effect"
        if not options:
            self._log_game_event(
                f"{self._player_label(player_id)} could not use \"{source_name}\" "
                f"(no domains available to take)."
            )
            return [0, 0, 0, 0]
        self.pending_required_choice = {
            "kind": "grant_domain_reward",
            "player_id": player_id,
            "source_name": source_name,
            "options": options,
        }
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_domain_reward"
        return [0, 0, 0, 0]

    def _apply_grant_domain_choice(self, player_id, stack_idx):
        """Acquire the chosen domain for free, running all the normal post-acquisition steps."""
        player = self._player_by_id(player_id)
        if not player:
            return
        domain_stacks = self.domain_grid
        if stack_idx < 0 or stack_idx >= len(domain_stacks):
            return
        domain_stack = domain_stacks[stack_idx]
        if not domain_stack:
            return
        top = domain_stack[-1]
        if getattr(top, "domain_id", None) is None:
            return
        source_name = (getattr(self, "pending_required_choice", None) or {}).get("source_name", "Effect")
        before = self._player_scores_line(player)
        acquired = domain_stack.pop(-1)
        acquired.acquired_turn_number = int(self.turn_number)
        player.owned_domains.append(acquired)
        vp_gain = int(getattr(acquired, "vp_reward", 0) or 0)
        if vp_gain:
            player.victory_score = int(getattr(player, "victory_score", 0)) + vp_gain
            self._bump_harvest_delta(player, 0, 0, 0, vp_gain)
        if not domain_stack and self.exhausted_stack:
            exhausted = self.exhausted_stack.pop()
            if isinstance(exhausted, Event):
                exhausted.toggle_visibility(True)
                exhausted.toggle_accessibility(True)
            domain_stack.append(exhausted)
            self.exhausted_count = int(self.exhausted_count) + 1
        after = self._player_scores_line(player)
        self._log_game_event(
            f"{self._player_label(player_id)} took domain \"{acquired.name}\" "
            f"via \"{source_name}\" (free); scores {before} -> {after}"
        )
        self._apply_domain_activation_effect(player, acquired)

    def _execute_build_domain_activation_payout(self, player_id):
        """Offer the active player an optional free domain build (Ararmartin Ridge)."""
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        have = self._player_citizen_role_totals(player)
        has_pratchett = self._player_has_action_effect_flag(player, "action.pratchettsplateau")
        options = []
        for stack_idx, domain_stack in enumerate(self.domain_grid):
            if not domain_stack:
                continue
            top = domain_stack[-1]
            if getattr(top, "domain_id", None) is None:
                continue
            if not getattr(top, "is_accessible", False) or not getattr(top, "is_visible", True):
                continue
            # Role requirement check (citizens only, matching build_domain logic).
            req_shadow = int(getattr(top, "shadow_count", 0) or 0)
            req_holy = int(getattr(top, "holy_count", 0) or 0)
            req_soldier = int(getattr(top, "soldier_count", 0) or 0)
            req_worker = int(getattr(top, "worker_count", 0) or 0)
            if have["shadow"] < req_shadow or have["holy"] < req_holy or \
               have["soldier"] < req_soldier or have["worker"] < req_worker:
                continue
            gold_cost = int(getattr(top, "gold_cost", 0) or 0)
            if has_pratchett:
                gold_cost = max(0, gold_cost - 1)
            if int(getattr(player, "gold_score", 0) or 0) < gold_cost:
                continue
            options.append({
                "stack_idx": stack_idx,
                "domain_id": int(getattr(top, "domain_id", 0)),
                "name": getattr(top, "name", "Domain"),
                "gold_cost": gold_cost,
            })
        if not options:
            self._log_game_event(
                f"{self._player_label(player_id)} gained +3 Gold from \"Ararmartin Ridge\" "
                f"(no affordable domains available to build)."
            )
            return [0, 0, 0, 0]
        self.pending_required_choice = {
            "kind": "domain_build_opportunity",
            "player_id": player_id,
            "options": options,
        }
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_domain_to_build"
        return [0, 0, 0, 0]

    def _execute_banish_center_payout(self, command, player_id):
        """Parse `banish_center <kind> [optional]` and prompt for a center-stack card.

        Gnoll Bonewitch-style banish removes an accessible card from the board,
        not from a player's tableau. The removed card lands in the global banish pile.
        """
        parts = (command or "").strip().split()
        if not parts or parts[0].lower() != "banish_center":
            return [-9999, 0, 0, 0]
        if len(parts) < 2:
            return [-9999, 0, 0, 0]
        kind = parts[1].lower()
        optional = any(p.lower() == "optional" for p in parts[2:])
        if kind not in ("citizen",):
            return [-9999, 0, 0, 0]
        options = []
        for i, stack in enumerate(list(getattr(self, "citizen_grid", []) or [])):
            if not stack:
                continue
            top = stack[-1]
            if not getattr(top, "is_accessible", False):
                continue
            if getattr(top, "citizen_id", None) is None:
                continue  # Event/Exhausted placeholder — not a valid citizen target
            options.append({
                "token": "citizen.center",
                "idx": i,
                "name": getattr(top, "name", "?"),
                "citizen_id": int(getattr(top, "citizen_id", -1)),
                "gold_cost": int(getattr(top, "gold_cost", 0) or 0),
            })
        if not options:
            self._log_game_event(
                f"{self._player_label(player_id)} had no center-stack {kind} to banish; effect skipped."
            )
            return [0, 0, 0, 0]
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_owned_card"
        self.pending_required_choice = {
            "kind": "banish_center_card",
            "player_id": player_id,
            "card_kind": kind,
            "options": options,
            "allow_skip": optional,
        }
        self._log_game_event(
            f"{self._player_label(player_id)} is choosing a center-stack {kind} to banish."
        )
        return [0, 0, 0, 0]

    def _banish_center_citizen(self, stack_idx):
        """Remove the accessible top citizen from a board stack and push it to the banish pile."""
        stacks = list(getattr(self, "citizen_grid", []) or [])
        if stack_idx < 0 or stack_idx >= len(stacks):
            return None
        stack = stacks[stack_idx]
        if not stack:
            return None
        citizen = stack[-1]
        if not getattr(citizen, "is_accessible", False):
            return None
        if getattr(citizen, "citizen_id", None) is None:
            return None  # Event/Exhausted placeholder — not banishable as a citizen
        banished = stack.pop(-1)
        self._citizen_set_flipped(banished, False)
        self.banish_pile.append(banished)
        self._finalize_citizen_stack_after_claiming_top(stack)
        return banished

    def _banish_center_monster(self, stack_idx):
        """Remove the top monster from a center stack and push it to the banish pile."""
        from cards import Event as _Event
        stacks = list(getattr(self, "monster_grid", []) or [])
        if stack_idx < 0 or stack_idx >= len(stacks):
            return None
        stack = stacks[stack_idx]
        if not stack:
            return None
        top = stack[-1]
        if not getattr(top, "is_accessible", False):
            return None
        if getattr(top, "monster_id", None) is None:
            return None  # Event/Exhausted placeholder — not banishable as a monster
        banished = stack.pop(-1)
        self.banish_pile.append(banished)
        if stack:
            stack[-1].toggle_accessibility(True)
        elif self.exhausted_stack:
            exhausted = self.exhausted_stack.pop()
            stack.append(exhausted)
            self.exhausted_count = int(self.exhausted_count) + 1
            if isinstance(exhausted, _Event):
                exhausted.toggle_visibility(True)
                exhausted.toggle_accessibility(True)
        return banished

    def _maybe_fire_northern_wall_banish(self, player_id):
        """If the active player owns The Northern Wall, open an optional Minion-banish prompt."""
        player = self._player_by_id(player_id)
        if not player:
            return
        if not self._player_has_action_effect_flag(player, "action.northernwall"):
            return
        options = []
        for stack_idx, stack in enumerate(getattr(self, "monster_grid", []) or []):
            if not stack:
                continue
            top = stack[-1]
            if getattr(top, "monster_id", None) is None:
                continue
            if not getattr(top, "is_accessible", False):
                continue
            if (getattr(top, "monster_type", "") or "").strip().lower() != "minion":
                continue
            options.append({
                "token": "monster.center",
                "idx": stack_idx,
                "name": getattr(top, "name", "?"),
                "monster_id": int(getattr(top, "monster_id", -1)),
                "monster_type": getattr(top, "monster_type", "?"),
            })
        if not options:
            return  # No accessible Minions; skip silently
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_owned_card"
        self.pending_required_choice = {
            "kind": "banish_roll_minion",
            "player_id": player_id,
            "options": options,
            "allow_skip": True,
        }

    def _execute_banish_owned_payout(self, command, player_id):
        """Parse `banish_owned <kind> [optional]` and open a self-target prompt.

        Grammar (positional, mirrors `return_owned` and `take_owned`):
          kind:     citizen   (future: monster, ...)
          optional: literal "optional" flag when the actor may decline

        "Banish" is a permanent removal: the chosen card leaves the player's
        tableau and lands on the global `self.banish_pile`. Distinct from
        `_citizen_set_flipped` (face-down but still on the tableau and recoverable).

        Returns [0,0,0,0] -- the banish itself grants no resources; any companion
        gains live in a sibling compound leg (e.g. `... + choose <citizens>`),
        which is chained automatically via `_set_payout_continuation`.
        """
        parts = (command or "").strip().split()
        if not parts or parts[0].lower() != "banish_owned":
            return [-9999, 0, 0, 0]
        if len(parts) < 2:
            return [-9999, 0, 0, 0]
        kind = parts[1].lower()
        optional = any(p.lower() == "optional" for p in parts[2:])
        if kind not in ("citizen",):
            return [-9999, 0, 0, 0]
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        attr = "owned_citizens"
        options = []
        for i, c in enumerate(list(getattr(player, attr, []) or [])):
            options.append({
                "token": "citizen.owned",
                "idx": i,
                "name": getattr(c, "name", "?"),
                "citizen_id": int(getattr(c, "citizen_id", -1)),
                "is_flipped": bool(getattr(c, "is_flipped", False)),
            })
        if not options:
            self._log_game_event(
                f"{self._player_label(player_id)} had no {kind} to banish; effect skipped."
            )
            return [0, 0, 0, 0]
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_owned_card"
        self.pending_required_choice = {
            "kind": "banish_owned_card",
            "player_id": player_id,
            "card_kind": kind,
            "options": options,
            "allow_skip": optional,
        }
        self._log_game_event(
            f"{self._player_label(player_id)} is choosing a {kind} to banish."
        )
        return [0, 0, 0, 0]

    def _banish_owned_citizen(self, player, src_idx):
        """Remove a citizen from `player.owned_citizens[src_idx]` and push to the global banish pile.

        Returns the banished citizen (for logging), or None on bad index.
        Caller is responsible for logging the higher-level "via <card>" context.
        """
        owned = list(getattr(player, "owned_citizens", []) or [])
        if src_idx < 0 or src_idx >= len(owned):
            return None
        citizen = owned[src_idx]
        if getattr(citizen, "is_flipped", False):
            self._citizen_set_flipped(citizen, False)
        del player.owned_citizens[src_idx]
        self.banish_pile.append(citizen)
        return citizen

    def _execute_flip_citizen_payout(self, command, player_id):
        """Parse `flip_citizen <variant> [optional]` and open the appropriate prompt.

        Variants:
          targeted   -- acting player picks one player, then one of that player's
                        unflipped tableau citizens, and flips it face-down.
                        Two-stage prompt: choose_player -> choose_owned_card.

        Trailing literal `optional` flag lets the actor skip at either stage.

        Always returns [0,0,0,0] -- the base monster rewards (vp/gold/etc.) are
        applied by the slay flow on top of zero, and the flip is a follow-up choice.
        If no eligible target exists the effect is silently lost (logged).
        """
        parts = (command or "").strip().split()
        if not parts or parts[0].lower() != "flip_citizen":
            return [-9999, 0, 0, 0]
        variant = (parts[1].lower() if len(parts) >= 2 else "")
        optional = any(p.lower() == "optional" for p in parts[2:])
        if variant != "targeted":
            return [-9999, 0, 0, 0]
        options = []
        for p in self.player_list:
            if p.player_id == player_id:
                continue
            if not self._player_is_negative_effect_target(p):
                continue
            owned = list(getattr(p, "owned_citizens", []) or [])
            if not any(not getattr(c, "is_flipped", False) for c in owned):
                continue
            options.append({
                "token": "player",
                "player_id": p.player_id,
                "name": getattr(p, "name", "?"),
            })
        if not options:
            self._log_game_event(
                f"{self._player_label(player_id)} could not flip a citizen (no eligible tableau)."
            )
            return [0, 0, 0, 0]
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_player"
        self.pending_required_choice = {
            "kind": "monster_flip_citizen_targeted",
            "player_id": player_id,
            "stage": "player",
            "options": options,
            "allow_skip": optional,
        }
        self._log_game_event(
            f"{self._player_label(player_id)} is choosing a player to flip a citizen from."
        )
        return [0, 0, 0, 0]

    def _execute_banish_player_citizen_payout(self, player_id):
        """Sunder Bay: choose a player, then banish one of their citizens permanently."""
        options = []
        for p in self.player_list:
            if p.player_id == player_id:
                continue
            if not self._player_is_negative_effect_target(p):
                continue
            owned = list(getattr(p, "owned_citizens", []) or [])
            if not owned:
                continue
            options.append({
                "token": "player",
                "player_id": p.player_id,
                "name": getattr(p, "name", "?"),
            })
        if not options:
            self._log_game_event(
                f"{self._player_label(player_id)} could not use \"Sunder Bay\" "
                f"(no opponents have citizens)."
            )
            return [0, 0, 0, 0]
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_player"
        self.pending_required_choice = {
            "kind": "banish_player_citizen",
            "player_id": player_id,
            "stage": "player",
            "item": {"domain_name": "Sunder Bay"},
            "options": options,
            "allow_skip": False,
        }
        self._log_game_event(
            f"{self._player_label(player_id)} is choosing a player to banish a citizen from (Sunder Bay)."
        )
        return [0, 0, 0, 0]

    def _execute_banish_random_player_monster_payout(self, player_id):
        """Wandering Flame: choose a player, then a random monster from their tableau is banished."""
        options = []
        for p in self.player_list:
            if p.player_id == player_id:
                continue
            if list(getattr(p, "owned_monsters", []) or []):
                options.append({
                    "token": "player",
                    "player_id": p.player_id,
                    "name": getattr(p, "name", "?"),
                })
        if not options:
            self._log_game_event(
                f"{self._player_label(player_id)} could not use \"Wandering Flame\" "
                f"(no opponents have monsters)."
            )
            return [0, 0, 0, 0]
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_player"
        self.pending_required_choice = {
            "kind": "banish_random_player_monster",
            "player_id": player_id,
            "item": {"domain_name": "Wandering Flame"},
            "explain": "A random monster from the chosen player's tableau will be permanently banished.",
            "options": options,
            "allow_skip": False,
        }
        self._log_game_event(
            f"{self._player_label(player_id)} is choosing a player to banish a random monster from (Wandering Flame)."
        )
        return [0, 0, 0, 0]

    def _execute_compound_payout(
        self,
        compound_command,
        player_id,
        auto_apply_single_choice=True,
        balance_hint=None,
        suppress_exchange_optional_prompt=False,
    ):
        """
        Execute multiple commands separated by +.
        e.g. "s 3 + choose <citizens where role==soldier and gold_cost<=2>"
        Non-choice commands are executed immediately and return [result].
        Choice commands set action_required and return [0,0,0,0].
        balance_hint: optional dict g,s,m,v carried across segments so exchange affordability sees prior legs.

        If a leg opens a blocking prompt, any later legs are stashed via
        `_set_payout_continuation` so they resume after the prompt resolves. The
        prompt handler is responsible for calling `_resume_payout_continuation`
        once it has applied the choice and cleared `action_required`.
        """
        parts = [p.strip() for p in (compound_command or "").split(" + ")]
        if not parts:
            return [0, 0, 0, 0]
        total_payout = [0, 0, 0, 0]
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        prior_action = (self.action_required or {}).get("action", "")
        prior_concurrent = getattr(self, "concurrent_action", None)
        bal = dict(balance_hint) if balance_hint is not None else _player_resource_balances(player)
        if not bal:
            return [-9999, 0, 0, 0]
        for i, cmd in enumerate(parts):
            if not cmd:
                continue
            payout = self.execute_special_payout(
                cmd,
                player_id,
                auto_apply_single_choice=auto_apply_single_choice,
                balance_hint=bal,
                suppress_exchange_optional_prompt=suppress_exchange_optional_prompt,
            )
            new_action = (self.action_required or {}).get("action", "")
            new_concurrent = getattr(self, "concurrent_action", None)
            if (new_action and new_action != prior_action) or (new_concurrent is not prior_concurrent):
                remaining = [p for p in parts[i + 1:] if p]
                if remaining:
                    self._set_payout_continuation(player_id, remaining, balance_hint=bal)
                return total_payout
            if isinstance(payout, list) and len(payout) >= 4:
                if payout[0] == -9999:
                    prior_empty = (
                        total_payout[0] == 0 and total_payout[1] == 0
                        and total_payout[2] == 0 and total_payout[3] == 0
                    )
                    if prior_empty:
                        return payout
                    return total_payout
                bal["g"] = int(bal["g"]) + int(payout[0])
                bal["s"] = int(bal["s"]) + int(payout[1])
                bal["m"] = int(bal["m"]) + int(payout[2])
                bal["v"] = int(bal["v"]) + int(payout[3])
                total_payout[0] += payout[0]
                total_payout[1] += payout[1]
                total_payout[2] += payout[2]
                total_payout[3] += payout[3]
        return total_payout

    def _tokenize_payout(self, s):
        """Whitespace-split a payout command, respecting double-quoted multi-word tokens.

        Used by `count area "<multi word area>" <res> <mult>` and any future verb
        whose positional args may contain spaces (e.g. citizen-name filters that
        embed a space-bearing card name).

        Example:
          `count area "Undead Samurai" m 1` -> ['count', 'area', 'Undead Samurai', 'm', '1']
          `count area Gnolls g 1`           -> ['count', 'area', 'Gnolls', 'g', '1']
        Quotes are stripped from yielded tokens. Backslash escapes are not supported
        (payout strings never need them); an unterminated quote captures the rest
        of the input.
        """
        s = s or ""
        out = []
        i = 0
        n = len(s)
        while i < n:
            while i < n and s[i].isspace():
                i += 1
            if i >= n:
                break
            if s[i] == '"':
                j = s.find('"', i + 1)
                if j == -1:
                    out.append(s[i + 1:])
                    return out
                out.append(s[i + 1:j])
                i = j + 1
                continue
            j = i
            while j < n and not s[j].isspace():
                j += 1
            out.append(s[i:j])
            i = j
        return out

    def _emit_payout_token(self, tok):
        """Inverse of `_tokenize_payout` for a single token: quote it if it contains whitespace.

        Used by `_normalize_choose_command` so re-emitted normalized strings stay
        round-trip-safe (e.g. an area "Undead Samurai" comes back out as the
        quoted form, not as two bare tokens).
        """
        t = "" if tok is None else str(tok)
        if not t:
            return '""'
        if any(ch.isspace() for ch in t):
            return f'"{t}"'
        return t

    def _set_payout_continuation(self, player_id, parts, balance_hint=None):
        """Stash remaining compound-payout legs (post-prompt). Cleared by `_resume_payout_continuation`."""
        if not parts:
            self.pending_payout_continuation = None
            return
        self.pending_payout_continuation = {
            "player_id": player_id,
            "parts": list(parts),
            "balance_hint": dict(balance_hint) if balance_hint else None,
        }

    def _resume_payout_continuation(self):
        """Drain whatever compound legs were stashed when a prompt opened.

        Called by prompt handlers after they clear `action_required` and
        `pending_required_choice`. Any leg that itself opens another prompt
        will re-stash whatever still remains, so chains of 3+ blocking legs
        work without special-casing.

        Immediate (non-blocking) payouts from the remaining legs are applied to
        the player's score here, mirroring what `slay_monster` / the activation
        flow would have done if the legs had executed inline.
        """
        cont = getattr(self, "pending_payout_continuation", None)
        if not cont:
            return
        self.pending_payout_continuation = None
        player_id = cont.get("player_id")
        parts = [p for p in (cont.get("parts") or []) if p]
        if not parts or not player_id:
            return
        balance_hint = cont.get("balance_hint")
        if len(parts) == 1:
            payout = self.execute_special_payout(parts[0], player_id, balance_hint=balance_hint)
        else:
            payout = self._execute_compound_payout(" + ".join(parts), player_id, balance_hint=balance_hint)
        if not (isinstance(payout, list) and len(payout) >= 4):
            return
        if payout[0] == -9999:
            return
        if payout[0] == 0 and payout[1] == 0 and payout[2] == 0 and payout[3] == 0:
            return
        player = self._player_by_id(player_id)
        if not player:
            return
        player.gold_score = int(player.gold_score) + payout[0]
        player.strength_score = int(player.strength_score) + payout[1]
        player.magic_score = int(player.magic_score) + payout[2]
        player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
        self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])

    def execute_special_payout(
        self,
        command,
        player_id,
        auto_apply_single_choice=True,
        balance_hint=None,
        suppress_exchange_optional_prompt=False,
    ):
        print("executing special payout")
        raw = (command or "").strip()
        low = raw.lower()
        if low.startswith("manipulate_resources"):
            return self._execute_manipulate_resources_payout(raw, player_id)
        if low == "slay":
            return self._execute_slay_payout(player_id)
        if low.startswith("steal"):
            return self._execute_steal_payout(raw, player_id)
        if low.startswith("take_owned"):
            return self._execute_take_owned_payout(raw, player_id)
        if low == "<domains>" or low.startswith("<domains"):
            return self._execute_grant_domain_payout(player_id)
        if low == "build_domain":
            return self._execute_build_domain_activation_payout(player_id)
        if low == "concurrent_flip_one_citizen":
            self._begin_concurrent_flip_one_citizen(player_id)
            return [0, 0, 0, 0]
        if " + " in raw and not raw.startswith("choose"):
            return self._execute_compound_payout(
                raw,
                player_id,
                auto_apply_single_choice=auto_apply_single_choice,
                balance_hint=balance_hint,
                suppress_exchange_optional_prompt=suppress_exchange_optional_prompt,
            )
        if low.startswith("flip_citizen"):
            return self._execute_flip_citizen_payout(raw, player_id)
        if low == "banish_player_citizen":
            return self._execute_banish_player_citizen_payout(player_id)
        if low == "banish_random_player_monster":
            return self._execute_banish_random_player_monster_payout(player_id)
        if low.startswith("banish_center"):
            return self._execute_banish_center_payout(raw, player_id)
        if low.startswith("banish_owned"):
            return self._execute_banish_owned_payout(raw, player_id)
        payout = [0, 0, 0, 0]  # gp, sp, mp, vp, todo: citizen, monster, domain
        split_command = self._tokenize_payout(command or "")
        if not split_command:
            payout[0] = -9999
            return payout
        # Ensure safe indexing even for short commands.
        split_command = split_command + ["", "", "", "", "", "", "", ""]
        first_word = split_command[0]
        second_word = split_command[1]
        third_word = split_command[2]
        fourth_word = split_command[3]
        if first_word in ("g", "s", "m", "v"):
            try:
                amount = int(second_word)
                if first_word == "g":
                    payout[0] = amount
                elif first_word == "s":
                    payout[1] = amount
                elif first_word == "m":
                    payout[2] = amount
                elif first_word == "v":
                    payout[3] = amount
                print(payout)
                return payout
            except (TypeError, ValueError):
                payout[0] = -9999
                return payout
        match first_word:
            case "count":
                match second_word:
                    case "owned_shadow":
                        self.update_payout_for_role('shadow_count', player_id, payout, split_command)
                    case "owned_holy":
                        self.update_payout_for_role('holy_count', player_id, payout, split_command)
                    case "owned_soldier":
                        self.update_payout_for_role('soldier_count', player_id, payout, split_command)
                    case "owned_worker":
                        self.update_payout_for_role('worker_count', player_id, payout, split_command)
                    case "owned_monsters":
                        self.update_payout_for_role('owned_monsters', player_id, payout, split_command)
                    case "owned_citizens":
                        self.update_payout_for_role('owned_citizens', player_id, payout, split_command)
                    case "owned_domains":
                        self.update_payout_for_role('owned_domains', player_id, payout, split_command)
                    case "owned_citizen_name":
                        # count owned_citizen_name NAME R N
                        # third_word = citizen name, fourth_word = resource, split_command[4] = multiplier
                        want = third_word.strip().lower()
                        player_cn = self._player_by_id(player_id)
                        if not player_cn or not want:
                            payout[0] = -9999
                        else:
                            n = sum(
                                1 for c in list(getattr(player_cn, "owned_citizens", []) or [])
                                if not getattr(c, "is_flipped", False)
                                and (getattr(c, "name", "") or "").strip().lower() == want
                            )
                            try:
                                mult = int(split_command[4])
                            except (TypeError, ValueError):
                                payout[0] = -9999
                                mult = None
                            if mult is not None:
                                match fourth_word:
                                    case 'g':
                                        payout[0] = n * mult
                                    case 's':
                                        payout[1] = n * mult
                                    case 'm':
                                        payout[2] = n * mult
                                    case 'v':
                                        payout[3] = n * mult
                                    case _:
                                        payout[0] = -9999
                    case "owned_starter_name":
                        # count owned_starter_name NAME R N
                        want = third_word.strip().lower()
                        player_sn = self._player_by_id(player_id)
                        if not player_sn or not want:
                            payout[0] = -9999
                        else:
                            n = sum(
                                1 for s in list(getattr(player_sn, "owned_starters", []) or [])
                                if not getattr(s, "is_flipped", False)
                                and (getattr(s, "name", "") or "").strip().lower() == want
                            )
                            try:
                                mult = int(split_command[4])
                            except (TypeError, ValueError):
                                payout[0] = -9999
                                mult = None
                            if mult is not None:
                                match fourth_word:
                                    case 'g':
                                        payout[0] = n * mult
                                    case 's':
                                        payout[1] = n * mult
                                    case 'm':
                                        payout[2] = n * mult
                                    case 'v':
                                        payout[3] = n * mult
                                    case _:
                                        payout[0] = -9999
                    case "area":
                        area_count = int(
                            (self.owned_monster_attributes(player_id) or {}).get(third_word, 0) or 0
                        )
                        match fourth_word:
                            case 'g':
                                payout[0] = area_count * int(split_command[4])
                            case 's':
                                payout[1] = area_count * int(split_command[4])
                            case 'm':
                                payout[2] = area_count * int(split_command[4])
                            case 'v':
                                payout[3] = area_count * int(split_command[4])
                            case _:
                                payout[0] = -9999
                    case _:
                        payout[0] = -9999
            case "exchange":
                if second_word == "wild":
                    return self._execute_wild_cost_exchange_payout(raw, player_id)
                if fourth_word == "wild":
                    return self._execute_wild_gain_exchange_payout(raw, player_id)
                player_x = self._player_by_id(player_id)
                if not player_x:
                    payout[0] = -9999
                    print(payout)
                    return payout
                match second_word:
                    case 'g':
                        payout[0] = payout[0] - int(third_word)
                    case 's':
                        payout[1] = payout[1] - int(third_word)
                    case 'm':
                        payout[2] = payout[2] - int(third_word)
                    case 'v':
                        payout[3] = payout[3] - int(third_word)
                    case _:
                        payout[0] = -9999
                match fourth_word:
                    case 'g':
                        payout[0] = payout[0] + int(split_command[4])
                    case 's':
                        payout[1] = payout[1] + int(split_command[4])
                    case 'm':
                        payout[2] = payout[2] + int(split_command[4])
                    case 'v':
                        payout[3] = payout[3] + int(split_command[4])
                    case _:
                        payout[0] = -9999
                if payout[0] == -9999:
                    print(payout)
                    return payout
                bal_x = balance_hint if balance_hint is not None else _player_resource_balances(player_x)
                if not _balances_allow_payout(bal_x, payout):
                    return [0, 0, 0, 0]
                if (
                    not suppress_exchange_optional_prompt
                    and balance_hint is None
                    and self._want_harvest_optional_exchange_prompt(raw)
                ):
                    self.pending_required_choice = {
                        "kind": "harvest_optional_exchange",
                        "player_id": player_id,
                        "command": raw,
                    }
                    self.action_required["id"] = player_id
                    self.action_required["action"] = "harvest_optional_exchange"
                    return [0, 0, 0, 0]
                print(payout)
                return payout
            case "choose":
                normalized, options = self._normalize_choose_command(command)
                options = self._filter_unavailable_choose_options(options)
                if not options:
                    payout[0] = -9999
                    return payout
                prompt_options = self._expand_choose_options_for_prompt(options)
                if not prompt_options:
                    payout[0] = -9999
                    return payout
                if auto_apply_single_choice and len(prompt_options) == 1:
                    ok = self._apply_choose_option(player_id, prompt_options[0])
                    if not ok:
                        payout[0] = -9999
                    return payout
                self.action_required["id"] = player_id
                self.action_required["action"] = normalized
                self.pending_required_choice = {
                    "kind": "special_payout_choose",
                    "player_id": player_id,
                    "command": normalized,
                    "options": prompt_options,
                }
            case _:
                payout[0] = -9999
        print(payout)
        return payout

    def _normalize_choose_command(self, command):
        """
        Normalize a "choose" special payout into a canonical string + parsed options.

        Supported input formats:
        - "choose g 2 m 2"
        - "choose g 3 <citizens where name==Knight>"
        - "choose <citizens where gold_cost<=2>"
        - "choose <count area Forest g 2> <citizens + v 1>"
        - "choose <count area \"Undead Samurai\" m 1>"   # multi-word area, double-quoted
        Returns:
        - (normalized_command: str, options: list[dict{token, amount}])
        """
        raw = (command or "").strip()
        if not raw.lower().startswith("choose"):
            return (command or ""), []
        rest = raw[6:].strip()
        options = []
        i = 0
        n = len(rest)
        while i < n:
            while i < n and rest[i].isspace():
                i += 1
            if i >= n:
                break
            if rest[i] == "<":
                j = rest.find(">", i + 1)
                if j == -1:
                    return (command or ""), []
                inner = rest[i + 1:j].strip()
                parsed_inner = self._parse_choose_inner_option(inner)
                if parsed_inner is None:
                    return (command or ""), []
                options.append(parsed_inner)
                i = j + 1
                continue
            j = i
            while j < n and not rest[j].isspace():
                j += 1
            tok = rest[i:j].strip().lower()
            i = j
            while i < n and rest[i].isspace():
                i += 1
            k = i
            while k < n and not rest[k].isspace():
                k += 1
            amt_s = rest[i:k].strip()
            try:
                amt = int(amt_s)
            except (TypeError, ValueError):
                return (command or ""), []
            if tok not in ("g", "s", "m", "v") or amt <= 0:
                return (command or ""), []
            options.append({"token": tok, "amount": amt})
            i = k
        if not options:
            return (command or ""), []
        norm_parts = []
        for o in options:
            if o["token"] in ("g", "s", "m", "v"):
                norm_parts.append(f"{o['token']} {o['amount']}")
            elif o["token"] == "count_area":
                area_tok = self._emit_payout_token(o.get('area'))
                norm_parts.append(f"<count area {area_tok} {o.get('resource')} {o.get('mult')}>")
            elif o["token"] == "citizens_where":
                spec = o.get("spec", {})
                extras = o.get("extras") or []
                extra_str = ""
                if extras:
                    extra_str = " + " + " + ".join([f"{e['token']} {e['amount']}" for e in extras])
                if spec.get("is_any"):
                    norm_parts.append(f"<citizens{extra_str}>")
                elif spec.get("clauses"):
                    clause_parts = []
                    for clause in list(spec.get("clauses") or []):
                        clause_parts.append(
                            f"{clause.get('field')} {clause.get('op')} {clause.get('value')}"
                        )
                    norm_parts.append(f"<citizens where {' and '.join(clause_parts)}{extra_str}>")
                else:
                    norm_parts.append(
                        f"<citizens where {spec.get('field')} {spec.get('op')} {spec.get('value')}{extra_str}>"
                    )
            else:
                return (command or ""), []
        normalized = "choose " + " ".join(norm_parts)
        return normalized, options

    def _parse_choose_inner_option(self, inner):
        s = (inner or "").strip()
        if not s:
            return None
        parts = self._tokenize_payout(s)
        if len(parts) >= 5 and parts[0].lower() == "count" and parts[1].lower() == "area":
            area = parts[2]
            resource = parts[3].lower()
            try:
                mult = int(parts[4])
            except (TypeError, ValueError):
                return None
            if mult <= 0 or resource not in ("g", "s", "m", "v"):
                return None
            if area not in self._active_areas():
                return None
            return {"token": "count_area", "area": area, "resource": resource, "mult": mult, "amount": 1}
        return self._parse_citizens_inner_option(s)

    def _parse_citizens_inner_option(self, inner):
        clauses = [c.strip() for c in (inner or "").split("+")]
        if not clauses:
            return None
        base = clauses[0]
        spec = self._parse_boutique_citizen_where(base)
        if spec is None:
            return None
        extras = []
        for c in clauses[1:]:
            p = c.split()
            if len(p) != 2:
                return None
            tok = p[0].strip().lower()
            try:
                amt = int(p[1])
            except (TypeError, ValueError):
                return None
            if tok not in ("g", "s", "m", "v") or amt <= 0:
                return None
            extras.append({"token": tok, "amount": amt})
        return {"token": "citizens_where", "amount": 1, "spec": spec, "extras": extras}

    def _parse_boutique_citizen_where(self, inner):
        parts = (inner or "").strip().split()
        if len(parts) == 1 and parts[0].lower() == "citizens":
            return {"pool": "citizens", "field": "gold_cost", "op": ">=", "value": "0", "is_any": True}
        if len(parts) < 3:
            return None
        if parts[0].lower() != "citizens" or parts[1].lower() != "where":
            return None
        predicate = " ".join(parts[2:]).strip()
        clauses = [c.strip() for c in predicate.split(" and ") if c.strip()]
        if not clauses:
            return None
        parsed_clauses = []
        for clause in clauses:
            field = op = value = None
            for candidate_op in ("<=", ">=", "==", "=", "<", ">"):
                if candidate_op in clause:
                    left, right = clause.split(candidate_op, 1)
                    field = (left or "").strip().lower()
                    op = "==" if candidate_op == "=" else candidate_op
                    value = (right or "").strip()
                    break
            if not field or not op or value == "":
                return None
            if field not in ("gold_cost", "name", "shadow_count", "holy_count", "soldier_count", "worker_count", "role"):
                return None
            if field == "name":
                if op != "==":
                    return None
                parsed_clauses.append({"field": field, "op": op, "value": value})
            elif field == "role":
                if op != "==":
                    return None
                if value.lower() not in ("shadow", "holy", "soldier", "worker"):
                    return None
                parsed_clauses.append({"field": field, "op": op, "value": value.lower()})
            else:
                try:
                    int(value)
                except (TypeError, ValueError):
                    return None
                parsed_clauses.append({"field": field, "op": op, "value": value})
        return {"pool": "citizens", "clauses": parsed_clauses, "is_any": False}

    def _citizen_matches_clause(self, citizen, clause):
        field = (clause.get("field") or "").strip().lower()
        op = (clause.get("op") or "").strip()
        value = clause.get("value")
        if field == "name":
            if op != "==":
                return False
            card_name = (getattr(citizen, "name", "") or "").strip().lower()
            cmp_name = (value or "").strip().lower().strip("\"'")
            return card_name == cmp_name
        if field == "role":
            role = (value or "").strip().lower()
            if role == "shadow":
                return int(getattr(citizen, "shadow_count", 0) or 0) > 0
            if role == "holy":
                return int(getattr(citizen, "holy_count", 0) or 0) > 0
            if role == "soldier":
                return int(getattr(citizen, "soldier_count", 0) or 0) > 0
            if role == "worker":
                return int(getattr(citizen, "worker_count", 0) or 0) > 0
            return False
        try:
            card_v = int(getattr(citizen, field, 0) or 0)
            cmp_v = int(value)
        except (TypeError, ValueError):
            return False
        if op == "==":
            return card_v == cmp_v
        if op == "<=":
            return card_v <= cmp_v
        if op == ">=":
            return card_v >= cmp_v
        if op == "<":
            return card_v < cmp_v
        if op == ">":
            return card_v > cmp_v
        return False

    def _citizen_matches_filter(self, citizen, spec):
        if not isinstance(spec, dict):
            return False
        if spec.get("is_any"):
            return True
        clauses = spec.get("clauses")
        if clauses:
            return all(self._citizen_matches_clause(citizen, clause) for clause in clauses)
        field = (spec.get("field") or "").strip().lower()
        op = (spec.get("op") or "").strip()
        value = spec.get("value")
        if field == "name":
            card_name = (getattr(citizen, "name", "") or "").strip().lower()
            cmp_name = (value or "").strip().lower().strip("\"'")
            if op != "==":
                return False
            return card_name == cmp_name
        try:
            card_v = int(getattr(citizen, field, 0) or 0)
            cmp_v = int(value)
        except (TypeError, ValueError):
            return False
        if op == "==":
            return card_v == cmp_v
        if op == "<=":
            return card_v <= cmp_v
        if op == ">=":
            return card_v >= cmp_v
        if op == "<":
            return card_v < cmp_v
        if op == ">":
            return card_v > cmp_v
        return False

    def _board_citizen_candidates(self, spec):
        out = []
        for stack in self.citizen_grid:
            if not stack:
                continue
            top = stack[-1]
            if not getattr(top, "is_accessible", False):
                continue
            # Skip Event/Exhausted placeholders that may occupy citizen slots.
            if getattr(top, "citizen_id", None) is None:
                continue
            if self._citizen_matches_filter(top, spec):
                out.append(top)
        return out

    def _player_can_afford_self_convert_resources(self, player, pay_k, pay_n):
        if pay_k == "g":
            return int(getattr(player, "gold_score", 0) or 0) >= pay_n
        if pay_k == "s":
            return int(getattr(player, "strength_score", 0) or 0) >= pay_n
        if pay_k == "m":
            return int(getattr(player, "magic_score", 0) or 0) >= pay_n
        if pay_k == "v":
            return int(getattr(player, "victory_score", 0) or 0) >= pay_n
        return False

    def _apply_self_convert_kv_to_player(self, player, kv):
        pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
        gain_k, gain_n = _parse_resource_kv(kv.get("gain", ""))
        idx = {"g": 0, "s": 1, "m": 2, "v": 3}
        pi, gi = idx[pay_k], idx[gain_k]
        payout = [0, 0, 0, 0]
        payout[pi] -= pay_n
        payout[gi] += gain_n
        player.gold_score = int(player.gold_score) + payout[0]
        player.strength_score = int(player.strength_score) + payout[1]
        player.magic_score = int(player.magic_score) + payout[2]
        player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
        self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])

    # ----------------------------------------------------------------------
    # Immediate "may slay a Monster" prompt
    #
    # A bare-verb `slay` payout in a card effect string means: the controlling
    # player may immediately slay one accessible monster (paying its normal
    # strength/magic cost). It replaces the older `grant_action slay` mechanic
    # of accruing a free-slay action token to spend later.
    #
    # The prompt has two stages on `pending_required_choice`:
    #   - stage "pick_monster": present every accessible monster top + a Pass.
    #     `action_required.action = "choose_monster_slay"`.
    #   - stage "pay_for_slay": after a monster is picked, collect the slay
    #     payment (gold only when an event added it; strength/magic per
    #     `_validate_monster_slay_payment`).
    #     `action_required.action = "slay_monster_payment"`.
    #
    # `resume_kind` distinguishes follow-up resolution:
    #   - "domain_activation": resume via `_resume_after_domain_activation_follow_up`.
    #   - "harvest_pending_slay": resume the deferred-slay drain at end of harvest.
    # ----------------------------------------------------------------------

    def _immediate_slay_monster_options(self):
        """Return option dicts for every accessible monster top across the grid.

        Includes Event cards with is_monster=True that are occupying monster_grid
        slots — they use event_id instead of monster_id in the option dict.
        """
        options = []
        for stack in self.monster_grid:
            if not stack:
                continue
            top = stack[-1]
            if not getattr(top, "is_accessible", False):
                continue
            eid = getattr(top, "event_id", None)
            if eid is not None:
                # Event occupying a monster slot — only include if it acts as a monster.
                if not getattr(top, "is_monster", False):
                    continue
                options.append({
                    "event_id": int(eid),
                    "name": getattr(top, "name", "?"),
                    "area": "",
                    "gold_cost": int(getattr(top, "extra_gold_cost", 0) or 0),
                    "strength_cost": (
                        int(getattr(top, "strength_cost", 0) or 0)
                        + int(getattr(top, "extra_strength_cost", 0) or 0)
                    ),
                    "magic_cost": (
                        int(getattr(top, "magic_cost", 0) or 0)
                        + int(getattr(top, "extra_magic_cost", 0) or 0)
                    ),
                })
                continue
            mid = int(getattr(top, "monster_id", -1))
            if mid < 0:
                continue
            options.append({
                "monster_id": mid,
                "name": getattr(top, "name", "?"),
                "area": getattr(top, "area", ""),
                "gold_cost": int(getattr(top, "extra_gold_cost", 0) or 0),
                "strength_cost": (
                    int(getattr(top, "strength_cost", 0) or 0)
                    + int(getattr(top, "extra_strength_cost", 0) or 0)
                ),
                "magic_cost": (
                    int(getattr(top, "magic_cost", 0) or 0)
                    + int(getattr(top, "extra_magic_cost", 0) or 0)
                ),
            })
        return options

    def _open_immediate_slay_prompt(self, player_id, source_label, resume_kind="domain_activation"):
        """Open the pick_monster stage of the may-slay prompt.

        If no monster is accessible the prompt is skipped (and the appropriate
        resume kind fires immediately) so the activating player isn't stuck
        on a no-op blocker.
        """
        source_label = (source_label or "Effect").strip() or "Effect"
        options = self._immediate_slay_monster_options()
        if not options:
            self._log_game_event(
                f"{self._player_label(player_id)} could not use \"{source_label}\" "
                f"(no accessible monsters to slay)."
            )
            self._resume_after_immediate_slay(resume_kind)
            return
        self.action_required["id"] = player_id
        self.action_required["action"] = "choose_monster_slay"
        self.pending_required_choice = {
            "kind": "immediate_slay",
            "stage": "pick_monster",
            "player_id": player_id,
            "source_label": source_label,
            "resume_kind": resume_kind,
            "options": options,
            "allow_skip": True,
        }
        self._log_game_event(
            f"{self._player_label(player_id)} may slay a monster (\"{source_label}\")."
        )

    def _enter_slay_payment_stage(self, prc, chosen):
        """Transition the may-slay prompt from pick_monster to pay_for_slay."""
        player_id = prc.get("player_id")
        stage = {
            "kind": "immediate_slay",
            "stage": "pay_for_slay",
            "player_id": player_id,
            "source_label": prc.get("source_label", "Effect"),
            "resume_kind": prc.get("resume_kind", "domain_activation"),
            "monster_name": chosen.get("name", "?"),
            "area": chosen.get("area", ""),
            "gold_cost": int(chosen.get("gold_cost", 0) or 0),
            "strength_cost": int(chosen.get("strength_cost", 0) or 0),
            "magic_cost": int(chosen.get("magic_cost", 0) or 0),
            "options": list(prc.get("options") or []),
        }
        # Carry the right id depending on whether this is a regular monster or an Event.
        if chosen.get("event_id") is not None:
            stage["event_id"] = int(chosen["event_id"])
        else:
            stage["monster_id"] = int(chosen.get("monster_id", -1))
        self.pending_required_choice = stage
        self.action_required["id"] = player_id
        self.action_required["action"] = "slay_monster_payment"

    def _resume_after_immediate_slay(self, resume_kind):
        """Continue the engine after the may-slay prompt resolves (slay or pass)."""
        if resume_kind == "harvest_pending_slay":
            self._drain_pending_harvest_slays()
            return
        # Default: domain activation follow-up (existing behaviour).
        self._resume_after_domain_activation_follow_up()

    def _execute_slay_payout(self, player_id):
        """Bare-verb `slay` payout. Either prompts now (action phase) or queues for harvest end."""
        if getattr(self, "phase", None) == "harvest":
            label = getattr(self, "_immediate_slay_source_label", None) or "Effect"
            self.pending_harvest_slays.append({
                "player_id": player_id,
                "source_label": label,
            })
            return [0, 0, 0, 0]
        label = getattr(self, "_immediate_slay_source_label", None) or "Effect"
        self._open_immediate_slay_prompt(player_id, label, resume_kind="domain_activation")
        return [0, 0, 0, 0]

    def _drain_pending_harvest_slays(self):
        """Open a may-slay prompt for the next pending harvest slay, or finish harvest.

        Called after the regular harvest scan completes and after each pending
        slay resolves. Once the queue is empty we finish harvest the same way
        `_harvest_run_automation_until_blocked` would have.
        """
        # Clean up any prompt residue from the just-resolved entry.
        if isinstance(self.action_required, dict):
            aa = str(self.action_required.get("action", "") or "")
            if aa in ("choose_monster_slay", "slay_monster_payment"):
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
        self.pending_required_choice = None
        while self.pending_harvest_slays:
            entry = self.pending_harvest_slays[0]
            pid = entry.get("player_id")
            label = entry.get("source_label", "Effect")
            options = self._immediate_slay_monster_options()
            if not options:
                self._log_game_event(
                    f"{self._player_label(pid)} could not use \"{label}\" "
                    f"(no accessible monsters to slay)."
                )
                self.pending_harvest_slays.pop(0)
                continue
            # Pop now so the prompt resolution doesn't double-drain.
            self.pending_harvest_slays.pop(0)
            self._open_immediate_slay_prompt(pid, label, resume_kind="harvest_pending_slay")
            return
        # Queue empty: complete harvest normally.
        if getattr(self, "phase", None) == "harvest" and not getattr(self, "harvest_processed", False):
            self._harvest_complete_finalize()

    def _resume_after_domain_activation_follow_up(self):
        """Clear optional domain activation prompts and restore action/end-turn resolution."""
        self.pending_required_choice = None
        if getattr(self, "phase", None) == "action" and int(getattr(self, "actions_remaining", 0) or 0) > 0:
            self.action_required["id"] = self.current_player_id()
            self.action_required["action"] = "standard_action"
            return
        self.action_required["id"] = self.game_id
        self.action_required["action"] = ""
        if getattr(self, "phase", None) == "action" and int(getattr(self, "actions_remaining", 0) or 0) == 0:
            if self._start_action_end_domain_sequence(self.current_player_id()):
                return

    def _prompt_or_apply_self_convert(self, raw, player, domain=None, context="domain_activation"):
        """
        Activation self_convert: optional effects prompt confirm/decline when affordable.
        Non-optional applies immediately when affordable.

        `context` is stored in pending_required_choice so the resolution handler
        knows how to resume after the player confirms or skips:
          "domain_activation"  — default; calls _resume_after_domain_activation_follow_up
          "action_end_queue"   — pops the queue item and drains the next entry
        """
        payout = [0, 0, 0, 0]
        kv = _parse_domain_effect_kv(raw)
        if (kv.get("mode") or "").strip().lower() != "self_convert":
            payout[0] = -9999
            return payout
        optional = str(kv.get("optional", "")).strip().lower() in ("true", "1", "yes")
        pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
        gain_k, gain_n = _parse_resource_kv(kv.get("gain", ""))
        if not player or not pay_k or not gain_k or pay_n <= 0 or gain_n <= 0:
            payout[0] = -9999
            return payout
        can_pay = self._player_can_afford_self_convert_resources(player, pay_k, pay_n)
        if optional:
            if not can_pay:
                return [0, 0, 0, 0]
            domain_name = "Domain"
            if domain is not None:
                domain_name = getattr(domain, "name", None) or domain_name
            self.action_required["id"] = player.player_id
            self.action_required["action"] = "domain_self_convert"
            self.pending_required_choice = {
                "kind": "domain_self_convert",
                "player_id": player.player_id,
                "kv": kv,
                "domain_name": domain_name,
                "context": context,
            }
            return [0, 0, 0, 0]
        if not can_pay:
            return [-9999, 0, 0, 0]
        idx = {"g": 0, "s": 1, "m": 2, "v": 3}
        pi, gi = idx[pay_k], idx[gain_k]
        payout[pi] -= pay_n
        payout[gi] += gain_n
        return payout

    def _execute_manipulate_resources_self_convert_payout(self, raw, player_id):
        """Activation / compound payout fragment: bank trade (e.g. Wisborg)."""
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        return self._prompt_or_apply_self_convert(raw, player, None)

    def _execute_manipulate_resources_gain_payout(self, raw, player_id):
        """Activation / compound payout fragment: simple bank gain (mode=gain gain=<r>:<n>)."""
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        kv = _parse_domain_effect_kv(raw)
        if (kv.get("mode") or "").strip().lower() != "gain":
            return [-9999, 0, 0, 0]
        gain_k, gain_n = _parse_resource_kv(kv.get("gain", ""))
        if not gain_k or gain_n <= 0:
            return [-9999, 0, 0, 0]
        idx = {"g": 0, "s": 1, "m": 2, "v": 3}
        payout = [0, 0, 0, 0]
        payout[idx[gain_k]] += gain_n
        return payout

    def _execute_manipulate_resources_payout(self, raw, player_id):
        """Dispatch a manipulate_resources payout fragment by mode."""
        kv = _parse_domain_effect_kv(raw)
        mode = (kv.get("mode") or "").strip().lower()
        if mode == "gain":
            return self._execute_manipulate_resources_gain_payout(raw, player_id)
        return self._execute_manipulate_resources_self_convert_payout(raw, player_id)

    def _player_resource_tuple(self, player):
        return (
            int(getattr(player, "gold_score", 0) or 0),
            int(getattr(player, "strength_score", 0) or 0),
            int(getattr(player, "magic_score", 0) or 0),
            int(getattr(player, "victory_score", 0) or 0),
        )

    def _transfer_resources_player_to_player(self, from_player, to_player, dg, ds, dm, dv):
        fg, fs, fm, fv = self._player_resource_tuple(from_player)
        if dg > fg or ds > fs or dm > fm or dv > fv:
            return False
        from_player.gold_score = fg - dg
        from_player.strength_score = fs - ds
        from_player.magic_score = fm - dm
        from_player.victory_score = fv - dv
        tg, ts, tm, tv = self._player_resource_tuple(to_player)
        to_player.gold_score = tg + dg
        to_player.strength_score = ts + ds
        to_player.magic_score = tm + dm
        to_player.victory_score = tv + dv
        return True

    def _bank_gain_for_active(self, player, gain_k, gain_n):
        if gain_k == "g":
            player.gold_score = int(player.gold_score) + gain_n
            self._bump_harvest_delta(player, gain_n, 0, 0, 0)
        elif gain_k == "s":
            player.strength_score = int(player.strength_score) + gain_n
            self._bump_harvest_delta(player, 0, gain_n, 0, 0)
        elif gain_k == "m":
            player.magic_score = int(player.magic_score) + gain_n
            self._bump_harvest_delta(player, 0, 0, gain_n, 0)
        elif gain_k == "v":
            player.victory_score = int(getattr(player, "victory_score", 0)) + gain_n
            self._bump_harvest_delta(player, 0, 0, 0, gain_n)

    def _parse_manipulate_action_end(self, passive_text):
        s = (passive_text or "").strip()
        low = s.lower()
        if not low.startswith("action.end"):
            return None
        rest = s[len("action.end"):].strip()
        if not rest.lower().startswith("manipulate_resources"):
            return None
        return _parse_domain_effect_kv(rest)

    def _parse_manipulate_action_start(self, passive_text):
        s = (passive_text or "").strip()
        low = s.lower()
        if not low.startswith("action.start"):
            return None
        rest = s[len("action.start"):].strip()
        if not rest.lower().startswith("manipulate_resources"):
            return None
        return _parse_domain_effect_kv(rest)

    def _apply_manipulate_gain(self, player, kv, source_label="Domain"):
        """Apply a 'mode=gain' bank gain to the player and log the score delta."""
        if not player:
            return False
        gain_k, gain_n = _parse_resource_kv(kv.get("gain", ""))
        if not gain_k or gain_n <= 0:
            return False
        before = self._player_scores_line(player)
        self._bank_gain_for_active(player, gain_k, gain_n)
        after = self._player_scores_line(player)
        if before != after:
            self._log_game_event(
                f"{self._player_label(player.player_id)} \"{source_label}\" gain; scores {before} -> {after}"
            )
        return True

    def _apply_action_event_gain_passives(self, player, event_name):
        """Fire owned-domain `action.<event_name> manipulate_resources mode=gain gain=...` passives.

        Generic dispatcher for action-phase triggers: `start`, `end`, `hire`, `slay`,
        and any future verb. Only mode=gain is handled here -- player-targeted modes
        (take_from_player, pay_to_player) route through the action.end queue/prompt
        machinery and are intentionally ignored at the per-event call sites.

        The caller is responsible for invoking this only when the firing player is the
        active player; we still guard on `self.phase == "action"` so card text that says
        "During your Action Phase, ..." stays honest if a slay/hire ever leaks into
        another phase (e.g. via a granted action triggered from harvest).
        """
        if not player or not event_name:
            return
        if getattr(self, "phase", None) != "action":
            return
        prefix = f"action.{str(event_name).lower()}"
        for d in list(getattr(player, "owned_domains", []) or []):
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            raw = (getattr(d, "passive_effect", None) or "").strip()
            if not raw:
                continue
            parts = raw.split()
            if not parts or parts[0].lower() != prefix:
                continue
            rest = raw[len(parts[0]):].strip()
            if not rest.lower().startswith("manipulate_resources"):
                continue
            kv = _parse_domain_effect_kv(rest)
            if not kv:
                continue
            mode = (kv.get("mode") or "").strip().lower()
            if mode != "gain":
                continue
            self._apply_manipulate_gain(player, kv, source_label=getattr(d, "name", "Domain"))

    def _apply_action_start_domain_passives(self, player):
        """Fire any owned-domain passives keyed to 'action.start' for the active player."""
        self._apply_action_event_gain_passives(player, "start")
        # Handle optional blocking passives (self_convert, wild exchange) that need a prompt.
        # Process at most one blocking passive — the first owned domain that fires.
        if not player or getattr(self, "phase", None) != "action":
            return
        for d in list(getattr(player, "owned_domains", []) or []):
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            raw = (getattr(d, "passive_effect", None) or "").strip()
            if not raw:
                continue
            parts = raw.split()
            if not parts or parts[0].lower() != "action.start":
                continue
            rest = raw[len(parts[0]):].strip()
            rest_low = rest.lower()
            if rest_low.startswith("manipulate_resources"):
                kv = _parse_domain_effect_kv(rest)
                if (kv.get("mode") or "").strip().lower() == "self_convert":
                    self._prompt_or_apply_self_convert(rest, player, d, context="domain_activation")
                    if (self.action_required or {}).get("action") == "domain_self_convert":
                        return
            elif rest_low.startswith("exchange") and "wild" in rest_low:
                self._execute_action_start_wild_gain_exchange(rest, player, d)
                if (self.action_required or {}).get("action") == "harvest_wild_gain_exchange":
                    return

    def _execute_action_start_wild_gain_exchange(self, command, player, domain):
        """Fire a `exchange <res> N wild M` passive at action.start.

        Delegates to the existing wild-gain exchange machinery but stamps the
        pending_required_choice with context="action_start" so the resolution
        handler resumes the action phase instead of harvest.
        """
        result = self._execute_wild_gain_exchange_payout(command, player.player_id)
        prc = getattr(self, "pending_required_choice", None)
        if prc and prc.get("kind") == "harvest_wild_gain_exchange":
            prc["context"] = "action_start"
            prc["domain_name"] = getattr(domain, "name", "Domain")

    def _collect_action_end_manipulate_queue(self, active_player):
        out = []
        for d in list(getattr(active_player, "owned_domains", []) or []):
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            kv = self._parse_manipulate_action_end(getattr(d, "passive_effect", None) or "")
            if not kv:
                continue
            mode = (kv.get("mode") or "").strip().lower()
            if mode not in ("take_from_player", "pay_to_player", "self_convert"):
                continue
            out.append({
                "domain_name": getattr(d, "name", "Domain"),
                "mode": mode,
                "kv": kv,
            })
        return out

    def _manipulate_candidates_other_players(self, active_pid, take_or_pay, kv):
        """
        take_or_pay: 'take' (active receives from victim) or 'pay' (active pays victim, optional bank gain).
        """
        pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
        take_k, take_n = _parse_resource_kv(kv.get("take", ""))
        gain_k, gain_n = _parse_resource_kv(kv.get("gain", ""))
        optional = str(kv.get("optional", "")).strip().lower() in ("true", "1", "yes")
        res_k, res_n = (take_k, take_n) if take_or_pay == "take" else (pay_k, pay_n)
        if not res_k or res_n <= 0:
            return None, optional
        idx = {"g": 0, "s": 1, "m": 2, "v": 3}
        ri = idx[res_k]
        opts = []
        for p in self.player_list:
            if p.player_id == active_pid:
                continue
            # Resting seat is "not in play" for negative effects, but pay_to_player
            # is a positive effect for the target so it stays eligible.
            if take_or_pay == "take" and not self._player_is_negative_effect_target(p):
                continue
            if take_or_pay == "take" and self._player_has_take_immunity(p):
                continue
            tup = self._player_resource_tuple(p)
            if take_or_pay == "take" and tup[ri] < res_n:
                continue
            if take_or_pay == "pay":
                opts.append({"token": "player", "player_id": p.player_id, "name": getattr(p, "name", "?")})
                continue
            opts.append({"token": "player", "player_id": p.player_id, "name": getattr(p, "name", "?")})
        return {"res_k": res_k, "res_n": res_n, "gain_k": gain_k, "gain_n": gain_n, "mode": kv.get("mode"), "options": opts}, optional

    def _start_action_end_domain_sequence(self, active_pid):
        active = self._player_by_id(active_pid)
        if not active:
            return False
        q = self._collect_action_end_manipulate_queue(active)
        self.pending_action_end_queue = q
        if not q:
            return False
        self.phase = "action_end_pending"
        blocked = self._drain_action_end_manipulate_queue()
        if not blocked:
            self.phase = "action"
        return blocked

    def _drain_action_end_manipulate_queue(self):
        while self.pending_action_end_queue:
            item = self.pending_action_end_queue[0]
            active_pid = self.current_player_id()
            active = self._player_by_id(active_pid)
            if not active:
                self.pending_action_end_queue = []
                return False
            mode = item["mode"]
            kv = item["kv"]
            # self_convert items (Rime Temple, Switch Wind Fortress): prompt player to
            # optionally trade one resource for another. Skip silently if unaffordable.
            if mode == "self_convert":
                pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
                can_pay = bool(pay_k) and self._player_can_afford_self_convert_resources(active, pay_k, pay_n)
                if not can_pay:
                    self.pending_action_end_queue.pop(0)
                    continue
                self.action_required["id"] = active_pid
                self.action_required["action"] = "domain_self_convert"
                self.pending_required_choice = {
                    "kind": "domain_self_convert",
                    "player_id": active_pid,
                    "kv": kv,
                    "domain_name": item.get("domain_name", "Domain"),
                    "context": "action_end_queue",
                }
                return True
            gain_k, gain_n_from_kv = _parse_resource_kv(kv.get("gain", ""))
            optional = str(kv.get("optional", "")).strip().lower() in ("true", "1", "yes")
            vp_pay_may_decline = mode == "pay_to_player" and gain_k == "v" and gain_n_from_kv > 0
            optional_effective = optional or vp_pay_may_decline
            take_or_pay = "take" if mode == "take_from_player" else "pay"
            parsed, _opt = self._manipulate_candidates_other_players(active_pid, take_or_pay, kv)
            if not parsed or not parsed.get("options"):
                self.pending_action_end_queue.pop(0)
                if optional_effective:
                    continue
                self.pending_action_end_queue = []
                return False
            gain_k, gain_n = parsed.get("gain_k"), int(parsed.get("gain_n") or 0)
            res_k, res_n = parsed.get("res_k"), int(parsed.get("res_n") or 0)
            opts = parsed["options"]
            if mode == "pay_to_player":
                ap = self._player_by_id(active_pid)
                pk, pn = _parse_resource_kv(kv.get("pay", ""))
                if not pk or pn <= 0 or int(self._player_resource_tuple(ap)[{"g": 0, "s": 1, "m": 2, "v": 3}[pk]]) < pn:
                    self.pending_action_end_queue.pop(0)
                    if optional_effective:
                        continue
                    self.pending_action_end_queue = []
                    return False
            self.action_required["id"] = active_pid
            self.action_required["action"] = "choose_player"
            self.pending_required_choice = {
                "kind": "domain_manipulate_player",
                "player_id": active_pid,
                "item": item,
                "options": opts,
                "allow_skip": optional_effective,
            }
            return True
        return False

    def _apply_manipulate_player_choice(self, active_pid, target_pid, item):
        active = self._player_by_id(active_pid)
        victim = self._player_by_id(target_pid)
        if not active or not victim:
            return
        mode = item["mode"]
        kv = item["kv"]
        before_a = self._player_scores_line(active)
        before_v = self._player_scores_line(victim)
        gain_k, gain_n = _parse_resource_kv(kv.get("gain", ""))
        if mode == "take_from_player":
            tk, tn = _parse_resource_kv(kv.get("take", ""))
            dg = ds = dm = dv = 0
            if tk == "g":
                dg = tn
            elif tk == "s":
                ds = tn
            elif tk == "m":
                dm = tn
            elif tk == "v":
                dv = tn
            if not self._transfer_resources_player_to_player(victim, active, dg, ds, dm, dv):
                return
        elif mode == "pay_to_player":
            pk, pn = _parse_resource_kv(kv.get("pay", ""))
            dg = ds = dm = dv = 0
            if pk == "g":
                dg = pn
            elif pk == "s":
                ds = pn
            elif pk == "m":
                dm = pn
            elif pk == "v":
                dv = pn
            if not self._transfer_resources_player_to_player(active, victim, dg, ds, dm, dv):
                return
            if gain_k and gain_n > 0:
                self._bank_gain_for_active(active, gain_k, gain_n)
        after_a = self._player_scores_line(active)
        after_v = self._player_scores_line(victim)
        bank_vp_note = ""
        if mode == "pay_to_player" and gain_k == "v" and gain_n > 0:
            bank_vp_note = f" (+{gain_n} VP from bank, not from target)"
        source_label = item.get("source_label") or "end-of-action"
        self._log_game_event(
            f"{self._player_label(active_pid)} {source_label} \"{item.get('domain_name')}\" vs "
            f"{self._player_label(target_pid)}: active {before_a} -> {after_a}; target {before_v} -> {after_v}"
            f"{bank_vp_note}"
        )

    def _apply_harvest_jousting_passive(self, player):
        """Apply automatic harvest-phase domain passives for the active player.

        Supports compound passives joined by ` + ` (same compounding rule as
        domain activations). Each leg is a self-contained named-count verb:
          - `harvest.gain_per_owned_citizen_name <NAME> <R> <N>` -> counts owned citizens
          - `harvest.gain_per_owned_starter_name <NAME> <R> <N>` -> counts owned starters
        Names match case-insensitively against the card's `name`. Resource
        letter R is one of g | s | m | v. Multiplier N is gained per matching
        unflipped card in the relevant pool.

        Example (Jousting Field gains 1g per Knight whether citizen or starter):
          `harvest.gain_per_owned_citizen_name Knight g 1 + harvest.gain_per_owned_starter_name Knight g 1`
        """
        if not player:
            return
        for d in list(getattr(player, "owned_domains", []) or []):
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            raw = (getattr(d, "passive_effect", None) or "").strip()
            if not raw:
                continue
            for leg in [s.strip() for s in raw.split(" + ") if s.strip()]:
                self._apply_harvest_named_count_leg(player, d, leg)

    def _apply_harvest_named_count_leg(self, player, domain, leg):
        """Apply a single `harvest.gain_per_owned_{citizen,starter}_name NAME R N` leg."""
        parts = leg.split()
        if len(parts) < 4:
            return
        verb = parts[0].strip().lower()
        if verb == "harvest.gain_per_owned_citizen_name":
            pool_attr = "owned_citizens"
            pool_label = "citizen"
        elif verb == "harvest.gain_per_owned_starter_name":
            pool_attr = "owned_starters"
            pool_label = "starter"
        else:
            return
        unit_name = parts[1]
        res = (parts[2] or "").strip().lower()
        try:
            mult = int(parts[3])
        except (TypeError, ValueError):
            return
        want = unit_name.strip().lower()
        n = 0
        for c in list(getattr(player, pool_attr, []) or []):
            if getattr(c, "is_flipped", False):
                continue
            if (getattr(c, "name", "") or "").strip().lower() == want:
                n += 1
        if n <= 0:
            return
        gain = mult * n
        dg = ds = dm = dv = 0
        if res == "g":
            dg = gain
        elif res == "s":
            ds = gain
        elif res == "m":
            dm = gain
        elif res == "v":
            dv = gain
        else:
            return
        before = self._player_scores_line(player)
        player.gold_score = int(player.gold_score) + dg
        player.strength_score = int(player.strength_score) + ds
        player.magic_score = int(player.magic_score) + dm
        player.victory_score = int(player.victory_score) + dv
        self._bump_harvest_delta(player, dg, ds, dm, dv)
        after = self._player_scores_line(player)
        self._log_game_event(
            f"{self._player_label(player.player_id)} harvest passive \"{getattr(domain, 'name', 'Domain')}\" "
            f"({unit_name} {pool_label} x{n}): scores {before} -> {after}"
        )

    def _prompt_domain_monster_strength_boost(self, player, domain, effect):
        parts = effect.split()
        delta = 3
        if parts:
            try:
                delta = int(str(parts[-1]).replace("+", "").strip())
            except (TypeError, ValueError):
                delta = 3
        options = []
        for stack in self.monster_grid:
            if not stack:
                continue
            top = stack[-1]
            if not getattr(top, "is_accessible", False):
                continue
            if getattr(top, "monster_id", None) is None:
                continue  # Event/Exhausted placeholder — not a valid strength-boost target
            options.append({
                "token": "monster.choice",
                "monster_id": int(getattr(top, "monster_id", -1)),
                "name": getattr(top, "name", "?"),
            })
        if not options:
            self._log_game_event(
                f"{self._player_label(player.player_id)} could not use \"{getattr(domain, 'name', 'Domain')}\" "
                f"(no accessible monsters)."
            )
            return
        if len(options) == 1:
            self._apply_monster_strength_boost(options[0]["monster_id"], delta)
            self._log_game_event(
                f"{self._player_label(player.player_id)} activated \"{getattr(domain, 'name', 'Domain')}\" "
                f"on \"{options[0].get('name')}\" (+{delta} strength cost)."
            )
            return
        self.action_required["id"] = player.player_id
        self.action_required["action"] = "choose_monster_strength"
        self.pending_required_choice = {
            "kind": "domain_boost_monster",
            "player_id": player.player_id,
            "delta": delta,
            "domain_name": getattr(domain, "name", "Domain"),
            "options": options,
        }

    def _apply_monster_strength_boost(self, monster_id, delta):
        try:
            mid = int(monster_id)
        except (TypeError, ValueError):
            return False
        for stack in self.monster_grid:
            if not stack:
                continue
            top = stack[-1]
            if int(getattr(top, "monster_id", -1)) != mid:
                continue
            if not getattr(top, "is_accessible", False):
                return False
            top.strength_cost = int(getattr(top, "strength_cost", 0) or 0) + int(delta or 0)
            return True
        return False

    def _apply_domain_activation_effect(self, player, domain):
        effect = (getattr(domain, "activation_effect", None) or "").strip()
        if not effect:
            return
        low = effect.lower()
        if low.startswith("action.modify_monster_strength"):
            self._prompt_domain_monster_strength_boost(player, domain, effect)
            return
        if low.startswith("return_owned"):
            parsed = self._parse_return_owned_effect(effect)
            if parsed:
                self._prompt_return_owned_card(player, domain, parsed)
            return
        if low.startswith("manipulate_resources"):
            kv = _parse_domain_effect_kv(effect)
            mode = (kv.get("mode") or "").strip().lower()
            if mode == "self_convert":
                before = self._player_scores_line(player)
                payout = self._prompt_or_apply_self_convert(effect, player, domain)
                if isinstance(self.action_required, dict) and self.action_required.get("action"):
                    self._log_game_event(
                        f"{self._player_label(player.player_id)} triggered activation effect on \"{getattr(domain, 'name', 'Domain')}\" and is choosing options."
                    )
                    return
                if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
                    return
                player.gold_score = int(player.gold_score) + payout[0]
                player.strength_score = int(player.strength_score) + payout[1]
                player.magic_score = int(player.magic_score) + payout[2]
                player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
                self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
                after = self._player_scores_line(player)
                if before != after:
                    self._log_game_event(
                        f"{self._player_label(player.player_id)} activated domain \"{getattr(domain, 'name', 'Domain')}\"; scores {before} -> {after}"
                    )
                return
            if mode in ("take_from_player", "pay_to_player"):
                self._prompt_activation_manipulate_player(player, domain, kv)
                return
        before = self._player_scores_line(player)
        _prior_action = (self.action_required or {}).get("action", "")
        _prior_concurrent = getattr(self, "concurrent_action", None)
        # Tag any bare-verb `slay` payout in the effect with this domain's name so the
        # prompt knows what to call out. Cleared in finally so the tag never leaks
        # into other payout paths (harvest, action.end queues, etc.).
        self._immediate_slay_source_label = getattr(domain, "name", "Domain")
        try:
            payout = self.execute_special_payout(effect, player.player_id, auto_apply_single_choice=False)
        finally:
            self._immediate_slay_source_label = None
        _new_action = (self.action_required or {}).get("action", "")
        _new_concurrent = getattr(self, "concurrent_action", None)
        if (_new_action and _new_action != _prior_action) or (_new_concurrent is not _prior_concurrent):
            # Compound payouts (e.g. Cloudrider's Camp: "s 3 + choose <citizens ...>") resolve the
            # resource leg before the blocking choose; apply those gains now so they are not lost.
            if isinstance(payout, list) and len(payout) >= 4 and payout[0] != -9999:
                player.gold_score = int(player.gold_score) + payout[0]
                player.strength_score = int(player.strength_score) + payout[1]
                player.magic_score = int(player.magic_score) + payout[2]
                player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
                self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
            self._log_game_event(
                f"{self._player_label(player.player_id)} triggered activation effect on \"{getattr(domain, 'name', 'Domain')}\" and is choosing options."
            )
            return
        if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
            return
        player.gold_score = int(player.gold_score) + payout[0]
        player.strength_score = int(player.strength_score) + payout[1]
        player.magic_score = int(player.magic_score) + payout[2]
        player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
        self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
        after = self._player_scores_line(player)
        if before != after:
            self._log_game_event(
                f"{self._player_label(player.player_id)} activated domain \"{getattr(domain, 'name', 'Domain')}\"; scores {before} -> {after}"
            )

    def _prompt_activation_manipulate_player(self, player, domain, kv):
        """Immediate activation prompt for manipulate_resources mode=take_from_player or pay_to_player.

        Reuses the `domain_manipulate_player` prompt + `_apply_manipulate_player_choice` apply path
        from action.end passives, but marks `from_activation=True` so resolution resumes the
        action phase via `_resume_after_domain_activation_follow_up` instead of draining the
        action.end queue.
        """
        mode = (kv.get("mode") or "").strip().lower()
        domain_name = getattr(domain, "name", "Domain")
        gain_k, gain_n_from_kv = _parse_resource_kv(kv.get("gain", ""))
        optional = str(kv.get("optional", "")).strip().lower() in ("true", "1", "yes")
        vp_pay_may_decline = mode == "pay_to_player" and gain_k == "v" and gain_n_from_kv > 0
        optional_effective = optional or vp_pay_may_decline
        take_or_pay = "take" if mode == "take_from_player" else "pay"
        parsed, _opt = self._manipulate_candidates_other_players(player.player_id, take_or_pay, kv)
        if not parsed or not parsed.get("options"):
            self._log_game_event(
                f"{self._player_label(player.player_id)} could not use \"{domain_name}\" "
                f"(no eligible players)."
            )
            return
        if mode == "pay_to_player":
            pk, pn = _parse_resource_kv(kv.get("pay", ""))
            res_idx = {"g": 0, "s": 1, "m": 2, "v": 3}
            if not pk or pn <= 0 or int(self._player_resource_tuple(player)[res_idx[pk]]) < pn:
                self._log_game_event(
                    f"{self._player_label(player.player_id)} could not use \"{domain_name}\" "
                    f"(insufficient resources to pay)."
                )
                return
        item = {"domain_name": domain_name, "mode": mode, "kv": kv, "source_label": "activated"}
        self.action_required["id"] = player.player_id
        self.action_required["action"] = "choose_player"
        self.pending_required_choice = {
            "kind": "domain_manipulate_player",
            "player_id": player.player_id,
            "item": item,
            "options": parsed["options"],
            "allow_skip": optional_effective,
            "from_activation": True,
        }
        self._log_game_event(
            f"{self._player_label(player.player_id)} triggered activation effect on \"{domain_name}\" and is choosing a player."
        )

    def _parse_return_owned_effect(self, effect):
        """Parse `return_owned <kind> <resource> <amount> [optional]`.

        Returns dict with kind ("monster"|"citizen"), resource (g|s|m|v), amount (int),
        and optional (bool); or None if the string is malformed.
        """
        parts = (effect or "").strip().split()
        if len(parts) < 4 or parts[0].lower() != "return_owned":
            return None
        kind = parts[1].lower()
        if kind not in ("monster", "citizen"):
            return None
        resource = parts[2].lower()
        if resource not in ("g", "s", "m", "v"):
            return None
        try:
            amount = int(parts[3])
        except (TypeError, ValueError):
            return None
        optional = len(parts) >= 5 and parts[4].lower() == "optional"
        return {"kind": kind, "resource": resource, "amount": amount, "optional": optional}

    def _prompt_return_owned_card(self, player, domain, parsed):
        """Open a `choose_owned_card` prompt for Watcher/Nest-style activations.

        parsed: {kind: "monster"|"citizen", resource: g/s/m/v, amount: int, optional: bool}
        """
        kind = parsed["kind"]
        optional = bool(parsed.get("optional"))
        domain_name = getattr(domain, "name", "Domain")
        options = []
        if kind == "monster":
            owned = list(getattr(player, "owned_monsters", []) or [])
            for i, m in enumerate(owned):
                options.append({
                    "token": "monster.owned",
                    "idx": i,
                    "name": getattr(m, "name", "?"),
                    "monster_id": int(getattr(m, "monster_id", -1)),
                    "area": getattr(m, "area", ""),
                })
        else:
            owned = list(getattr(player, "owned_citizens", []) or [])
            for i, c in enumerate(owned):
                options.append({
                    "token": "citizen.owned",
                    "idx": i,
                    "name": getattr(c, "name", "?"),
                    "citizen_id": int(getattr(c, "citizen_id", -1)),
                })
        if not options:
            self._log_game_event(
                f"{self._player_label(player.player_id)} could not use \"{domain_name}\" "
                f"(no owned {kind}s to return)."
            )
            return
        self.action_required["id"] = player.player_id
        self.action_required["action"] = "choose_owned_card"
        self.pending_required_choice = {
            "kind": "domain_return_owned",
            "player_id": player.player_id,
            "domain_name": domain_name,
            "card_kind": kind,
            "resource": parsed["resource"],
            "amount": int(parsed["amount"]),
            "allow_skip": optional,
            "options": options,
        }
        self._log_game_event(
            f"{self._player_label(player.player_id)} triggered activation effect on \"{domain_name}\" and is choosing a {kind} to return."
        )

    def _parse_take_owned_effect(self, effect):
        """Parse `take_owned <kind> <pick> [optional]`.

        Symmetric inverse of `return_owned`: instead of returning one of your own
        cards to its board stack for a reward, you transfer one of someone else's
        owned cards to yourself.

        Args:
          kind:     "monster" (future: "citizen")
          pick:     "random"  (future: "choose" -- let the activating player pick the specific card)
          optional: literal "optional" flag (when present, activator may decline)

        Returns dict {kind, pick, optional} or None if malformed.
        """
        parts = (effect or "").strip().split()
        if len(parts) < 3 or parts[0].lower() != "take_owned":
            return None
        kind = parts[1].lower()
        if kind not in ("monster", "citizen"):
            return None
        pick = parts[2].lower()
        if pick not in ("random",):
            return None
        optional = len(parts) >= 4 and parts[3].lower() == "optional"
        return {"kind": kind, "pick": pick, "optional": optional}

    def _execute_take_owned_payout(self, command, player_id):
        """Route `take_owned <kind> <pick> [optional]` through execute_special_payout.

        Works for both domain activations (source label already set by
        _apply_domain_activation_effect) and monster special rewards (label set by
        slay_monster before calling execute_special_payout).
        """
        parsed = self._parse_take_owned_effect(command)
        if not parsed:
            return [-9999, 0, 0, 0]
        player = self._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        source_name = getattr(self, "_immediate_slay_source_label", None) or "Effect"
        self._prompt_take_owned_card(player, source_name, parsed)
        return [0, 0, 0, 0]

    def _prompt_take_owned_card(self, player, source_name, parsed):
        """Open a `choose_player` prompt for take_owned effects (domains and monsters).

        Reuses the same prompt verb used by `domain_manipulate_player` so client and
        blocking-check code don't need a new action token. The discriminator lives
        in `pending_required_choice.kind = "domain_take_owned"`.

        Eligibility: only other players with at least one owned card of the right
        kind are listed. If nobody is eligible the effect is silently lost; we log
        it so the player can see why nothing happened.
        """
        kind = parsed["kind"]
        pick = parsed.get("pick", "random")
        optional = bool(parsed.get("optional"))
        domain_name = source_name
        active_pid = player.player_id
        attr = "owned_monsters" if kind == "monster" else "owned_citizens"
        options = []
        for p in self.player_list:
            if p.player_id == active_pid:
                continue
            if not self._player_is_negative_effect_target(p):
                continue
            # `take_owned` removes a card from the target's tableau, so it is a
            # "take" effect under Castle of the Seven Suns' operator-icon
            # reading ("you" includes your cards). Players with `immunity.take`
            # are not eligible targets.
            if self._player_has_take_immunity(p):
                continue
            if not list(getattr(p, attr, []) or []):
                continue
            options.append({
                "token": "player",
                "player_id": p.player_id,
                "name": getattr(p, "name", "?"),
            })
        if not options:
            self._log_game_event(
                f"{self._player_label(active_pid)} could not use \"{domain_name}\" "
                f"(no other player owns a {kind})."
            )
            return
        self.action_required["id"] = active_pid
        self.action_required["action"] = "choose_player"
        self.pending_required_choice = {
            "kind": "domain_take_owned",
            "player_id": active_pid,
            "domain_name": domain_name,
            "card_kind": kind,
            "pick": pick,
            "allow_skip": optional,
            "options": options,
            "from_activation": True,
        }
        self._log_game_event(
            f"{self._player_label(active_pid)} triggered activation effect on \"{domain_name}\" "
            f"and is choosing a player to steal a {kind} from."
        )

    def _monster_stack_index_for_area(self, area):
        """Return the monster_grid stack index assigned to `area` at game setup, or None."""
        if not area:
            return None
        mapping = list(getattr(self, "monster_stack_areas", []) or [])
        for i, a in enumerate(mapping):
            if a == area:
                return i
        return None

    def _unexhaust_stack_top_if_present(self, stack):
        """If stack's top card is an Exhausted token, pop it back to the pool. Returns True if popped."""
        if not stack:
            return False
        top = stack[-1]
        if getattr(top, "name", "") != "Exhausted":
            return False
        stack.pop(-1)
        self.exhausted_stack.append(top)
        self.exhausted_count = max(0, int(self.exhausted_count) - 1)
        return True

    def _return_monster_to_stack(self, monster):
        """Place a previously-owned monster back on its area stack. Handles un-exhausting if needed."""
        stack_idx = self._monster_stack_index_for_area(getattr(monster, "area", None))
        if stack_idx is None:
            return False
        stack = self.monster_grid[stack_idx]
        self._unexhaust_stack_top_if_present(stack)
        if stack:
            stack[-1].toggle_accessibility(False)
        monster.toggle_visibility(True)
        monster.toggle_accessibility(True)
        stack.append(monster)
        return True

    def _return_citizen_to_stack(self, citizen):
        """Place a previously-owned citizen back on its roll-keyed stack. Handles un-exhausting if needed."""
        try:
            rm1 = int(getattr(citizen, "roll_match1", 0) or 0)
        except (TypeError, ValueError):
            return False
        if rm1 == 11:
            stack_idx = 9
        elif 1 <= rm1 <= 9:
            stack_idx = rm1 - 1
        else:
            return False
        stack = self.citizen_grid[stack_idx]
        self._unexhaust_stack_top_if_present(stack)
        if stack:
            stack[-1].toggle_accessibility(False)
        # Citizens always come back face-up on the board (face-down only applies to owned tableau cards).
        self._citizen_set_flipped(citizen, False)
        stack.append(citizen)
        return True

    def _filter_unavailable_choose_options(self, options):
        out = []
        for opt in options or []:
            token = (opt.get("token") or "").strip().lower()
            if token == "citizens_where":
                spec = opt.get("spec") or {}
                count = int(opt.get("amount", 1) or 1)
                if len(self._board_citizen_candidates(spec)) < count:
                    continue
            out.append(opt)
        return out

    def _expand_choose_options_for_prompt(self, options):
        expanded = []
        for opt in options or []:
            token = (opt.get("token") or "").strip().lower()
            if token in ("g", "s", "m", "v"):
                expanded.append({"token": token, "amount": int(opt.get("amount", 0) or 0)})
                continue
            if token == "count_area":
                expanded.append(opt)
                continue
            if token != "citizens_where":
                continue
            if int(opt.get("amount", 1) or 1) != 1:
                continue
            spec = opt.get("spec") or {}
            candidates = self._board_citizen_candidates(spec)
            for c in candidates:
                extras = list(opt.get("extras") or [])
                expanded.append({
                    "token": "citizens.choice",
                    "amount": 1,
                    "citizen_id": c.citizen_id,
                    "name": c.name,
                    "gold_cost": int(getattr(c, "gold_cost", 0) or 0),
                    "extras": extras,
                })
        return expanded

    def _finalize_citizen_stack_after_claiming_top(self, citizen_stack):
        if citizen_stack:
            citizen_stack[-1].toggle_accessibility(True)
            return
        if self.exhausted_stack:
            exhausted = self.exhausted_stack.pop()
            if isinstance(exhausted, Event):
                exhausted.toggle_visibility(True)
                exhausted.toggle_accessibility(True)
            citizen_stack.append(exhausted)
            self.exhausted_count = int(self.exhausted_count) + 1

    def _claim_specific_board_citizen(self, player_id, citizen_id):
        target = self._player_by_id(player_id)
        if not target:
            return False
        try:
            wanted = int(citizen_id)
        except (TypeError, ValueError):
            return False
        for stack in self.citizen_grid:
            if not stack:
                continue
            top = stack[-1]
            if not getattr(top, "is_accessible", False):
                continue
            if int(getattr(top, "citizen_id", -1)) != wanted:
                continue
            claimed = stack.pop(-1)
            self._citizen_set_flipped(claimed, False)
            target.owned_citizens.append(claimed)
            self._finalize_citizen_stack_after_claiming_top(stack)
            return True
        return False

    def _apply_choose_option(self, player_id, opt):
        target = self._player_by_id(player_id)
        if not target:
            return False
        token = (opt.get("token") or "").strip().lower()
        amount = int(opt.get("amount", 0))
        if amount <= 0 and token not in ("count_area",):
            return False
        if token == "citizens.choice":
            if not self._claim_specific_board_citizen(player_id, opt.get("citizen_id")):
                return False
            for e in list(opt.get("extras") or []):
                t = (e.get("token") or "").strip().lower()
                n = int(e.get("amount", 0) or 0)
                if t == "g":
                    target.gold_score = int(target.gold_score) + n
                    self._bump_harvest_delta(target, n, 0, 0, 0)
                elif t == "s":
                    target.strength_score = int(target.strength_score) + n
                    self._bump_harvest_delta(target, 0, n, 0, 0)
                elif t == "m":
                    target.magic_score = int(target.magic_score) + n
                    self._bump_harvest_delta(target, 0, 0, n, 0)
                elif t == "v":
                    target.victory_score = int(getattr(target, "victory_score", 0)) + n
                    self._bump_harvest_delta(target, 0, 0, 0, n)
                else:
                    return False
            return True
        if token == "count_area":
            area = opt.get("area")
            resource = (opt.get("resource") or "").strip().lower()
            mult = int(opt.get("mult", 0) or 0)
            count = int((self.owned_monster_attributes(player_id) or {}).get(area, 0) or 0)
            total = count * mult
            if resource == "g":
                target.gold_score = int(target.gold_score) + total
                self._bump_harvest_delta(target, total, 0, 0, 0)
            elif resource == "s":
                target.strength_score = int(target.strength_score) + total
                self._bump_harvest_delta(target, 0, total, 0, 0)
            elif resource == "m":
                target.magic_score = int(target.magic_score) + total
                self._bump_harvest_delta(target, 0, 0, total, 0)
            elif resource == "v":
                target.victory_score = int(getattr(target, "victory_score", 0)) + total
                self._bump_harvest_delta(target, 0, 0, 0, total)
            else:
                return False
            return True
        dg = ds = dm = dv = 0
        if token == "g":
            dg = amount
        elif token == "s":
            ds = amount
        elif token == "m":
            dm = amount
        elif token == "v":
            dv = amount
        else:
            return False
        target.gold_score = int(target.gold_score) + int(dg)
        target.strength_score = int(target.strength_score) + int(ds)
        target.magic_score = int(target.magic_score) + int(dm)
        target.victory_score = int(getattr(target, "victory_score", 0)) + int(dv)
        if not hasattr(target, "harvest_delta") or not isinstance(target.harvest_delta, dict):
            target.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
        self._bump_harvest_delta(target, dg, ds, dm, dv)
        return True

    def _describe_choose_option(self, opt):
        token = (opt.get("token") or "").strip().lower()
        if token in ("g", "s", "m", "v"):
            label = {"g": "gold", "s": "strength", "m": "magic", "v": "victory"}[token]
            return f"+{int(opt.get('amount', 0) or 0)} {label}"
        if token == "count_area":
            area = opt.get("area")
            resource = (opt.get("resource") or "").strip().lower()
            mult = int(opt.get("mult", 0) or 0)
            label = {"g": "gold", "s": "strength", "m": "magic", "v": "victory"}.get(resource, resource)
            return f"+({mult} x {area}) {label}"
        if token == "citizens.choice":
            name = (opt.get("name") or "Citizen").strip()
            extras = list(opt.get("extras") or [])
            suffix = ""
            if extras:
                parts = []
                for e in extras:
                    et = (e.get("token") or "").strip().lower()
                    ea = int(e.get("amount", 0) or 0)
                    el = {"g": "gold", "s": "strength", "m": "magic", "v": "victory"}.get(et, et)
                    parts.append(f"+{ea} {el}")
                suffix = " + " + " + ".join(parts)
            return f"gain 1 {name} citizen{suffix}"
        return f"{token} {opt.get('amount')}"

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

    def wait_for_input(self, command, player_id):
        print("waiting for input")
        while self.action_required["id"] != self.game_id:
            time.sleep(1)  # wait for 1 second before checking again
        print("input received")
        choice = []
        payout = [0, 0, 0, 0]
        match self.action_required['action']:
            case 'choose 1':
                choice = [command[1], command[2]]
            case 'choose 2':
                choice = [command[3], command[4]]
            case 'choose 3':
                choice = [command[5], command[6]]  # [sixth_word, seventh_word]
            case _:
                payout[0] = -9999
        match choice[0]:
            case 'g':
                payout[0] = payout[0] + int(choice[1])
            case 's':
                payout[1] = payout[1] + int(choice[1])
            case 'm':
                payout[2] = payout[2] + int(choice[1])
            case 'v':
                payout[3] = payout[3] + int(choice[1])
            case _:
                payout[0] = -9999
        for player in self.player_list:
            if player.player_id == player_id:
                player.gold_score = player.gold_score + payout[0]
                player.strength_score = player.strength_score + payout[1]
                player.magic_score = player.magic_score + payout[2]
                player.victory_score = player.victory_score + payout[3]
                # If this payout is resolving a harvest-time choice, track it on the same harvest delta.
                if not hasattr(player, "harvest_delta") or not isinstance(player.harvest_delta, dict):
                    player.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
                player.harvest_delta["gold"] = int(player.harvest_delta.get("gold", 0)) + int(payout[0])
                player.harvest_delta["strength"] = int(player.harvest_delta.get("strength", 0)) + int(payout[1])
                player.harvest_delta["magic"] = int(player.harvest_delta.get("magic", 0)) + int(payout[2])
                player.harvest_delta["victory"] = int(player.harvest_delta.get("victory", 0)) + int(payout[3])
        for player in self.player_list:
            print(f"Player {player.name}: {player.gold_score} G, {player.strength_score} S, {player.magic_score} M,"
                  f" {player.victory_score} VP, Monsters: {len(player.owned_monsters)}, "
                  f"Citizens: {len(player.owned_citizens)}, Domains {len(player.owned_domains)}")
        self._maybe_resume_harvest_prompt()

    def act_on_required_action(self, player_id, action):
        if self.action_required['id'] == player_id:
            print("correct player responded to action")
            current_required = self.action_required.get("action", "")

            # Special: bonus resource choice (imaginary starter on "no payout" harvest)
            if current_required == "bonus_resource_choice":
                choice = (action or "").strip().lower()
                if choice not in ("gold", "strength", "magic"):
                    return
                target = self._player_by_id(player_id)
                if not target:
                    return
                before = self._player_scores_line(target)
                if choice == "gold":
                    target.gold_score += 1
                    target.harvest_delta["gold"] = int(target.harvest_delta.get("gold", 0)) + 1
                elif choice == "strength":
                    target.strength_score += 1
                    target.harvest_delta["strength"] = int(target.harvest_delta.get("strength", 0)) + 1
                else:
                    target.magic_score += 1
                    target.harvest_delta["magic"] = int(target.harvest_delta.get("magic", 0)) + 1
                after = self._player_scores_line(target)
                self._log_game_event(
                    f"{self._player_label(player_id)} harvest bonus +1 {choice} (no gold/strength/magic spent); "
                    f"scores {before} -> {after}"
                )

                # Pop current pending player and either fire the next bonus, or clear blocking.
                if self.pending_harvest_choices and self.pending_harvest_choices[0] == player_id:
                    self.pending_harvest_choices.pop(0)
                if self.pending_harvest_choices:
                    self._activate_finalize_bonus_for(self.pending_harvest_choices[0])
                    return

                self.action_required['action'] = ""
                self.action_required['id'] = self.game_id
                return

            if current_required == "harvest_optional_exchange":
                prc_h = getattr(self, "pending_required_choice", None) or {}
                if prc_h.get("kind") != "harvest_optional_exchange" or prc_h.get("player_id") != player_id:
                    return
                act_h = (action or "").strip().lower()
                if act_h not in ("confirm_harvest_exchange", "skip_harvest_exchange"):
                    return
                cmd_h = (prc_h.get("command") or "").strip()
                target_h = self._player_by_id(player_id)
                self.pending_required_choice = None
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                if not target_h or not cmd_h:
                    self._maybe_resume_harvest_prompt()
                    return
                before_h = self._player_scores_line(target_h)
                if act_h == "skip_harvest_exchange":
                    self._log_game_event(
                        f"{self._player_label(player_id)} skipped optional harvest exchange ({cmd_h}); "
                        f"scores unchanged ({before_h})."
                    )
                    self._maybe_resume_harvest_prompt()
                    return
                payout_h = self.execute_special_payout(
                    cmd_h,
                    player_id,
                    suppress_exchange_optional_prompt=True,
                )
                if isinstance(payout_h, list) and len(payout_h) >= 4 and payout_h[0] != -9999:
                    target_h.gold_score = int(target_h.gold_score) + int(payout_h[0])
                    target_h.strength_score = int(target_h.strength_score) + int(payout_h[1])
                    target_h.magic_score = int(target_h.magic_score) + int(payout_h[2])
                    target_h.victory_score = int(getattr(target_h, "victory_score", 0)) + int(payout_h[3])
                    self._bump_harvest_delta(target_h, payout_h[0], payout_h[1], payout_h[2], payout_h[3])
                    after_h = self._player_scores_line(target_h)
                    self._log_game_event(
                        f"{self._player_label(player_id)} took harvest exchange ({cmd_h}); scores {before_h} -> {after_h}"
                    )
                self._maybe_resume_harvest_prompt()
                return

            if current_required == "harvest_steal":
                prc_s = getattr(self, "pending_required_choice", None) or {}
                if prc_s.get("kind") != "harvest_steal" or prc_s.get("player_id") != player_id:
                    return
                victim_opts_s = list(prc_s.get("victim_options") or [])
                resource_opts_s = list(prc_s.get("resource_options") or [])
                act_s = (action or "").strip().lower()
                stage_s = (prc_s.get("stage") or "victim").strip().lower()
                if stage_s == "victim" and act_s.startswith("steal_victim "):
                    try:
                        idx_s = int(act_s.split()[1]) - 1
                    except (IndexError, ValueError):
                        return
                    if idx_s < 0 or idx_s >= len(victim_opts_s):
                        return
                    victim_opt_s = victim_opts_s[idx_s]
                    if len(resource_opts_s) == 1:
                        res_opt_s = resource_opts_s[0]
                        self.pending_required_choice = None
                        self.action_required["action"] = ""
                        self.action_required["id"] = self.game_id
                        self._apply_harvest_steal_choice(
                            player_id,
                            victim_opt_s.get("victim_id"),
                            res_opt_s.get("resource"),
                            res_opt_s.get("amount"),
                        )
                        self._maybe_resume_harvest_prompt()
                        return
                    self.pending_required_choice = {
                        "kind": "harvest_steal",
                        "stage": "resource",
                        "player_id": player_id,
                        "victim": victim_opt_s,
                        "resource_options": resource_opts_s,
                    }
                    self.action_required["action"] = "harvest_steal"
                    self.action_required["id"] = player_id
                    return
                if stage_s == "resource" and act_s.startswith("steal_resource "):
                    try:
                        idx_s = int(act_s.split()[1]) - 1
                    except (IndexError, ValueError):
                        return
                    if idx_s < 0 or idx_s >= len(resource_opts_s):
                        return
                    victim_opt_s = prc_s.get("victim") or {}
                    res_opt_s = resource_opts_s[idx_s]
                    self.pending_required_choice = None
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self._apply_harvest_steal_choice(
                        player_id,
                        victim_opt_s.get("victim_id"),
                        res_opt_s.get("resource"),
                        res_opt_s.get("amount"),
                    )
                    self._maybe_resume_harvest_prompt()
                    return
                # Backward compatibility for the old flat "steal N" client action.
                opts_s = list(prc_s.get("options") or [])
                if act_s.startswith("steal "):
                    try:
                        idx_s = int(act_s.split()[1]) - 1
                    except (IndexError, ValueError):
                        return
                    if idx_s < 0 or idx_s >= len(opts_s):
                        return
                    opt_s = opts_s[idx_s]
                    self.pending_required_choice = None
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self._apply_harvest_steal_choice(
                        player_id,
                        opt_s.get("victim_id"),
                        opt_s.get("resource"),
                        opt_s.get("amount"),
                    )
                    self._maybe_resume_harvest_prompt()
                    return
                return

            if current_required == "harvest_wild_gain_exchange":
                prc_wg = getattr(self, "pending_required_choice", None) or {}
                if prc_wg.get("kind") != "harvest_wild_gain_exchange" or prc_wg.get("player_id") != player_id:
                    return
                act_wg = (action or "").strip().lower()
                if not act_wg.startswith("wild_gain_resource "):
                    return
                res_wg = act_wg.split()[1] if len(act_wg.split()) > 1 else ""
                if res_wg not in ("g", "s", "m"):
                    return
                self.pending_required_choice = None
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self._apply_wild_gain_exchange_choice(player_id, res_wg, prc_wg)
                if prc_wg.get("context") == "action_start":
                    self._resume_after_domain_activation_follow_up()
                else:
                    self._maybe_resume_harvest_prompt()
                return

            if current_required == "harvest_wild_cost_exchange":
                prc_wc = getattr(self, "pending_required_choice", None) or {}
                if prc_wc.get("kind") != "harvest_wild_cost_exchange" or prc_wc.get("player_id") != player_id:
                    return
                act_wc = (action or "").strip().lower()
                if not act_wc.startswith("wild_cost_resource "):
                    return
                res_wc = act_wc.split()[1] if len(act_wc.split()) > 1 else ""
                valid_wc = {o["resource"] for o in (prc_wc.get("cost_options") or [])}
                if res_wc not in valid_wc:
                    return
                self.pending_required_choice = None
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self._apply_wild_cost_exchange_choice(player_id, res_wc, prc_wc)
                self._maybe_resume_harvest_prompt()
                return

            if current_required == "choose_domain_reward":
                prc_dr = getattr(self, "pending_required_choice", None) or {}
                if prc_dr.get("kind") != "grant_domain_reward" or prc_dr.get("player_id") != player_id:
                    return
                act_dr = (action or "").strip().lower()
                if not act_dr.startswith("grant_domain "):
                    return
                opts_dr = list(prc_dr.get("options") or [])
                try:
                    sel_dr = int(act_dr.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel_dr < 0 or sel_dr >= len(opts_dr):
                    return
                stack_idx_dr = opts_dr[sel_dr]["stack_idx"]
                self.pending_required_choice = None
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self._apply_grant_domain_choice(player_id, stack_idx_dr)
                self._resume_after_domain_activation_follow_up()
                return

            if current_required == "choose_domain_to_build":
                prc_db = getattr(self, "pending_required_choice", None) or {}
                if prc_db.get("kind") != "domain_build_opportunity" or prc_db.get("player_id") != player_id:
                    return
                act_db = (action or "").strip().lower()
                if act_db == "skip":
                    self.pending_required_choice = None
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined to build a domain (Ararmartin Ridge)."
                    )
                    self._resume_after_domain_activation_follow_up()
                    return
                if not act_db.startswith("build_domain_pick "):
                    return
                opts_db = list(prc_db.get("options") or [])
                try:
                    sel_db = int(act_db.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel_db < 0 or sel_db >= len(opts_db):
                    return
                chosen = opts_db[sel_db]
                domain_id_db = chosen["domain_id"]
                gold_cost_db = int(chosen.get("gold_cost", 0))
                self.pending_required_choice = None
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.build_domain(player_id, domain_id_db, gp=gold_cost_db)
                if not (self.action_required.get("action") and self.action_required.get("id") != self.game_id):
                    self._resume_after_domain_activation_follow_up()
                return

            prc0 = getattr(self, "pending_required_choice", None) or {}

            # Immediate "may slay a Monster" prompt — stage 1: pick a monster.
            if prc0.get("kind") == "immediate_slay" and str(current_required).strip() == "choose_monster_slay":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                resume_kind = prc0.get("resume_kind", "domain_activation")
                source_label = prc0.get("source_label", "Effect")
                if act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined to slay (\"{source_label}\")."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_after_immediate_slay(resume_kind)
                    return
                if not act.startswith("choose_monster_slay "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    idx = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if idx < 0 or idx >= len(opts):
                    return
                # Stage 2: collect the slay payment.
                self._enter_slay_payment_stage(prc0, opts[idx])
                return

            # Immediate "may slay a Monster" prompt — stage 2: collect payment + slay.
            if prc0.get("kind") == "immediate_slay" and str(current_required).strip() == "slay_monster_payment":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                resume_kind = prc0.get("resume_kind", "domain_activation")
                source_label = prc0.get("source_label", "Effect")
                if act == "back":
                    self.action_required["action"] = "choose_monster_slay"
                    self.action_required["id"] = player_id
                    self.pending_required_choice = {
                        "kind": "immediate_slay",
                        "stage": "pick_monster",
                        "player_id": player_id,
                        "source_label": source_label,
                        "resume_kind": resume_kind,
                        "options": list(prc0.get("options") or []),
                        "allow_skip": True,
                    }
                    return
                if act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined to slay (\"{source_label}\")."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_after_immediate_slay(resume_kind)
                    return
                if not act.startswith("slay_pay "):
                    return
                parts = act.split()
                if len(parts) < 4:
                    return
                try:
                    gp = int(parts[1])
                    sp = int(parts[2])
                    mp = int(parts[3])
                except (TypeError, ValueError):
                    return
                event_id_opt = prc0.get("event_id")
                monster_id = int(prc0.get("monster_id", -1)) if event_id_opt is None else None
                if event_id_opt is None and monster_id < 0:
                    return
                target = self._player_by_id(player_id)
                before_tup = self._player_resource_tuple(target) if target else (0, 0, 0, 0)
                try:
                    self.slay_monster(player_id, monster_id, sp, mp, gp, event_id=event_id_opt)
                except ValueError as e:
                    # Payment didn't validate; surface in the log so the player
                    # sees why nothing happened, but keep the prompt open so they
                    # can retry with a corrected payment.
                    self._log_game_event(
                        f"{self._player_label(player_id)} could not slay "
                        f"\"{prc0.get('monster_name', '?')}\" via \"{source_label}\": {e}"
                    )
                    return
                # When the slay was triggered by a citizen harvest payout (resolved at
                # end of harvest), count the net resource delta toward harvest_delta so
                # the empty-harvest bonus_resource_choice gate sees it correctly.
                if resume_kind == "harvest_pending_slay" and target:
                    after_tup = self._player_resource_tuple(target)
                    self._bump_harvest_delta(
                        target,
                        after_tup[0] - before_tup[0],
                        after_tup[1] - before_tup[1],
                        after_tup[2] - before_tup[2],
                        after_tup[3] - before_tup[3],
                    )
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                self._resume_after_immediate_slay(resume_kind)
                return

            if prc0.get("kind") == "domain_boost_monster" and str(current_required).strip() == "choose_monster_strength":
                act = (action or "").strip().lower()
                opts = list(prc0.get("options") or [])
                if not act.startswith("choose_monster "):
                    return
                try:
                    idx = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if idx < 0 or idx >= len(opts):
                    return
                target = self._player_by_id(player_id)
                if not target:
                    return
                mid = int(opts[idx].get("monster_id", -1))
                delta = int(prc0.get("delta", 0) or 0)
                if not self._apply_monster_strength_boost(mid, delta):
                    return
                self._log_game_event(
                    f"{self._player_label(player_id)} chose \"{opts[idx].get('name', '?')}\" for "
                    f"\"{prc0.get('domain_name', 'Domain')}\" (+{delta} strength cost)."
                )
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                return

            if prc0.get("kind") == "domain_self_convert" and str(current_required).strip() == "domain_self_convert":
                act = (action or "").strip().lower()
                if player_id != prc0.get("player_id"):
                    return
                ctx = prc0.get("context", "domain_activation")
                if act == "skip":
                    self.pending_required_choice = None
                    self.action_required["id"] = self.game_id
                    self.action_required["action"] = ""
                    if ctx == "action_end_queue":
                        self.pending_action_end_queue.pop(0) if self.pending_action_end_queue else None
                        if not self._drain_action_end_manipulate_queue():
                            pass  # advance_tick handles turn end
                    else:
                        self._resume_after_domain_activation_follow_up()
                    return
                if act != "confirm_self_convert":
                    return
                kv = prc0.get("kv") or {}
                pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
                target = self._player_by_id(player_id)
                if not target or not pay_k or pay_n <= 0:
                    return
                if not self._player_can_afford_self_convert_resources(target, pay_k, pay_n):
                    return
                before = self._player_scores_line(target)
                self._apply_self_convert_kv_to_player(target, kv)
                after = self._player_scores_line(target)
                self._log_game_event(
                    f"{self._player_label(player_id)} confirmed \"{prc0.get('domain_name', 'Domain')}\" trade; scores {before} -> {after}"
                )
                self.pending_required_choice = None
                self.action_required["id"] = self.game_id
                self.action_required["action"] = ""
                if ctx == "action_end_queue":
                    self.pending_action_end_queue.pop(0) if self.pending_action_end_queue else None
                    if not self._drain_action_end_manipulate_queue():
                        pass  # advance_tick handles turn end
                else:
                    self._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "domain_manipulate_player" and str(current_required).strip() == "choose_player":
                act = (action or "").strip().lower()
                from_activation = bool(prc0.get("from_activation"))
                if prc0.get("allow_skip") and act == "skip":
                    if not from_activation and self.pending_action_end_queue:
                        self.pending_action_end_queue.pop(0)
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    if from_activation:
                        self._resume_after_domain_activation_follow_up()
                    elif not self._drain_action_end_manipulate_queue():
                        self.action_required["id"] = self.game_id
                        self.action_required["action"] = ""
                    return
                opts = list(prc0.get("options") or [])
                if not act.startswith("choose_player "):
                    return
                try:
                    idx = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if idx < 0 or idx >= len(opts):
                    return
                item = prc0.get("item") or {}
                tid = opts[idx].get("player_id")
                self._apply_manipulate_player_choice(player_id, tid, item)
                if not from_activation and self.pending_action_end_queue:
                    self.pending_action_end_queue.pop(0)
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                if from_activation:
                    self._resume_after_domain_activation_follow_up()
                elif not self._drain_action_end_manipulate_queue():
                    self.action_required["id"] = self.game_id
                    self.action_required["action"] = ""
                return

            if prc0.get("kind") == "monster_flip_citizen_targeted" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if prc0.get("allow_skip") and act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined to flip a citizen."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    return
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self._player_by_id(target_pid)
                if not target:
                    return
                citizen_opts = []
                for i, c in enumerate(list(getattr(target, "owned_citizens", []) or [])):
                    if getattr(c, "is_flipped", False):
                        continue
                    citizen_opts.append({
                        "token": "citizen.owned",
                        "idx": i,
                        "name": getattr(c, "name", "?"),
                        "citizen_id": int(getattr(c, "citizen_id", -1)),
                    })
                if not citizen_opts:
                    self._log_game_event(
                        f"{self._player_label(player_id)} could not flip a citizen from "
                        f"{self._player_label(target_pid)} (no eligible citizens); effect lost."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    return
                self.pending_required_choice = {
                    "kind": "monster_flip_citizen_targeted",
                    "player_id": player_id,
                    "stage": "citizen",
                    "target_player_id": target_pid,
                    "options": citizen_opts,
                    "allow_skip": bool(prc0.get("allow_skip")),
                }
                self.action_required["id"] = player_id
                self.action_required["action"] = "choose_owned_card"
                self._log_game_event(
                    f"{self._player_label(player_id)} chose {self._player_label(target_pid)} "
                    f"and is now picking a citizen to flip."
                )
                return

            if prc0.get("kind") == "monster_flip_citizen_targeted" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if prc0.get("allow_skip") and act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined to flip a citizen."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    return
                if not act.startswith("choose_owned_card "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = prc0.get("target_player_id")
                target = self._player_by_id(target_pid)
                if not target:
                    return
                src_idx = int(opts[sel].get("idx", -1))
                owned = list(getattr(target, "owned_citizens", []) or [])
                if src_idx < 0 or src_idx >= len(owned):
                    return
                citizen = owned[src_idx]
                if getattr(citizen, "is_flipped", False):
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    return
                self._citizen_set_flipped(citizen, True)
                self._log_game_event(
                    f"{self._player_label(player_id)} flipped citizen "
                    f"\"{getattr(citizen, 'name', '?')}\" face-down on "
                    f"{self._player_label(target_pid)}'s tableau."
                )
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                return

            if prc0.get("kind") == "banish_player_citizen" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self._player_by_id(target_pid)
                if not target:
                    return
                citizen_opts = []
                for i, c in enumerate(list(getattr(target, "owned_citizens", []) or [])):
                    citizen_opts.append({
                        "token": "citizen.owned",
                        "idx": i,
                        "name": getattr(c, "name", "?"),
                        "citizen_id": int(getattr(c, "citizen_id", -1)),
                    })
                if not citizen_opts:
                    self._log_game_event(
                        f"{self._player_label(player_id)} could not banish a citizen from "
                        f"{self._player_label(target_pid)} (no citizens); effect lost."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_after_domain_activation_follow_up()
                    return
                self.pending_required_choice = {
                    "kind": "banish_player_citizen",
                    "player_id": player_id,
                    "stage": "citizen",
                    "target_player_id": target_pid,
                    "options": citizen_opts,
                }
                self.action_required["id"] = player_id
                self.action_required["action"] = "choose_owned_card"
                self._log_game_event(
                    f"{self._player_label(player_id)} chose {self._player_label(target_pid)} "
                    f"and is now picking a citizen to banish (Sunder Bay)."
                )
                return

            if prc0.get("kind") == "banish_player_citizen" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose_owned_card "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = prc0.get("target_player_id")
                target = self._player_by_id(target_pid)
                if not target:
                    return
                src_idx = int(opts[sel].get("idx", -1))
                owned = list(getattr(target, "owned_citizens", []) or [])
                if src_idx < 0 or src_idx >= len(owned):
                    return
                citizen = owned[src_idx]
                citizen_name = getattr(citizen, "name", "?")
                target.owned_citizens.pop(src_idx)
                self._citizen_set_flipped(citizen, False)
                self.banish_pile.append(citizen)
                self._log_game_event(
                    f"{self._player_label(player_id)} banished citizen \"{citizen_name}\" "
                    f"from {self._player_label(target_pid)}'s tableau (Sunder Bay)."
                )
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                self._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "banish_random_player_monster" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self._player_by_id(target_pid)
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                if not target:
                    self._resume_after_domain_activation_follow_up()
                    return
                monsters = list(getattr(target, "owned_monsters", []) or [])
                if not monsters:
                    self._log_game_event(
                        f"{self._player_label(target_pid)} had no monsters to banish (Wandering Flame)."
                    )
                    self._resume_after_domain_activation_follow_up()
                    return
                idx = random.randrange(len(monsters))
                banished = monsters.pop(idx)
                target.owned_monsters = monsters
                self.banish_pile.append(banished)
                self._log_game_event(
                    f"{self._player_label(player_id)} banished \"{getattr(banished, 'name', '?')}\" "
                    f"from {self._player_label(target_pid)}'s tableau at random (Wandering Flame)."
                )
                self._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "domain_take_owned" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                domain_name = prc0.get("domain_name", "Domain")
                if prc0.get("allow_skip") and act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined activation effect on \"{domain_name}\"."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_after_domain_activation_follow_up()
                    return
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self._player_by_id(target_pid)
                active = self._player_by_id(player_id)
                if not target or not active:
                    return
                card_kind = prc0.get("card_kind")
                pick = (prc0.get("pick") or "random").lower()
                attr = "owned_monsters" if card_kind == "monster" else "owned_citizens"
                owned = list(getattr(target, attr, []) or [])
                if not owned:
                    self._log_game_event(
                        f"{self._player_label(player_id)} could not steal a {card_kind} from "
                        f"{self._player_label(target_pid)} via \"{domain_name}\" "
                        f"(no {card_kind}s to take); activation effect lost."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_after_domain_activation_follow_up()
                    return
                if pick == "random":
                    src_idx = random.randrange(len(owned))
                else:
                    src_idx = 0
                card = owned[src_idx]
                card_label = getattr(card, "name", "?")
                del getattr(target, attr)[src_idx]
                getattr(active, attr).append(card)
                if card_kind == "monster":
                    target.owned_monster_attributes = self.owned_monster_attributes(target_pid)
                    active.owned_monster_attributes = self.owned_monster_attributes(player_id)
                self._log_game_event(
                    f"{self._player_label(player_id)} stole {card_kind} \"{card_label}\" from "
                    f"{self._player_label(target_pid)} via \"{domain_name}\"."
                )
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                self._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "banish_owned_card" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                card_kind = prc0.get("card_kind")
                if prc0.get("allow_skip") and act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined to banish a {card_kind}."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_payout_continuation()
                    return
                if not act.startswith("choose_owned_card "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                opts = list(prc0.get("options") or [])
                if sel < 0 or sel >= len(opts):
                    return
                src_idx = int(opts[sel].get("idx", -1))
                card_label = opts[sel].get("name", "?")
                player = self._player_by_id(player_id)
                if not player:
                    return
                if card_kind == "citizen":
                    banished = self._banish_owned_citizen(player, src_idx)
                else:
                    banished = None
                if not banished:
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_payout_continuation()
                    return
                self._log_game_event(
                    f"{self._player_label(player_id)} banished {card_kind} "
                    f"\"{card_label}\" to the banish pile."
                )
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                self._resume_payout_continuation()
                return

            if prc0.get("kind") == "banish_center_card" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                card_kind = prc0.get("card_kind")
                if prc0.get("allow_skip") and act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined to banish a center-stack {card_kind}."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_payout_continuation()
                    return
                if not act.startswith("choose_owned_card "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                opts = list(prc0.get("options") or [])
                if sel < 0 or sel >= len(opts):
                    return
                stack_idx = int(opts[sel].get("idx", -1))
                card_label = opts[sel].get("name", "?")
                if card_kind == "citizen":
                    banished = self._banish_center_citizen(stack_idx)
                else:
                    banished = None
                if not banished:
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_payout_continuation()
                    return
                self._log_game_event(
                    f"{self._player_label(player_id)} banished center-stack {card_kind} "
                    f"\"{card_label}\" to the banish pile."
                )
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                self._resume_payout_continuation()
                return

            if prc0.get("kind") == "banish_roll_minion" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined to banish a Minion (The Northern Wall)."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    return
                if not act.startswith("choose_owned_card "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                opts = list(prc0.get("options") or [])
                if sel < 0 or sel >= len(opts):
                    return
                stack_idx = int(opts[sel].get("idx", -1))
                card_label = opts[sel].get("name", "?")
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                banished = self._banish_center_monster(stack_idx)
                if banished:
                    self._log_game_event(
                        f"{self._player_label(player_id)} banished Minion \"{card_label}\" "
                        f"from the center (The Northern Wall)."
                    )
                return

            if prc0.get("kind") == "domain_return_owned" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                domain_name = prc0.get("domain_name", "Domain")
                if prc0.get("allow_skip") and act == "skip":
                    self._log_game_event(
                        f"{self._player_label(player_id)} declined activation effect on \"{domain_name}\"."
                    )
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._resume_after_domain_activation_follow_up()
                    return
                if not act.startswith("choose_owned_card "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                opts = list(prc0.get("options") or [])
                if sel < 0 or sel >= len(opts):
                    return
                target = self._player_by_id(player_id)
                if not target:
                    return
                opt = opts[sel]
                card_kind = prc0.get("card_kind")
                src_idx = int(opt.get("idx", -1))
                card_label = opt.get("name", "?")
                if card_kind == "monster":
                    owned = list(getattr(target, "owned_monsters", []) or [])
                    if src_idx < 0 or src_idx >= len(owned):
                        return
                    monster = owned[src_idx]
                    if not self._return_monster_to_stack(monster):
                        self._log_game_event(
                            f"{self._player_label(player_id)} could not return monster \"{card_label}\" "
                            f"(unknown area mapping); activation effect lost."
                        )
                        self.action_required["action"] = ""
                        self.action_required["id"] = self.game_id
                        self.pending_required_choice = None
                        self._resume_after_domain_activation_follow_up()
                        return
                    del target.owned_monsters[src_idx]
                    target.owned_monster_attributes = self.owned_monster_attributes(player_id)
                elif card_kind == "citizen":
                    owned = list(getattr(target, "owned_citizens", []) or [])
                    if src_idx < 0 or src_idx >= len(owned):
                        return
                    citizen = owned[src_idx]
                    if not self._return_citizen_to_stack(citizen):
                        self._log_game_event(
                            f"{self._player_label(player_id)} could not return citizen \"{card_label}\" "
                            f"(invalid roll mapping); activation effect lost."
                        )
                        self.action_required["action"] = ""
                        self.action_required["id"] = self.game_id
                        self.pending_required_choice = None
                        self._resume_after_domain_activation_follow_up()
                        return
                    del target.owned_citizens[src_idx]
                else:
                    return
                res = (prc0.get("resource") or "").strip().lower()
                amount = int(prc0.get("amount", 0) or 0)
                before = self._player_scores_line(target)
                if amount > 0:
                    if res == "g":
                        target.gold_score = int(target.gold_score) + amount
                        self._bump_harvest_delta(target, amount, 0, 0, 0)
                    elif res == "s":
                        target.strength_score = int(target.strength_score) + amount
                        self._bump_harvest_delta(target, 0, amount, 0, 0)
                    elif res == "m":
                        target.magic_score = int(target.magic_score) + amount
                        self._bump_harvest_delta(target, 0, 0, amount, 0)
                    elif res == "v":
                        target.victory_score = int(getattr(target, "victory_score", 0)) + amount
                        self._bump_harvest_delta(target, 0, 0, 0, amount)
                after = self._player_scores_line(target)
                self._log_game_event(
                    f"{self._player_label(player_id)} returned {card_kind} \"{card_label}\" via "
                    f"\"{domain_name}\"; scores {before} -> {after}"
                )
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                self._resume_after_domain_activation_follow_up()
                return

            # Resolve a blocking "choose ..." special payout prompt.
            if str(current_required).strip().lower().startswith("choose "):
                prc = getattr(self, "pending_required_choice", None) or {}
                normalized, options = self._normalize_choose_command(current_required)
                if prc.get("kind") == "special_payout_choose":
                    options = list(prc.get("options") or [])
                else:
                    options = self._expand_choose_options_for_prompt(
                        self._filter_unavailable_choose_options(options)
                    )
                if not options:
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    self._maybe_resume_harvest_prompt()
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose "):
                    return
                try:
                    idx = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if idx < 0 or idx >= len(options):
                    return
                opt = options[idx]
                target = self._player_by_id(player_id)
                if not target:
                    return
                before = self._player_scores_line(target)
                if not self._apply_choose_option(player_id, opt):
                    return
                after = self._player_scores_line(target)
                self._log_game_event(
                    f"{self._player_label(player_id)} chose ({idx + 1}/{len(options)}) from \"{normalized}\": "
                    f"{self._describe_choose_option(opt)}; scores {before} -> {after}"
                )
                # Clear the prompt, then chain any remaining compound legs, and finally
                # resume harvest automation if applicable. If the continuation itself
                # opens a new prompt, harvest resume will see action_required set and
                # back off naturally.
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                if getattr(self, "pending_required_choice", None):
                    self.pending_required_choice = None
                self._resume_payout_continuation()
                # If we're in the post-finalize bonus-drain phase (Herald-style
                # `no_payout` activations open a regular `choose` prompt here),
                # pop this player and fire the next pending bonus.
                if (
                    self.phase == "harvest"
                    and getattr(self, "harvest_processed", False)
                    and (self.action_required.get("action") or "") == ""
                    and self.pending_harvest_choices
                    and self.pending_harvest_choices[0] == player_id
                ):
                    self.pending_harvest_choices.pop(0)
                    if self.pending_harvest_choices:
                        self._activate_finalize_bonus_for(self.pending_harvest_choices[0])
                        return
                self._maybe_resume_harvest_prompt()
                return

            self.action_required["action"] = action
            self.action_required["id"] = self.game_id

    def submit_concurrent_action(self, player_id, response, kind=None):
        """
        Record one player's response to the active concurrent action.

        - `kind`, if provided, must match the active concurrent_action.kind
          (sanity check against stale clients).
        - The handler's apply() runs immediately for this player; if it raises
          ValueError the response is rejected and the player remains pending.
        - When the last pending player responds, the handler's finalize() runs
          and concurrent_action is cleared. If the game was sitting in setup,
          we advance the engine so it lands on the next actionable phase.
        """
        ca = getattr(self, "concurrent_action", None) or None
        if not ca:
            raise ValueError("No concurrent action is pending.")
        if kind and kind != ca.get("kind"):
            raise ValueError(
                f"Concurrent action kind mismatch (expected {ca.get('kind')!r}, got {kind!r})."
            )
        pending = ca.get("pending") or []
        if player_id not in pending:
            raise ValueError("You have no pending response in this concurrent action.")
        handler = CONCURRENT_HANDLERS.get(ca.get("kind"))
        if not handler:
            raise ValueError(f"Unknown concurrent action kind: {ca.get('kind')!r}.")

        handler.apply(self, player_id, response)
        self._log_game_event(
            f"{self._player_label(player_id)} submitted ({ca.get('kind')})."
        )
        ca.setdefault("responses", {})[player_id] = response
        ca["pending"] = [pid for pid in pending if pid != player_id]
        ca.setdefault("completed", []).append(player_id)

        if not ca["pending"]:
            self._log_game_event(f"All players finished: {ca.get('kind')}.")
            handler.finalize(self)
            self.concurrent_action = None
            # Drive the engine forward after the concurrent action resolves.
            if self.phase == "setup":
                # Setup stall: advance until the first actionable state.
                while self.advance_tick():
                    if self.phase == "action":
                        break
            else:
                # Mid-game concurrent action (e.g. Cursed Cavern flip during action phase):
                # if the active player spent their last action before the concurrent prompt,
                # finish_turn_if_no_actions_remaining will advance the turn now that the
                # block is cleared. If they still have actions, this is a no-op.
                self.finish_turn_if_no_actions_remaining()

    def update_payout_for_role(self, role_name, player_id, payout, split_command):
        role_count = 0
        for player in self.player_list:
            if player.player_id == player_id:
                role_count = player.calc_roles()[role_name]
                break
        match split_command[2]:
            case 'g':
                payout[0] = int(split_command[3]) * role_count
            case 's':
                payout[1] = int(split_command[3]) * role_count
            case 'm':
                payout[2] = int(split_command[3]) * role_count
            case 'v':
                payout[3] = int(split_command[3]) * role_count
            case _:
                payout[0] = -9999

    def _player_citizen_role_totals(self, player):
        totals = {"shadow": 0, "holy": 0, "soldier": 0, "worker": 0}
        for c in list(getattr(player, "owned_citizens", []) or []):
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
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
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
        for d in list(getattr(player, "owned_domains", []) or []):
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
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
        return False

    def hire_citizen(self, player_id, citizen_id, gp=0, mp=0, sp=0):
        """
        Hire the top/accessible citizen from a stack.

        Gold cost scales by +1 for each already-owned face-up card with the same
        name, counting owned citizens and starting cards. Flipped citizens stay
        known on the tableau, but do not count for duplicate citizen costs.

        Payment is (gold, magic, strength); only gold and magic may be used (strength must be 0).
        """
        gp, sp, mp = _n(gp), _n(sp), _n(mp)

        for citizen_stack in self.citizen_grid:
            if not citizen_stack:
                continue
            top = citizen_stack[-1]
            if getattr(top, "citizen_id", None) is None:
                continue  # Event/Exhausted placeholder — not hirable
            if int(getattr(top, "citizen_id", -1)) != int(citizen_id) or not getattr(top, "is_accessible", False):
                continue

            player = None
            for p in self.player_list:
                if p.player_id == player_id:
                    player = p
                    break
            if not player:
                raise ValueError("Player not found.")

            owned_same_name = 0
            has_emerald = self._player_has_action_effect_flag(player, "action.emeraldstronghold")
            if not has_emerald:
                for c in getattr(player, "owned_citizens", []) or []:
                    if getattr(c, "is_flipped", False):
                        continue
                    if getattr(c, "name", None) == top.name:
                        owned_same_name += 1
                for s in getattr(player, "owned_starters", []) or []:
                    if getattr(s, "name", None) == top.name:
                        owned_same_name += 1

            scaled_cost = int(getattr(top, "gold_cost", 0) or 0) + int(owned_same_name)
            if self._player_has_action_effect_flag(player, "action.defiantridge"):
                scaled_cost = max(0, scaled_cost - 1)
            has_shilina = self._player_has_action_effect_flag(player, "action.newshilinatower")
            _validate_hire_or_domain_gold_payment(player, scaled_cost, gp, sp, mp, allow_strength=has_shilina)

            before = self._player_scores_line(player)
            player.gold_score = player.gold_score - gp
            player.magic_score = player.magic_score - mp
            player.strength_score = player.strength_score - sp
            hired = citizen_stack.pop(-1)
            self._citizen_set_flipped(hired, False)
            player.owned_citizens.append(hired)

            self._finalize_citizen_stack_after_claiming_top(citizen_stack)
            after = self._player_scores_line(player)
            pay = self._format_resource_payment(gp, sp, mp)
            self._log_game_event(
                f"{self._player_label(player_id)} hired citizen \"{top.name}\" ({pay}); scores {before} -> {after}"
            )
            self._apply_action_event_gain_passives(player, "hire")
            return

        raise ValueError("Citizen not available to hire.")

    def slay_monster(self, player_id, monster_id, sp=0, mp=0, gp=0, event_id=None):
        gp, sp, mp = _n(gp), _n(sp), _n(mp)
        payout = [0, 0, 0, 0]

        # Regular monsters only live in monster_grid.
        # Events can land on any grid depending on which stack emptied first.
        candidate_grids = (
            [self.monster_grid, self.citizen_grid, self.domain_grid]
            if event_id is not None
            else [self.monster_grid]
        )

        for grid in candidate_grids:
          for monster_stack in grid:
            if not monster_stack:
                continue
            top = monster_stack[-1]
            is_event_card = isinstance(top, Event)
            # Match by monster_id for regular monsters, or event_id for Event cards.
            if is_event_card:
                if event_id is not None:
                    if int(getattr(top, "event_id", -1)) != int(event_id):
                        continue
                else:
                    continue
            else:
                # When searching for an event, skip all non-Event cards.
                if event_id is not None:
                    continue
                if int(getattr(top, "monster_id", -1)) != int(monster_id):
                    continue
            if not getattr(top, "is_accessible", False):
                continue

            player = None
            for p in self.player_list:
                if p.player_id == player_id:
                    player = p
                    break
            if not player:
                raise ValueError("Player not found.")

            # Compute effective costs including any event-applied extra costs.
            effective_strength_cost = (
                int(getattr(top, "strength_cost", 0) or 0)
                + int(getattr(top, "extra_strength_cost", 0) or 0)
            )
            effective_magic_cost = (
                int(getattr(top, "magic_cost", 0) or 0)
                + int(getattr(top, "extra_magic_cost", 0) or 0)
            )
            effective_gold_cost = int(getattr(top, "extra_gold_cost", 0) or 0)
            if self._player_has_action_effect_flag(player, "action.fortskyler"):
                effective_strength_cost = max(0, effective_strength_cost - 1)

            _validate_monster_slay_payment(
                player, effective_strength_cost, effective_magic_cost, effective_gold_cost, gp, sp, mp
            )

            before = self._player_scores_line(player)
            monster_to_add = monster_stack.pop(-1)
            player.gold_score = player.gold_score - gp
            player.strength_score = player.strength_score - sp
            player.magic_score = player.magic_score - mp
            player.owned_monsters.append(monster_to_add)

            if top.has_special_reward:
                self._immediate_slay_source_label = getattr(top, "name", "Monster")
                try:
                    payout = self.execute_special_payout(top.special_reward, player_id)
                finally:
                    self._immediate_slay_source_label = None
                if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
                    if not (isinstance(self.action_required, dict) and self.action_required.get("action")):
                        payout = [0, 0, 0, 0]
            payout[0] = payout[0] + int(getattr(top, "gold_reward", 0) or 0)
            payout[1] = payout[1] + int(getattr(top, "strength_reward", 0) or 0)
            payout[2] = payout[2] + int(getattr(top, "magic_reward", 0) or 0)
            payout[3] = payout[3] + int(getattr(top, "vp_reward", 0) or 0)
            player.gold_score = player.gold_score + payout[0]
            player.strength_score = player.strength_score + payout[1]
            player.magic_score = player.magic_score + payout[2]
            player.victory_score = player.victory_score + payout[3]
            player.owned_monster_attributes = self.owned_monster_attributes(player_id)

            if monster_stack:
                monster_stack[-1].toggle_accessibility(True)
            elif is_event_card:
                # Event already counted toward exhausted_count when it was placed.
                # Just drop a static placeholder so the slot still shows the exhausted back.
                from cards import Exhausted as _Exhausted
                placeholder = _Exhausted(int(self.exhausted_count))
                placeholder.toggle_visibility(True)
                monster_stack.append(placeholder)
            elif self.exhausted_stack:
                exhausted = self.exhausted_stack.pop()
                monster_stack.append(exhausted)
                # Always count the slot as exhausted, whether the drawn card is a plain
                # Exhausted token or an Event card (Events ARE exhausted cards).
                self.exhausted_count = int(self.exhausted_count) + 1
                if isinstance(exhausted, Event):
                    exhausted.toggle_visibility(True)
                    exhausted.toggle_accessibility(True)
            after = self._player_scores_line(player)
            pay = self._format_resource_payment(gp, sp, mp)
            self._log_game_event(
                f"{self._player_label(player_id)} slew \"{monster_to_add.name}\" ({pay}); scores {before} -> {after}"
            )
            self._apply_action_event_gain_passives(player, "slay")
            return

        raise ValueError("Monster not available to slay.")

    def _reveal_hidden_domain_stack_tops(self):
        """Face up domain stack tops that were left hidden after a purchase (until turn end)."""
        for domain_stack in getattr(self, "domain_grid", None) or []:
            if not domain_stack:
                continue
            top = domain_stack[-1]
            if getattr(top, "domain_id", None) is None:
                continue
            if getattr(top, "is_visible", True):
                continue
            top.toggle_visibility(True)
            top.toggle_accessibility(True)

    def build_domain(self, player_id, domain_id, gp=0, mp=0, sp=0):
        gp, sp, mp = _n(gp), _n(sp), _n(mp)

        for domain_stack in self.domain_grid:
            if not domain_stack:
                continue
            top = domain_stack[-1]
            if getattr(top, "domain_id", None) is None:
                continue  # Event/Exhausted placeholder — not buildable
            if int(getattr(top, "domain_id", -1)) != int(domain_id):
                continue
            if not getattr(top, "is_accessible", False):
                continue
            if not getattr(top, "is_visible", True):
                continue

            player = None
            for p in self.player_list:
                if p.player_id == player_id:
                    player = p
                    break
            if not player:
                raise ValueError("Player not found.")

            # Domain role prerequisites must be satisfied by owned citizens.
            # Starters and already-owned domains do not count toward this gate.
            have = self._player_citizen_role_totals(player)
            req_shadow = int(getattr(top, "shadow_count", 0) or 0)
            req_holy = int(getattr(top, "holy_count", 0) or 0)
            req_soldier = int(getattr(top, "soldier_count", 0) or 0)
            req_worker = int(getattr(top, "worker_count", 0) or 0)
            missing = []
            if have["shadow"] < req_shadow:
                missing.append(f"shadow {have['shadow']}/{req_shadow}")
            if have["holy"] < req_holy:
                missing.append(f"holy {have['holy']}/{req_holy}")
            if have["soldier"] < req_soldier:
                missing.append(f"soldier {have['soldier']}/{req_soldier}")
            if have["worker"] < req_worker:
                missing.append(f"worker {have['worker']}/{req_worker}")
            if missing:
                raise ValueError(
                    "Domain role requirements not met (citizens only): " + ", ".join(missing)
                )

            gold_cost = int(getattr(top, "gold_cost", 0) or 0)
            has_pratchett = self._player_has_action_effect_flag(player, "action.pratchettsplateau")
            if has_pratchett:
                gold_cost = max(0, gold_cost - 1)
            _validate_hire_or_domain_gold_payment(player, gold_cost, gp, sp, mp)

            before = self._player_scores_line(player)
            player.gold_score = player.gold_score - gp
            player.magic_score = player.magic_score - mp
            bought = domain_stack.pop(-1)
            bought.acquired_turn_number = int(self.turn_number)
            player.owned_domains.append(bought)

            vp_gain = int(getattr(bought, "vp_reward", 0) or 0)
            if vp_gain:
                player.victory_score = int(getattr(player, "victory_score", 0) or 0) + vp_gain
                self._bump_harvest_delta(player, 0, 0, 0, vp_gain)

            if not domain_stack and self.exhausted_stack:
                exhausted = self.exhausted_stack.pop()
                if isinstance(exhausted, Event):
                    exhausted.toggle_visibility(True)
                    exhausted.toggle_accessibility(True)
                domain_stack.append(exhausted)
                self.exhausted_count = int(self.exhausted_count) + 1
            self._apply_domain_activation_effect(player, bought)
            after = self._player_scores_line(player)
            pay = self._format_resource_payment(gp, sp, mp)
            self._log_game_event(
                f"{self._player_label(player_id)} bought domain \"{top.name}\" ({pay}); scores {before} -> {after}"
            )
            return

        raise ValueError("Domain not available to purchase.")

    def take_resource(self, player_id, resource):
        """
        Spend a standard action to gain +1 gold, strength, or magic (player's choice).
        """
        choice = (resource or "").strip().lower()
        if choice not in ("gold", "strength", "magic"):
            raise ValueError('resource must be "gold", "strength", or "magic".')

        player = None
        for p in self.player_list:
            if p.player_id == player_id:
                player = p
                break
        if not player:
            raise ValueError("Player not found.")

        before = self._player_scores_line(player)
        if choice == "gold":
            player.gold_score = int(getattr(player, "gold_score", 0)) + 1
        elif choice == "strength":
            player.strength_score = int(getattr(player, "strength_score", 0)) + 1
        else:
            player.magic_score = int(getattr(player, "magic_score", 0)) + 1

        after = self._player_scores_line(player)
        self._log_game_event(
            f"{self._player_label(player_id)} took +1 {choice} (standard action; no gold/strength/magic cost); "
            f"scores {before} -> {after}"
        )

    def action_phase(self):
        return

    def play_turn(self):
        self.roll_phase()
        self.harvest_phase()
        self.action_phase()

    def _check_end_game_condition(self):
        """Returns a reason string if any end condition is met, else None."""
        from cards import Exhausted

        def _depleted(stack):
            """A stack counts as depleted if it is empty or holds only a
            non-purchasable placeholder (Event or Exhausted token)."""
            if not stack:
                return True
            top = stack[-1]
            return isinstance(top, (Event, Exhausted))

        if all(_depleted(s) for s in self.monster_grid):
            return "all monsters slain"
        if all(_depleted(s) for s in self.domain_grid):
            return "all domains built"
        if int(self.exhausted_count) >= len(self.player_list) * 2:
            return "exhausted stacks filled"
        return None

    def _build_final_result(self, scores):
        """Summarize win / tie-break / true-tie outcome for clients and logs."""
        if not scores:
            return None
        top_vp = int(scores[0]["total_vp"])
        vp_tied = [s for s in scores if int(s["total_vp"]) == top_vp]
        if len(vp_tied) == 1:
            w = vp_tied[0]
            return {
                "kind": "win",
                "headline": f"{w['name']} wins!",
                "detail": None,
                "winner_player_ids": [w["player_id"]],
            }
        min_tableau = min(int(s["tableau_size"]) for s in vp_tied)
        winners = [s for s in vp_tied if int(s["tableau_size"]) == min_tableau]
        if len(winners) == 1:
            w = winners[0]
            losers = [s for s in vp_tied if s["player_id"] != w["player_id"]]
            loser_bits = ", ".join(
                f"{s['name']} ({int(s['tableau_size'])} cards)" for s in losers
            )
            return {
                "kind": "tiebreak",
                "headline": f"{w['name']} wins on tie-break!",
                "detail": (
                    f"Tied at {top_vp} VP; {w['name']} had the smaller tableau "
                    f"({int(w['tableau_size'])} cards vs {loser_bits})."
                ),
                "winner_player_ids": [w["player_id"]],
            }
        names = ", ".join(s["name"] for s in winners)
        tableau_n = int(winners[0]["tableau_size"])
        return {
            "kind": "tie",
            "headline": "Tie game!",
            "detail": (
                f"{names} tied at {top_vp} VP with {tableau_n} tableau cards each."
            ),
            "winner_player_ids": [s["player_id"] for s in winners],
        }

    def _calculate_final_scores(self):
        """Compute final VP for each player including Duke multipliers. Returns ranked list."""
        self.unflip_all_citizens_for_final_scoring()
        scores = []
        for player in self.player_list:
            duke_vp = 0
            duke_summary = None
            duke_vp_breakdown = []

            if player.owned_dukes:
                duke = player.owned_dukes[0]
                roles = player.calc_roles()
                monster_attrs = self.owned_monster_attributes(player.player_id)

                def _res(score, divisor):
                    d = int(divisor or 0)
                    return int(score) // d if d > 0 else 0

                def _cnt(count, multiplier):
                    return int(count) * int(multiplier or 0)

                def _line(label, vp, detail):
                    v = int(vp)
                    if v:
                        duke_vp_breakdown.append({"label": label, "vp": v, "detail": detail})

                gsc = int(player.gold_score)
                gdiv = int(duke.gold_multiplier or 0)
                gvp = _res(player.gold_score, duke.gold_multiplier)
                _line("Gold", gvp, f"{gsc} gold ÷ {gdiv}" if gdiv > 0 else None)

                ssc = int(player.strength_score)
                sdiv = int(duke.strength_multiplier or 0)
                svp = _res(player.strength_score, duke.strength_multiplier)
                _line("Strength", svp, f"{ssc} strength ÷ {sdiv}" if sdiv > 0 else None)

                msc = int(player.magic_score)
                mdiv = int(duke.magic_multiplier or 0)
                mvp = _res(player.magic_score, duke.magic_multiplier)
                _line("Magic", mvp, f"{msc} magic ÷ {mdiv}" if mdiv > 0 else None)

                shc = int(roles["shadow_count"])
                shm = int(duke.shadow_multiplier or 0)
                shvp = _cnt(shc, duke.shadow_multiplier)
                _line("Shadow role", shvp, f"{shc} × {shm}" if shm else None)

                hoc = int(roles["holy_count"])
                hom = int(duke.holy_multiplier or 0)
                hovp = _cnt(hoc, duke.holy_multiplier)
                _line("Holy role", hovp, f"{hoc} × {hom}" if hom else None)

                soc = int(roles["soldier_count"])
                som = int(duke.soldier_multiplier or 0)
                sovp = _cnt(soc, duke.soldier_multiplier)
                _line("Soldier role", sovp, f"{soc} × {som}" if som else None)

                woc = int(roles["worker_count"])
                wom = int(duke.worker_multiplier or 0)
                wovp = _cnt(woc, duke.worker_multiplier)
                _line("Worker role", wovp, f"{woc} × {wom}" if wom else None)

                nmon = len(player.owned_monsters)
                mm = int(duke.monster_multiplier or 0)
                mmonvp = _cnt(nmon, duke.monster_multiplier)
                _line("Monsters", mmonvp, f"{nmon} × {mm}" if mm else None)

                ncit = len(player.owned_citizens)
                cm = int(duke.citizen_multiplier or 0)
                citvp = _cnt(ncit, duke.citizen_multiplier)
                _line("Citizens", citvp, f"{ncit} × {cm}" if cm else None)

                ndom = len(player.owned_domains)
                dm = int(duke.domain_multiplier or 0)
                domvp = _cnt(ndom, duke.domain_multiplier)
                _line("Domains", domvp, f"{ndom} × {dm}" if dm else None)

                nb = int(monster_attrs.get("Boss", 0))
                bm = int(duke.boss_multiplier or 0)
                bvp = _cnt(nb, duke.boss_multiplier)
                _line("Boss monsters", bvp, f"{nb} × {bm}" if bm else None)

                nmin = int(monster_attrs.get("Minion", 0))
                minm = int(duke.minion_multiplier or 0)
                minvp = _cnt(nmin, duke.minion_multiplier)
                _line("Minion monsters", minvp, f"{nmin} × {minm}" if minm else None)

                nbe = int(monster_attrs.get("Beast", 0))
                bem = int(duke.beast_multiplier or 0)
                bevp = _cnt(nbe, duke.beast_multiplier)
                _line("Beast monsters", bevp, f"{nbe} × {bem}" if bem else None)

                nti = int(monster_attrs.get("Titan", 0))
                tim = int(duke.titan_multiplier or 0)
                tivp = _cnt(nti, duke.titan_multiplier)
                _line("Titan monsters", tivp, f"{nti} × {tim}" if tim else None)

                duke_vp = (
                    gvp + svp + mvp + shvp + hovp + sovp + wovp
                    + mmonvp + citvp + domvp + bvp + minvp + bevp + tivp
                )
                duke_summary = {
                    "duke_id": duke.duke_id,
                    "name": duke.name or "Duke",
                    "card": duke.to_dict(),
                }

            total_vp = int(player.victory_score) + duke_vp
            tableau_size = (
                len(player.owned_starters)
                + len(player.owned_citizens)
                + len(player.owned_domains)
                + len(player.owned_monsters)
                + len(player.owned_dukes)
            )
            scores.append({
                "player_id": player.player_id,
                "name": player.name,
                "base_vp": int(player.victory_score),
                "duke_vp": duke_vp,
                "duke": duke_summary,
                "duke_vp_breakdown": duke_vp_breakdown,
                "total_vp": total_vp,
                "tableau_size": tableau_size,
            })
        scores.sort(key=lambda s: (-s["total_vp"], s["tableau_size"]))
        top_vp = int(scores[0]["total_vp"]) if scores else None
        for rank, s in enumerate(scores):
            s["rank"] = rank + 1
            s["tied_on_vp"] = top_vp is not None and int(s["total_vp"]) == top_vp
        return scores

    def _finalize_game(self):
        """Compute final scores, set phase to game_over, and log the result."""
        self.final_scores = self._calculate_final_scores()
        self.final_result = self._build_final_result(self.final_scores)
        self.phase = "game_over"
        if self.final_scores:
            for s in self.final_scores:
                place = {1: "1st", 2: "2nd", 3: "3rd"}.get(s["rank"], f"{s['rank']}th")
                self._log_game_event(
                    f"{place}: {s['name']} — {s['total_vp']} VP "
                    f"({s['base_vp']} base + {s['duke_vp']} Duke)."
                )
            fr = self.final_result or {}
            headline = fr.get("headline") or f"Game over! {self.final_scores[0]['name']} wins!"
            self._log_game_event(headline)
            detail = fr.get("detail")
            if detail:
                self._log_game_event(detail)

    def end_check(self):
        if self.exhausted_count <= (len(self.player_list) * 2):
            return False

    def prompt(self):
        return
