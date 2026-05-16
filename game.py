import time
import random
from constants import *
from cards import *
import threading
from game_models import Player, LobbyMember, GameMember
from game_setup import load_game_data
from game_serialization import SummaryEncoder, GameObjectEncoder


def _n(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _validate_hire_or_domain_gold_payment(player, scaled_gold_cost, gp, sp, mp):
    gp, sp, mp = _n(gp), _n(sp), _n(mp)
    if gp < 0 or sp < 0 or mp < 0:
        raise ValueError("Invalid payment (negative amounts).")
    if sp != 0:
        raise ValueError("Strength cannot be spent on hiring citizens or building domains.")
    scaled_gold_cost = int(scaled_gold_cost or 0)
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


def _validate_monster_slay_payment(player, strength_cost, magic_min, gp, sp, mp):
    gp, sp, mp = _n(gp), _n(sp), _n(mp)
    if gp != 0:
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
        self.player_list = game_state['player_list']
        self.monster_grid = game_state['monster_grid']
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
        self.exhausted_count = game_state['exhausted_count']
        self.exhausted_stack = list(game_state.get('exhausted_stack') or [])
        self.end_game_triggered = game_state.get('end_game_triggered', False)
        self.final_scores = game_state.get('final_scores', None)
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
        self.last_active_time = 0
        self.game_log = list(game_state.get('game_log') or [])
        self.pending_action_end_queue = list(game_state.get("pending_action_end_queue") or [])
        self.pending_required_choice = game_state.get("pending_required_choice")
        self._silent_harvest_batch = False
        # Between roll and harvest we allow a small "finalization window" where effects (or dev rigging)
        # may legally change the dice. When present, the engine blocks in roll_pending until finalized.
        self.pending_roll = game_state.get('pending_roll') or None

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
                or aa.startswith("choose ")
                or aa.startswith("choose_player")
                or aa.startswith("choose_monster")
                or aa == "domain_self_convert"
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

    def consume_player_action(self, player_id):
        """
        Consume one standard action for the active player.

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

        # If we're blocked on a required choice, no standard actions can be taken.
        if self.action_required and self.action_required.get("id") and self.action_required.get("id") != self.game_id:
            aa = str(self.action_required.get("action", "") or "")
            if self.action_required.get("action") in (
                "bonus_resource_choice",
                "manual_harvest",
                "harvest_optional_exchange",
            ) or aa.startswith("choose ") or aa.startswith("choose_player") or aa.startswith(
                "choose_monster"
            ) or aa == "domain_self_convert":
                return False

        if player_id != self.current_player_id():
            return False

        if self.actions_remaining is None:
            self.actions_remaining = 2
        if int(self.actions_remaining) <= 0:
            return False

        self.actions_remaining = int(self.actions_remaining) - 1
        self.tick_id += 1
        # Keep standard action prompt while actions remain.
        if int(self.actions_remaining) > 0:
            self.action_required["id"] = self.current_player_id()
            self.action_required["action"] = "standard_action"

        return True

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
        # Roll the RNG dice first (display value).
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

        self.pending_roll = None
        # Move into harvest exactly like the old post-roll transition.
        self.phase = "harvest"
        self.harvest_processed = False
        self.harvest_player_order = None
        self.harvest_player_idx = 0
        self.harvest_consumed = {}
        self._harvest_steal_phase_done = False

        # Clear the finalize prompt; harvest/action will set prompts as needed.
        self.action_required["id"] = self.game_id
        self.action_required["action"] = ""
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
            try:
                target = int(kv.get("target", ""))
            except (TypeError, ValueError):
                continue
            if target < 1 or target > 6:
                continue
            cost_spec = kv.get("cost", "")
            if not cost_spec:
                continue
            yield {"domain_name": getattr(d, "name", "Domain"), "target": target, "cost_spec": cost_spec}

    def _resolve_roll_effect_cost(self, player, cost_spec):
        spec = (cost_spec or "").strip().lower()
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
        changed1 = (fd1 != rd1)
        changed2 = (fd2 != rd2)
        if changed1 == changed2:
            return False
        new_value = fd1 if changed1 else fd2
        for effect in self._iter_roll_set_one_die_effects(player):
            if int(effect.get("target", 0) or 0) != int(new_value):
                continue
            cost = self._resolve_roll_effect_cost(player, effect.get("cost_spec"))
            if not cost:
                continue
            g = int(cost.get("gold", 0) or 0)
            if int(getattr(player, "gold_score", 0) or 0) < g:
                continue
            before = self._player_scores_line(player)
            if g:
                player.gold_score = int(player.gold_score) - g
            after = self._player_scores_line(player)
            self._log_game_event(
                f"{self._player_label(player.player_id)} used {effect.get('domain_name')} "
                f"(pay {g} gold) during roll: scores {before} -> {after}"
            )
            return True
        return False

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

    def _harvest_player_id_order_starting_active(self):
        n = len(self.player_list)
        if n == 0:
            return []
        t = int(self.turn_index) % n
        return [self.player_list[(t + i) % n].player_id for i in range(n)]

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
                player.gold_score = int(player.gold_score) + dg
                player.strength_score = int(player.strength_score) + ds
                player.magic_score = int(player.magic_score) + dm
                self._bump_harvest_delta(player, dg, ds, dm, 0)
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
                player.gold_score = int(player.gold_score) + dg
                player.strength_score = int(player.strength_score) + ds
                player.magic_score = int(player.magic_score) + dm
                self._bump_harvest_delta(player, dg, ds, dm, 0)
                cmd = _special_cmd(c, "special_payout_off_turn")
                if getattr(c, "has_special_payout_off_turn", False) or cmd:
                    payout = self.execute_special_payout(cmd or c.special_payout_off_turn, player.player_id)
                    player.gold_score = int(player.gold_score) + payout[0]
                    player.strength_score = int(player.strength_score) + payout[1]
                    player.magic_score = int(player.magic_score) + payout[2]
                    player.victory_score = int(player.victory_score) + payout[3]
                    self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
        finally:
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
        if aa in ("bonus_resource_choice", "manual_harvest", "harvest_optional_exchange", "harvest_steal"):
            return True
        if str(aa).startswith("choose ") or str(aa).startswith("choose_player") or str(aa).startswith("choose_monster"):
            return True
        if str(aa) == "domain_self_convert":
            return True
        return False

    def _harvest_complete_finalize(self):
        self.harvest_processed = True
        self.harvest_player_order = None
        self.harvest_player_idx = 0
        self.harvest_consumed = {}
        self._harvest_steal_phase_done = False
        self.pending_harvest_choices = []
        for p in self.player_list:
            d = getattr(p, "harvest_delta", {}) or {}
            if int(d.get("gold", 0)) == 0 and int(d.get("strength", 0)) == 0 and int(d.get("magic", 0)) == 0:
                self.pending_harvest_choices.append(p.player_id)
        if self.pending_harvest_choices:
            self.action_required["id"] = self.pending_harvest_choices[0]
            self.action_required["action"] = "bonus_resource_choice"
        else:
            self.action_required["id"] = self.game_id
            self.action_required["action"] = ""

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
        options = []
        for res, amt in resource_opts:
            for opp in opponents:
                opp_name = getattr(opp, "name", None) or f"Player {opp.player_id}"
                options.append({
                    "kind": "steal",
                    "victim_id": opp.player_id,
                    "victim_name": opp_name,
                    "resource": res,
                    "amount": amt,
                })
        self.pending_required_choice = {
            "kind": "harvest_steal",
            "player_id": player_id,
            "options": options,
        }
        self.action_required["id"] = player_id
        self.action_required["action"] = "harvest_steal"
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
        for cmd in parts:
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
            return self._execute_manipulate_resources_self_convert_payout(raw, player_id)
        if low.startswith("steal"):
            return self._execute_steal_payout(raw, player_id)
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
        payout = [0, 0, 0, 0]  # gp, sp, mp, vp, todo: citizen, monster, domain
        split_command = (command or "").split()
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
                        area_count = self.owned_monster_attributes(player_id)[third_word]
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
                norm_parts.append(f"<count area {o.get('area')} {o.get('resource')} {o.get('mult')}>")
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
        parts = s.split()
        if len(parts) >= 5 and parts[0].lower() == "count" and parts[1].lower() == "area":
            area = parts[2]
            resource = parts[3].lower()
            try:
                mult = int(parts[4])
            except (TypeError, ValueError):
                return None
            if mult <= 0 or resource not in ("g", "s", "m", "v"):
                return None
            if area not in Constants.areas:
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

    def _prompt_or_apply_self_convert(self, raw, player, domain=None):
        """
        Activation self_convert: optional effects prompt confirm/decline when affordable.
        Non-optional applies immediately when affordable.
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

    def _collect_action_end_manipulate_queue(self, active_player):
        out = []
        for d in list(getattr(active_player, "owned_domains", []) or []):
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            kv = self._parse_manipulate_action_end(getattr(d, "passive_effect", None) or "")
            if not kv:
                continue
            mode = (kv.get("mode") or "").strip().lower()
            if mode not in ("take_from_player", "pay_to_player"):
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
        self._log_game_event(
            f"{self._player_label(active_pid)} end-of-action \"{item.get('domain_name')}\" vs "
            f"{self._player_label(target_pid)}: active {before_a} -> {after_a}; target {before_v} -> {after_v}"
            f"{bank_vp_note}"
        )

    def _apply_harvest_jousting_passive(self, player):
        """Apply automatic harvest-phase domain passives for the active player.

        Accepts DB spellings `harvest.gain_per_owned_citizen_name` and `harvest:gain_per_owned_citizen_name`.
        Format: `<verb> <citizen_name> <resource_letter> <multiplier_per_card>`
        resource_letter: g | s | m | v
        """
        if not player:
            return
        for d in list(getattr(player, "owned_domains", []) or []):
            if self._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            raw = (getattr(d, "passive_effect", None) or "").strip()
            if not raw:
                continue
            parts = raw.split()
            verb = parts[0].strip().lower()
            if verb != "harvest.gain_per_owned_citizen_name":
                continue
            if len(parts) < 4:
                continue
            citizen_name = parts[1]
            res = (parts[2] or "").strip().lower()
            try:
                mult = int(parts[3])
            except (TypeError, ValueError):
                continue
            want = citizen_name.strip().lower()
            n = 0
            for c in list(getattr(player, "owned_citizens", []) or []):
                if getattr(c, "is_flipped", False):
                    continue
                if (getattr(c, "name", "") or "").strip().lower() == want:
                    n += 1
            if n <= 0:
                continue
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
                continue
            before = self._player_scores_line(player)
            player.gold_score = int(player.gold_score) + dg
            player.strength_score = int(player.strength_score) + ds
            player.magic_score = int(player.magic_score) + dm
            player.victory_score = int(player.victory_score) + dv
            self._bump_harvest_delta(player, dg, ds, dm, dv)
            after = self._player_scores_line(player)
            self._log_game_event(
                f"{self._player_label(player.player_id)} harvest passive \"{getattr(d, 'name', 'Domain')}\" "
                f"({citizen_name} x{n}): scores {before} -> {after}"
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
        if low.startswith("manipulate_resources"):
            kv = _parse_domain_effect_kv(effect)
            if (kv.get("mode") or "").strip().lower() == "self_convert":
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
        before = self._player_scores_line(player)
        _prior_action = (self.action_required or {}).get("action", "")
        _prior_concurrent = getattr(self, "concurrent_action", None)
        payout = self.execute_special_payout(effect, player.player_id, auto_apply_single_choice=False)
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

    def owned_monster_attributes(self, player_id):
        return_dict = {attr: 0 for attr in Constants.areas + Constants.types}
        for player in self.player_list:
            if player.player_id == player_id:
                for monster in player.owned_monsters:
                    for area in Constants.areas:
                        if monster.area == area:
                            return_dict[area] += 1
                    for monster_type in Constants.types:
                        if monster.monster_type == monster_type:
                            return_dict[monster_type] += 1

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

                # Pop current pending player and either queue the next, or clear blocking.
                if getattr(self, "pending_harvest_choices", None):
                    if self.pending_harvest_choices and self.pending_harvest_choices[0] == player_id:
                        self.pending_harvest_choices.pop(0)
                if getattr(self, "pending_harvest_choices", None) and self.pending_harvest_choices:
                    self.action_required["id"] = self.pending_harvest_choices[0]
                    self.action_required["action"] = "bonus_resource_choice"
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
                opts_s = list(prc_s.get("options") or [])
                act_s = (action or "").strip().lower()
                if not act_s.startswith("steal "):
                    return
                try:
                    idx_s = int(act_s.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if idx_s < 0 or idx_s >= len(opts_s):
                    return
                opt_s = opts_s[idx_s]
                thief = self._player_by_id(player_id)
                victim = self._player_by_id(opt_s.get("victim_id"))
                self.pending_required_choice = None
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                if thief and victim:
                    res_s = opt_s.get("resource", "g")
                    want_s = int(opt_s.get("amount", 0))
                    score_map = {"g": "gold_score", "s": "strength_score", "m": "magic_score", "v": "victory_score"}
                    attr_s = score_map.get(res_s)
                    if attr_s:
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
                            f"{self._player_label(opt_s.get('victim_id'))}; "
                            f"thief {before_thief} -> {after_thief}, "
                            f"victim {before_victim} -> {after_victim}"
                        )
                self._maybe_resume_harvest_prompt()
                return

            prc0 = getattr(self, "pending_required_choice", None) or {}
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
                if act == "skip":
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
                self._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "domain_manipulate_player" and str(current_required).strip() == "choose_player":
                act = (action or "").strip().lower()
                if prc0.get("allow_skip") and act == "skip":
                    if self.pending_action_end_queue:
                        self.pending_action_end_queue.pop(0)
                    self.action_required["action"] = ""
                    self.action_required["id"] = self.game_id
                    self.pending_required_choice = None
                    if not self._drain_action_end_manipulate_queue():
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
                if self.pending_action_end_queue:
                    self.pending_action_end_queue.pop(0)
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                self.pending_required_choice = None
                if not self._drain_action_end_manipulate_queue():
                    self.action_required["id"] = self.game_id
                    self.action_required["action"] = ""
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
                # Clear the prompt, then resume harvest automation if applicable.
                self.action_required["action"] = ""
                self.action_required["id"] = self.game_id
                if getattr(self, "pending_required_choice", None):
                    self.pending_required_choice = None
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

        Gold cost scales by +1 for each already-owned card with the same name,
        counting both owned citizens and starting cards.

        Payment is (gold, magic, strength); only gold and magic may be used (strength must be 0).
        """
        gp, sp, mp = _n(gp), _n(sp), _n(mp)

        for citizen_stack in self.citizen_grid:
            if not citizen_stack:
                continue
            top = citizen_stack[-1]
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
                    if getattr(c, "name", None) == top.name:
                        owned_same_name += 1
                for s in getattr(player, "owned_starters", []) or []:
                    if getattr(s, "name", None) == top.name:
                        owned_same_name += 1

            scaled_cost = int(getattr(top, "gold_cost", 0) or 0) + int(owned_same_name)
            _validate_hire_or_domain_gold_payment(player, scaled_cost, gp, sp, mp)

            before = self._player_scores_line(player)
            player.gold_score = player.gold_score - gp
            player.magic_score = player.magic_score - mp
            hired = citizen_stack.pop(-1)
            self._citizen_set_flipped(hired, False)
            player.owned_citizens.append(hired)

            self._finalize_citizen_stack_after_claiming_top(citizen_stack)
            after = self._player_scores_line(player)
            pay = self._format_resource_payment(gp, sp, mp)
            self._log_game_event(
                f"{self._player_label(player_id)} hired citizen \"{top.name}\" ({pay}); scores {before} -> {after}"
            )
            return

        raise ValueError("Citizen not available to hire.")

    def slay_monster(self, player_id, monster_id, sp=0, mp=0, gp=0):
        gp, sp, mp = _n(gp), _n(sp), _n(mp)
        payout = [0, 0, 0, 0]

        for monster_stack in self.monster_grid:
            if not monster_stack:
                continue
            top = monster_stack[-1]
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

            _validate_monster_slay_payment(player, top.strength_cost, top.magic_cost, gp, sp, mp)

            before = self._player_scores_line(player)
            monster_to_add = monster_stack.pop(-1)
            player.strength_score = player.strength_score - sp
            player.magic_score = player.magic_score - mp
            player.owned_monsters.append(monster_to_add)

            if top.has_special_reward:
                payout = self.execute_special_payout(top.special_reward, player_id)
                if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
                    if not (isinstance(self.action_required, dict) and self.action_required.get("action")):
                        payout = [0, 0, 0, 0]
            payout[0] = payout[0] + top.gold_reward
            payout[1] = payout[1] + top.strength_reward
            payout[2] = payout[2] + top.magic_reward
            payout[3] = payout[3] + top.vp_reward
            player.gold_score = player.gold_score + payout[0]
            player.strength_score = player.strength_score + payout[1]
            player.magic_score = player.magic_score + payout[2]
            player.victory_score = player.victory_score + payout[3]
            player.owned_monster_attributes = self.owned_monster_attributes(player_id)

            if monster_stack:
                monster_stack[-1].toggle_accessibility(True)
            elif self.exhausted_stack:
                exhausted = self.exhausted_stack.pop()
                monster_stack.append(exhausted)
                self.exhausted_count = int(self.exhausted_count) + 1
            after = self._player_scores_line(player)
            pay = self._format_resource_payment(gp, sp, mp)
            self._log_game_event(
                f"{self._player_label(player_id)} slew monster \"{monster_to_add.name}\" ({pay}); scores {before} -> {after}"
            )
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
        if all(not stack for stack in self.monster_grid):
            return "all monsters slain"
        if all(not stack for stack in self.domain_grid):
            return "all domains built"
        if int(self.exhausted_count) >= len(self.player_list) * 2:
            return "exhausted stacks filled"
        return None

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
                duke_summary = {"duke_id": duke.duke_id, "name": duke.name or "Duke"}

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
        for rank, s in enumerate(scores):
            s["rank"] = rank + 1
        return scores

    def _finalize_game(self):
        """Compute final scores, set phase to game_over, and log the result."""
        self.final_scores = self._calculate_final_scores()
        self.phase = "game_over"
        if self.final_scores:
            for s in self.final_scores:
                place = {1: "1st", 2: "2nd", 3: "3rd"}.get(s["rank"], f"{s['rank']}th")
                self._log_game_event(
                    f"{place}: {s['name']} — {s['total_vp']} VP "
                    f"({s['base_vp']} base + {s['duke_vp']} Duke)."
                )
            self._log_game_event(f"Game over! {self.final_scores[0]['name']} wins!")

    def end_check(self):
        if self.exhausted_count <= (len(self.player_list) * 2):
            return False

    def prompt(self):
        return
