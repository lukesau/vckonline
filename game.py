import time
import random
from json import JSONEncoder
from typing import List
import mariadb
from constants import *
from cards import *
import threading


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
        raise ValueError("Strength cannot be spent on hiring citizens or buying domains.")
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


def _citizen_is_thief(citizen):
    if not citizen:
        return False
    name = (getattr(citizen, "name", None) or "").strip().lower()
    if name == "thief":
        return True
    sc = getattr(citizen, "special_citizen", None)
    try:
        if int(sc) == 1:
            return True
    except (TypeError, ValueError):
        pass
    return False


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


CONCURRENT_HANDLERS = {
    "choose_duke": _ChooseDukeConcurrentHandler(),
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
        self.effects = game_state['effects']
        self.action_required = game_state['action_required']
        # Concurrent (non-ordered) prompt: all listed players must respond before progression.
        # See module-level _ChooseDukeConcurrentHandler / CONCURRENT_HANDLERS for the protocol.
        self.concurrent_action = game_state.get('concurrent_action') or None
        # Turn/tick tracking
        self.tick_id = game_state.get('tick_id', 0)
        self.turn_number = game_state.get('turn_number', 1)
        self.turn_index = game_state.get('turn_index', 0)
        # roll -> roll_pending -> harvest -> action
        self.phase = game_state.get('phase', 'roll')
        self.actions_remaining = game_state.get('actions_remaining', 0)
        self.harvest_processed = game_state.get('harvest_processed', False)
        self.pending_harvest_choices = game_state.get('pending_harvest_choices', [])
        # Manual harvest session (None = not in a multi-step harvest resolution)
        self.harvest_player_order = game_state.get('harvest_player_order')
        self.harvest_player_idx = game_state.get('harvest_player_idx', 0)
        self.harvest_consumed = game_state.get('harvest_consumed') or {}
        self.last_active_time = 0
        self.game_log = list(game_state.get('game_log') or [])
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
        # Block on any active concurrent (non-ordered) prompt first.
        if self.is_blocked_on_concurrent_action():
            return False

        # Block only on required player choices (not on standard action prompts)
        if self.action_required and self.action_required.get("id") and self.action_required.get("id") != self.game_id:
            if self.action_required.get("action") == "bonus_resource_choice" or str(
                    self.action_required.get("action", "")).startswith("choose"):
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

        if self.phase == 'harvest':
            # Manual harvest: players resolve matching starters/citizens in turn order (active player first).
            if not getattr(self, "harvest_processed", False):
                if getattr(self, "harvest_player_order", None) is None:
                    for p in self.player_list:
                        p.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
                    self.harvest_consumed = {}
                    self.harvest_player_idx = 0
                    self.harvest_player_order = self._harvest_player_id_order_starting_active()
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
            finisher = self._player_label(self.current_player_id())
            self.turn_index = (self.turn_index + 1) % max(1, len(self.player_list))
            self.turn_number = int(self.turn_number) + 1
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
        the caller must apply the hire/buy/slay/take first, then call
        finish_turn_if_no_actions_remaining() so logs and engine state stay ordered.
        """
        if self.phase != 'action':
            # If an action comes in early, fast-forward to action phase.
            while self.advance_tick():
                if self.phase == 'action':
                    break

        # If we're blocked on a required choice, no standard actions can be taken.
        if self.action_required and self.action_required.get("id") and self.action_required.get("id") != self.game_id:
            if self.action_required.get("action") in ("bonus_resource_choice", "manual_harvest") or str(
                    self.action_required.get("action", "")).startswith("choose"):
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
        if getattr(self, "phase", None) == "action" and int(getattr(self, "actions_remaining", 0) or 0) == 0:
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
            ok, n = self._roll_match_count(cit)
            if not ok:
                continue
            cid = int(getattr(cit, "citizen_id", -1))
            is_thief = _citizen_is_thief(cit)
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

    def _player_has_unharvested_thief_citizen(self, player, consumed_keys):
        consumed = set(consumed_keys or [])
        for idx, cit in enumerate(getattr(player, "owned_citizens", []) or []):
            if not _citizen_is_thief(cit):
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
        if aa in ("bonus_resource_choice", "manual_harvest"):
            return True
        if str(aa).startswith("choose"):
            return True
        return False

    def _harvest_complete_finalize(self):
        self.harvest_processed = True
        self.harvest_player_order = None
        self.harvest_player_idx = 0
        self.harvest_consumed = {}
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
            if len(slots) >= 2:
                self.action_required["id"] = pid
                self.action_required["action"] = "manual_harvest"
                self._log_game_event(
                    f"{self._player_label(pid)}: choose harvest order ({len(slots)} matching cards)."
                )
                return
            slot = slots[0]
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
            if self._player_has_unharvested_thief_citizen(player, consumed_list):
                raise ValueError("Harvest the Thief first.")
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

    def execute_special_payout(self, command, player_id):
        print("executing special payout")
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
        match first_word:
            case "count":
                print("Matched count")
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
                    case "type":
                        type_count = self.owned_monster_attributes(player_id)[third_word]
                        match fourth_word:
                            case 'g':
                                payout[0] = type_count * int(split_command[4])
                            case 's':
                                payout[1] = type_count * int(split_command[4])
                            case 'm':
                                payout[2] = type_count * int(split_command[4])
                            case 'v':
                                payout[3] = type_count * int(split_command[4])
                            case _:
                                payout[0] = -9999
                    case _:
                        payout[0] = -9999
            case "exchange":
                print("Matched exchange")
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
            case "choose":
                # "choose ..." is a blocking prompt: no immediate payout is applied here.
                # It is resolved later via act_on_required_action(), which applies the
                # chosen payout and then resumes harvest automation (if active).
                normalized, options = self._normalize_choose_command(command)
                if not options:
                    payout[0] = -9999
                    return payout
                self.action_required["id"] = player_id
                self.action_required["action"] = normalized
                # Keep a small bit of context for debugging / future extensions.
                self.pending_required_choice = {
                    "kind": "special_payout_choose",
                    "player_id": player_id,
                    "command": normalized,
                    "options": options,
                }
            case _:
                payout[0] = -9999
        print(payout)
        return payout

    def _normalize_choose_command(self, command):
        """
        Normalize a "choose" special payout into a canonical string + parsed options.

        Supported input formats (1-3 options):
        - "choose g 2 m 2"
        - "choose g 1 s 1 m 1"
        Returns:
        - (normalized_command: str, options: list[dict{token, amount}])
        """
        parts = (command or "").strip().split()
        if not parts or parts[0].lower() != "choose":
            return (command or ""), []
        rest = parts[1:]
        options = []

        def add_opt(tok, amt):
            t = (tok or "").strip().lower()
            if t not in ("g", "s", "m", "v"):
                return
            try:
                n = int(amt)
            except (TypeError, ValueError):
                return
            options.append({"token": t, "amount": n})

        # Strict: pairs token, amount (g 2 m 2 ...)
        i = 0
        while i + 1 < len(rest) and len(options) < 3:
            a, b = rest[i], rest[i + 1]
            if (a or "").lower() in ("g", "s", "m", "v"):
                add_opt(a, b)
                i += 2
                continue
            break

        normalized = "choose " + " ".join([f"{o['token']} {o['amount']}" for o in options]) if options else (command or "")
        return normalized, options

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

            # Resolve a blocking "choose ..." special payout prompt.
            if str(current_required).strip().lower().startswith("choose"):
                normalized, options = self._normalize_choose_command(current_required)
                if not options:
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
                dg = ds = dm = dv = 0
                if opt["token"] == "g":
                    dg = opt["amount"]
                elif opt["token"] == "s":
                    ds = opt["amount"]
                elif opt["token"] == "m":
                    dm = opt["amount"]
                else:
                    dv = opt["amount"]
                target.gold_score = int(target.gold_score) + int(dg)
                target.strength_score = int(target.strength_score) + int(ds)
                target.magic_score = int(target.magic_score) + int(dm)
                target.victory_score = int(getattr(target, "victory_score", 0)) + int(dv)
                if not hasattr(target, "harvest_delta") or not isinstance(target.harvest_delta, dict):
                    target.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
                self._bump_harvest_delta(target, dg, ds, dm, dv)
                after = self._player_scores_line(target)
                self._log_game_event(
                    f"{self._player_label(player_id)} chose ({idx + 1}/{len(options)}) from \"{normalized}\": "
                    f"{opt['token']} {opt['amount']}; scores {before} -> {after}"
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
            # If we were stalled in setup, drive the engine forward so the
            # next state the client polls is something actionable.
            if self.phase == "setup":
                while self.advance_tick():
                    if self.phase == "action":
                        break

    def update_payout_for_role(self, role_name, player_id, payout, split_command):
        role_count = 0
        for player in self.player_list:
            if player.player_id == player_id:
                role_count = player.calc_roles()[role_name]
                break
        if role_count > 0:
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
        else:
            payout[0] = -9999

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
            player.owned_citizens.append(citizen_stack.pop(-1))

            if citizen_stack:
                citizen_stack[-1].toggle_accessibility(True)
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
            after = self._player_scores_line(player)
            pay = self._format_resource_payment(gp, sp, mp)
            self._log_game_event(
                f"{self._player_label(player_id)} slew monster \"{monster_to_add.name}\" ({pay}); scores {before} -> {after}"
            )
            return

        raise ValueError("Monster not available to slay.")

    def buy_domain(self, player_id, domain_id, gp=0, mp=0, sp=0):
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

            gold_cost = int(getattr(top, "gold_cost", 0) or 0)
            _validate_hire_or_domain_gold_payment(player, gold_cost, gp, sp, mp)

            before = self._player_scores_line(player)
            player.gold_score = player.gold_score - gp
            player.magic_score = player.magic_score - mp
            player.owned_domains.append(domain_stack.pop(-1))

            if domain_stack:
                domain_stack[-1].toggle_accessibility(True)
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

    def end_check(self):
        if self.exhausted_count <= (len(self.player_list) * 2):
            return False

    def prompt(self):
        return


class Player:
    def __init__(self, player_id, name):
        self.player_id = player_id
        self.name = name
        self.owned_starters = []
        self.owned_citizens = []
        self.owned_domains = []
        self.owned_dukes = []
        self.owned_monsters = []
        self.gold_score = 2
        self.strength_score = 0
        self.magic_score = 1
        self.victory_score = 0
        self.is_first = False
        self.shadow_count = 0
        self.holy_count = 0
        self.soldier_count = 0
        self.worker_count = 0
        self.effects = {
            "roll_phase": [],
            "harvest_phase": [],
            "action_phase": []
        }
        self.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}

    @classmethod
    def from_dict(cls, data):
        player_id = data['player_id']
        name = data['name']
        player = cls(player_id, name)
        player.owned_starters = [Starter.from_dict(s) for s in data['owned_starters']]
        player.owned_citizens = [Citizen.from_dict(c) for c in data['owned_citizens']]
        player.owned_domains = [Domain.from_dict(d) for d in data['owned_domains']]
        player.owned_dukes = [Duke.from_dict(d) for d in data['owned_dukes']]
        player.owned_monsters = [Monster.from_dict(m) for m in data['owned_monsters']]
        player.gold_score = data['gold_score']
        player.strength_score = data['strength_score']
        player.magic_score = data['magic_score']
        player.victory_score = data['victory_score']
        player.is_first = data['is_first']
        player.effects = data['effects']
        player.harvest_delta = data.get('harvest_delta', {"gold": 0, "strength": 0, "magic": 0, "victory": 0})
        roles = player.calc_roles()
        player.shadow_count = roles['shadow_count']
        player.holy_count = roles['holy_count']
        player.soldier_count = roles['soldier_count']
        player.worker_count = roles['worker_count']
        return player

    def calc_roles(self):
        shadow_count = 0
        holy_count = 0
        soldier_count = 0
        worker_count = 0
        for citizen in self.owned_citizens:
            shadow_count = shadow_count + citizen.shadow_count
            holy_count = holy_count + citizen.holy_count
            soldier_count = soldier_count + citizen.soldier_count
            worker_count = worker_count + citizen.worker_count
        for domain in self.owned_domains:
            shadow_count = shadow_count + domain.shadow_count
            holy_count = holy_count + domain.holy_count
            soldier_count = soldier_count + domain.soldier_count
            worker_count = worker_count + domain.worker_count
        roles_dict = {
            "shadow_count": shadow_count,
            "holy_count": holy_count,
            "soldier_count": soldier_count,
            "worker_count": worker_count
        }
        return roles_dict


class LobbyMember:
    def __init__(self, player_name, player_id):
        self.name = player_name
        self.player_id = player_id
        self.is_ready = False
        self.last_active_time = 0


class GameMember:
    def __init__(self, player_id, player_name, game_id):
        self.name = player_name
        self.player_id = player_id
        self.game_id = game_id


def load_game_data(game_id, preset, player_list_from_lobby):
    monster_query = ""
    monster_stack = []
    citizen_query = ""
    citizen_stack = []
    domain_query = "select_random_domains"
    domain_stack = []
    duke_query = "select_random_dukes"
    duke_stack = []
    starter_query = "SELECT * FROM starters"
    starter_stack = []
    player_list = []
    citizen_grid: List[List[Citizen]] = [[] for _ in range(10)]
    domain_grid: List[List[Domain]] = [[] for _ in range(5)]
    monster_grid: List[List[Monster]] = [[] for _ in range(5)]
    die_one = 0
    die_two = 0
    die_sum = 0
    exhausted_count = 0
    effects = {
        "roll_phase": [],
        "harvest_phase": [],
        "action_phase": []
    }
    action_required = {
        "id": "",
        "action": ""
    }
    tick_id = 0
    turn_number = 1
    turn_index = 0
    # Start in setup; if no setup actions are needed the engine will advance into roll.
    phase = 'setup'
    actions_remaining = 0
    harvest_processed = False
    pending_harvest_choices = []
    match preset:
        case "base1":
            monster_query = "select_base1_monsters"
            citizen_query = "select_base1_citizens"
        case "base2":
            monster_query = "select_base2_monsters"
            citizen_query = "select_base2_citizens"
    try:
        my_connect = mariadb.connect(user='vckonline', password='vckonline', host='127.0.0.1',
                                     database='vckonline', port=3306)
        my_cursor = my_connect.cursor(dictionary=True)

        my_cursor.callproc(monster_query)

        results = my_cursor.fetchall()
        for row in results:
            my_monster = Monster(row['id_monsters'], row['name'], row['area'], row['monster_type'],
                                 row['monster_order'], row['strength_cost'], row['magic_cost'], row['vp_reward'],
                                 row['gold_reward'], row['strength_reward'], row['magic_reward'],
                                 row['has_special_reward'], row['special_reward'], row['has_special_cost'],
                                 row['special_cost'], row['is_extra'], row['expansion'])
            monster_stack.append(my_monster)

        my_cursor.callproc(citizen_query)
        citizen_count = 5
        if len(player_list_from_lobby) == 5:
            citizen_count = 6
        results = my_cursor.fetchall()
        for row in results:
            for i in range(citizen_count):
                my_citizen = Citizen(row['id_citizens'], row['name'], row['gold_cost'], row['roll_match1'],
                                     row['roll_match2'], row['shadow_count'], row['holy_count'], row['soldier_count'],
                                     row['worker_count'], row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                     row['strength_payout_on_turn'], row['strength_payout_off_turn'],
                                     row['magic_payout_on_turn'], row['magic_payout_off_turn'],
                                     row['has_special_payout_on_turn'], row['has_special_payout_off_turn'],
                                     row['special_payout_on_turn'], row['special_payout_off_turn'],
                                     row['special_citizen'],
                                     row['expansion'])
                citizen_stack.append(my_citizen)

        my_cursor.callproc(domain_query)
        results = my_cursor.fetchall()
        for row in results:
            my_domain = Domain(row['id_domains'], row['name'], row['gold_cost'], row['shadow_count'], row['holy_count'],
                               row['soldier_count'], row['worker_count'], row['vp_reward'],
                               row['has_activation_effect'], row['has_passive_effect'], row['passive_effect'],
                               row['activation_effect'], row['text'], row['expansion'])
            domain_stack.append(my_domain)

        my_cursor.callproc(duke_query)
        results = my_cursor.fetchall()
        for row in results:
            my_duke = Duke(row['id_dukes'], row['name'], row['gold_mult'], row['strength_mult'], row['magic_mult'],
                           row['shadow_mult'], row['holy_mult'], row['soldier_mult'], row['worker_mult'],
                           row['monster_mult'], row['citizen_mult'], row['domain_mult'], row['boss_mult'],
                           row['minion_mult'], row['beast_mult'], row['titan_mult'], row['expansion'])
            duke_stack.append(my_duke)

        my_cursor.execute(starter_query)
        my_result = my_cursor.fetchall()
        for row in my_result:
            my_starter = Starter(row['id_starters'], row['name'], row['roll_match1'], row['roll_match2'],
                                 row['gold_payout_on_turn'], row['gold_payout_off_turn'],
                                 row['strength_payout_on_turn'], row['strength_payout_off_turn'],
                                 row['magic_payout_on_turn'], row['magic_payout_off_turn'],
                                 row['has_special_payout_on_turn'], row['has_special_payout_off_turn'],
                                 row['special_payout_on_turn'], row['special_payout_off_turn'], row['expansion'])
            starter_stack.append(my_starter)
        my_cursor.close()
        my_connect.close()
    except Exception as e:
        print(f"Error: {e}")
    # print(f"size of monster stack: {len(monster_stack)}")
    # print(f"size of citizen stack: {len(citizen_stack)}")
    # print(f"size of domain stack: {len(domain_stack)}")
    # print(f"size of duke stack: {len(duke_stack)}")
    # print(f"size of starter stack: {len(starter_stack)}")
    # create players and determine order
    if not all([player_list_from_lobby, starter_query, monster_stack, citizen_stack, domain_stack, duke_stack]):
        raise ValueError("One or more required lists are empty.")
    else:
        for player in player_list_from_lobby:
            my_player = Player(player.player_id, player.name)
            player_list.append(my_player)
        random.shuffle(player_list)
        player_list[0].is_first = True
        # give players starters and dukes
        for player in player_list:
            player.owned_starters.append(starter_stack[0])
            player.owned_starters.append(starter_stack[1])
            for i in range(2):
                player.owned_dukes.append(duke_stack.pop())
        # deal monsters onto the board
        grouped_monsters = {}
        for monster in monster_stack:
            area = monster.area
            if area in grouped_monsters:
                grouped_monsters[area].append(monster)
            else:
                grouped_monsters[area] = [monster]
        # Reverse the order of each group by monster_order
        for area, monsters in grouped_monsters.items():
            monsters.sort(key=lambda item: item.order, reverse=True)
        areas = list(grouped_monsters.keys())
        chosen_areas = random.sample(areas, 5)
        for i, area in enumerate(chosen_areas):
            monsters = grouped_monsters[area]
            monster_grid[i].extend(monsters)
        for i, stack in enumerate(monster_grid):
            for monster in stack:
                monster.toggle_visibility(True)
            # Make the last monster in the stack accessible
            stack[-1].toggle_accessibility(True)
        # deal citizens onto the board
        # Create a dictionary to store citizen lists with roll numbers as keys
        citizens_by_roll = {roll: [] for roll in [1, 2, 3, 4, 5, 6, 7, 8, 9, 11]}
        # Group citizens by roll number
        for citizen in citizen_stack:
            citizen.toggle_visibility()
            citizens_by_roll[citizen.roll_match1].append(citizen)
        for roll in citizens_by_roll:
            # Map 11 roll to index 9
            index = roll - 1 if roll < 11 else 9
            citizens = citizens_by_roll[roll]
            citizen_grid[index].extend(list(citizens))
            # Make the first citizen in each list accessible
            citizen_grid[index][-1].toggle_accessibility(True)
        # Deal the domains into the stacks
        for i in range(5):
            stack = domain_grid[i]
            for j in range(3):
                if j == 2:  # top domain is visible and accessible
                    domain = domain_stack.pop()
                    domain.toggle_visibility(True)
                    domain.toggle_accessibility(True)
                    stack.append(domain)
                else:  # other domains are not visible or accessible
                    domain = domain_stack.pop()
                    stack.append(domain)

        # Create a dictionary to store all the stacks
        game_state = {'game_id': game_id,
                      'player_list': player_list,
                      'monster_grid': monster_grid,
                      'citizen_grid': citizen_grid,
                      'domain_grid': domain_grid,
                      'die_one': die_one,
                      'die_two': die_two,
                      'die_sum': die_sum,
                      'exhausted_count': exhausted_count,
                      'effects': effects,
                      'action_required': action_required,
                      'concurrent_action': None,
                      'tick_id': tick_id,
                      'turn_number': turn_number,
                      'turn_index': turn_index,
                      'phase': phase,
                      'actions_remaining': actions_remaining,
                      'harvest_processed': harvest_processed,
                      'pending_harvest_choices': pending_harvest_choices,
                      'harvest_player_order': None,
                      'harvest_player_idx': 0,
                      'harvest_consumed': {},
                      'game_log': []}
        # Return the dictionary
        return game_state


class SummaryEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Player):
            return {
                'player_id': obj.player_id,
                'name': obj.name,
                'owned_citizens': len(obj.owned_citizens),
                'owned_domains': len(obj.owned_domains),
                'owned_monsters': len(obj.owned_monsters),
                'gold_score': obj.gold_score,
                'strength_score': obj.strength_score,
                'magic_score': obj.magic_score,
                'victory_score': obj.victory_score,
                'is_first': obj.is_first
            }
        elif isinstance(obj, LobbyMember):
            return {
                "player_name": obj.name,
                "player_id": obj.player_id,
                "is_ready": obj.is_ready
            }
        elif isinstance(obj, GameMember):
            return {
                "player_name": obj.name,
                "player_id": obj.player_id
            }
        elif isinstance(obj, Game):
            return {
                "game_id": obj.game_id,
                "player_list": obj.player_list
            }
        else:
            return super().default(obj)


class GameObjectEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Player):
            # Role totals come from owned citizens + domains (see calc_roles); keep JSON aligned with gameplay.
            roles = obj.calc_roles()
            return {
                'player_id': obj.player_id,
                'name': obj.name,
                # Dev client wants to render a tableau; include full objects (not just ids).
                'owned_starters': [starter.to_dict() for starter in obj.owned_starters],
                'owned_citizens': [citizen.to_dict() for citizen in obj.owned_citizens],
                'owned_domains': [domain.to_dict() for domain in obj.owned_domains],
                'owned_dukes': [duke.to_dict() for duke in obj.owned_dukes],
                'owned_monsters': [monster.to_dict() for monster in obj.owned_monsters],
                'gold_score': obj.gold_score,
                'strength_score': obj.strength_score,
                'magic_score': obj.magic_score,
                'victory_score': obj.victory_score,
                'is_first': obj.is_first,
                'shadow_count': roles['shadow_count'],
                'holy_count': roles['holy_count'],
                'soldier_count': roles['soldier_count'],
                'worker_count': roles['worker_count'],
                'effects': obj.effects,
                'harvest_delta': getattr(obj, "harvest_delta", {"gold": 0, "strength": 0, "magic": 0, "victory": 0})
            }
        elif isinstance(obj, Duke):
            return obj.to_dict()
        elif isinstance(obj, Monster):
            return obj.to_dict()
        elif isinstance(obj, Starter):
            return obj.to_dict()
        elif isinstance(obj, Citizen):
            return obj.to_dict()
        elif isinstance(obj, Domain):
            return obj.to_dict()
        elif isinstance(obj, Game):
            base = {
                "game_id": obj.game_id,
                "player_list": obj.player_list,
                "monster_grid": obj.monster_grid,
                "citizen_grid": obj.citizen_grid,
                "domain_grid": obj.domain_grid,
                "die_one": obj.die_one,
                "die_two": obj.die_two,
                "die_sum": obj.die_sum,
                "rolled_die_one": getattr(obj, "rolled_die_one", obj.die_one),
                "rolled_die_two": getattr(obj, "rolled_die_two", obj.die_two),
                "rolled_die_sum": getattr(obj, "rolled_die_sum", obj.die_sum),
                "pending_roll": getattr(obj, "pending_roll", None),
                "exhausted_count": obj.exhausted_count,
                "effects": obj.effects,
                "action_required": obj.action_required,
                "concurrent_action": getattr(obj, "concurrent_action", None),
                "tick_id": getattr(obj, "tick_id", 0),
                "turn_number": getattr(obj, "turn_number", 1),
                "turn_index": getattr(obj, "turn_index", 0),
                "phase": getattr(obj, "phase", "roll"),
                "actions_remaining": getattr(obj, "actions_remaining", 0),
                "active_player_id": obj.current_player_id() if hasattr(obj, "current_player_id") else None,
                "harvest_player_order": getattr(obj, "harvest_player_order", None),
                "harvest_player_idx": getattr(obj, "harvest_player_idx", 0),
                "harvest_consumed": getattr(obj, "harvest_consumed", {}) or {},
                "harvest_prompt_slots": obj.harvest_slots_for_api() if hasattr(obj, "harvest_slots_for_api") else [],
                "game_log": list(getattr(obj, "game_log", None) or []),
            }
            return base
        else:
            return super().default(obj)
