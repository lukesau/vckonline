"""HarvestEngine -- composed sub-engine of Game.

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


class HarvestEngine:
    def __init__(self, game):
        self.game = game

    def _roll_match_count(self, card):
        d1, d2, ds = self.game.die_one, self.game.die_two, self.game.die_sum
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
        before_scores = self.game._player_scores_line(player)
        card_name = getattr(starter_or_citizen, "name", "?")
        turn_lbl = "on-turn" if on_turn else "off-turn"
        # Tag any bare-verb `slay` payouts produced by this harvest activation with
        # the source card's name (used by the deferred-slay prompt at end of harvest).
        # Cleared in the outer `finally` below so the tag never leaks across cards.
        self.game._immediate_slay_source_label = card_name
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
                        payout = self.game.payouts.execute_special_payout(cmd or s.special_payout_on_turn, player.player_id)
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
                        payout = self.game.payouts.execute_special_payout(cmd or s.special_payout_off_turn, player.player_id)
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
                    payout = self.game.payouts.execute_special_payout(cmd or c.special_payout_on_turn, player.player_id)
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
                    payout = self.game.payouts.execute_special_payout(cmd or c.special_payout_off_turn, player.player_id)
                    player.gold_score = int(player.gold_score) + payout[0]
                    player.strength_score = int(player.strength_score) + payout[1]
                    player.magic_score = int(player.magic_score) + payout[2]
                    player.victory_score = int(player.victory_score) + payout[3]
                    self._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
        finally:
            self.game._immediate_slay_source_label = None
            after_scores = self.game._player_scores_line(player)
            if before_scores != after_scores:
                self.game._log_game_event(
                    f"{self.game._player_label(player.player_id)} harvest {kind} \"{card_name}\" "
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
                if "doubles" in trig and self.game.die_one == self.game.die_two and self.game.die_one != 0:
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
        if self.game.lifecycle.is_blocked_on_concurrent_action():
            return True
        aid = self.game.action_required.get("id") if self.game.action_required else None
        if not aid or aid == self.game.game_id:
            return False
        aa = self.game.action_required.get("action") or ""
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
        if str(aa) == "domain_choose_resource":
            return True
        return False

    def _harvest_complete_finalize(self):
        self.game.harvest_processed = True
        self.game.harvest_player_order = None
        self.game.harvest_player_idx = 0
        # Snapshot which players had any card activate this harvest BEFORE
        # resetting the bookkeeping. We gate the end-of-harvest bonus
        # (legacy bonus_resource_choice or Herald's `no_payout` trigger) on
        # "no cards of yours fired", not on "harvest_delta is zero" — those
        # diverge whenever a card activates but its payout nets nothing
        # (e.g. an `exchange` you can't afford, a `count` that finds zero
        # of the counted thing, a steal against an empty victim, etc.).
        activated_pids = {pid for pid, keys in self.game.harvest_consumed.items() if keys}
        self.game.harvest_consumed = {}
        self.game._harvest_steal_phase_done = False
        # Pending may-slay prompts contributed gains directly (via slay_monster), so
        # by the time we reach this finalize step they should be drained. Defensive
        # clear so a malformed entry can't pin the harvest open across phases.
        self.game.pending_harvest_slays = []
        self.game.pending_harvest_choices = []
        # 5-player resting seat: that player did not harvest at all this round,
        # so they do NOT get the missed-harvest consolation prompt either (they
        # would otherwise look identical to "had no matching cards").
        resting_pid = self.game.resting_player_id()
        for p in self.game.player_list:
            if resting_pid is not None and p.player_id == resting_pid:
                continue
            if p.player_id not in activated_pids:
                self.game.pending_harvest_choices.append(p.player_id)
        if self.game.pending_harvest_choices:
            self._activate_finalize_bonus_for(self.game.pending_harvest_choices[0])
        else:
            self.game.action_required["id"] = self.game.game_id
            self.game.action_required["action"] = ""

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
        player = self.game._player_by_id(player_id)
        if not player:
            if self.game.pending_harvest_choices and self.game.pending_harvest_choices[0] == player_id:
                self.game.pending_harvest_choices.pop(0)
            if self.game.pending_harvest_choices:
                self._activate_finalize_bonus_for(self.game.pending_harvest_choices[0])
            else:
                self.game.action_required["id"] = self.game.game_id
                self.game.action_required["action"] = ""
            return
        starter = self._find_owned_starter_with_trigger(player, "no_payout")
        if starter is not None:
            on_turn = player_id == self.game.lifecycle.current_player_id()
            self._apply_harvest_activation(player, starter, "starter", on_turn)
            # Activation normally opens a `choose ...` prompt; if it didn't (e.g.
            # malformed special_payout), advance the queue so we don't stall.
            aa = (self.game.action_required.get("action") or "").strip()
            aid = self.game.action_required.get("id")
            if aid == player_id and aa:
                return
            if self.game.pending_harvest_choices and self.game.pending_harvest_choices[0] == player_id:
                self.game.pending_harvest_choices.pop(0)
            if self.game.pending_harvest_choices:
                self._activate_finalize_bonus_for(self.game.pending_harvest_choices[0])
            else:
                self.game.action_required["id"] = self.game.game_id
                self.game.action_required["action"] = ""
            return
        # Legacy fallback: hard-coded bonus_resource_choice prompt.
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "bonus_resource_choice"

    def _harvest_run_automation_until_blocked(self):
        # Steal pre-phase: all steal effects across all players fire first, in harvest
        # turn order (active player first, then around the board). This ensures steals
        # resolve before any normal payouts regardless of whose card it is.
        if not getattr(self.game, "_harvest_steal_phase_done", False):
            while True:
                if self._harvest_action_blocked():
                    return
                order = getattr(self.game, "harvest_player_order", None) or []
                found_steal = False
                for pid in order:
                    player = self.game._player_by_id(pid)
                    if not player:
                        continue
                    consumed_list = self.game.harvest_consumed.setdefault(pid, [])
                    on_turn = pid == self.game.lifecycle.current_player_id()
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
            self.game._harvest_steal_phase_done = True

        # Normal harvest: process each player's remaining cards in turn order.
        while not getattr(self.game, "harvest_processed", False):
            if self._harvest_action_blocked():
                return
            order = getattr(self.game, "harvest_player_order", None) or []
            if self.game.harvest_player_idx >= len(order):
                # All players' regular payouts (including specials) are complete.
                # Drain any deferred may-slay prompts queued by citizen payouts; the
                # drain itself opens the next prompt or finalizes harvest when empty.
                if self.game.pending_harvest_slays:
                    self._drain_pending_harvest_slays()
                else:
                    self._harvest_complete_finalize()
                return
            pid = order[self.game.harvest_player_idx]
            player = self.game._player_by_id(pid)
            if not player:
                self.game.harvest_player_idx += 1
                continue
            consumed_list = self.game.harvest_consumed.get(pid)
            if consumed_list is None:
                consumed_list = []
                self.game.harvest_consumed[pid] = consumed_list
            on_turn = pid == self.game.lifecycle.current_player_id()
            slots = self._build_harvest_slots(player, consumed_list, on_turn)
            if not slots:
                self._apply_harvest_on_any_magic_gain_passives(player)
                self.game.harvest_player_idx += 1
                continue
            slot = self._harvest_slots_sorted_for_simulation(slots)[0]
            self._apply_harvest_activation(player, slot["_obj"], slot["kind"], on_turn)
            consumed_list.append(slot["slot_key"])
            if self._harvest_action_blocked():
                return

    def harvest_slots_for_api(self):
        if self.game.action_required.get("action") != "manual_harvest":
            return []
        pid = self.game.action_required.get("id")
        player = self.game._player_by_id(pid)
        if not player:
            return []
        consumed_list = self.game.harvest_consumed.get(pid) or []
        on_turn = pid == self.game.lifecycle.current_player_id()
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
        if self.game.phase != "harvest" or getattr(self.game, "harvest_processed", False):
            raise ValueError("Not in harvest phase.")
        if self.game.action_required.get("action") != "manual_harvest":
            raise ValueError("No harvest choice is pending.")
        if self.game.action_required.get("id") != player_id:
            raise ValueError("It is not your turn to harvest.")
        sk = (slot_key or "").strip()
        if not sk:
            raise ValueError("slot_key required.")
        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        consumed_list = self.game.harvest_consumed.get(player_id)
        if consumed_list is None:
            consumed_list = []
            self.game.harvest_consumed[player_id] = consumed_list
        on_turn = player_id == self.game.lifecycle.current_player_id()
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
        aa = (self.game.action_required.get("action") or "").strip()
        aid = self.game.action_required.get("id")
        if aid == player_id and aa and aa != "manual_harvest":
            return

        self.game.action_required["id"] = self.game.game_id
        self.game.action_required["action"] = ""
        self._harvest_run_automation_until_blocked()
        if self.game.phase == "harvest" and self.game.harvest_processed and not self._harvest_action_blocked():
            self.game.lifecycle.advance_tick()

    def harvest_phase(self):
        """Resolve the entire harvest non-interactively (local scripts / play_turn)."""
        for p in self.game.player_list:
            p.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0}
        active = self.game._player_by_id(self.game.lifecycle.current_player_id())
        self._apply_harvest_jousting_passive(active)
        resting_pid = self.game.resting_player_id()
        if resting_pid is not None:
            self.game._log_game_event(
                f"{self.game._player_label(resting_pid)} is resting (5-player rule); no harvest this turn."
            )
        self.game._silent_harvest_batch = True
        try:
            order = self.game._harvest_player_id_order_starting_active()
            for pid in order:
                player = self.game._player_by_id(pid)
                if not player:
                    continue
                on_turn = pid == self.game.lifecycle.current_player_id()
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
            self.game._silent_harvest_batch = False
        # Silent batch harvest can't open prompts; drop any deferred slay opportunities
        # that citizens may have queued. Interactive harvest drains them via
        # `_harvest_run_automation_until_blocked` -> `_drain_pending_harvest_slays`.
        if self.game.pending_harvest_slays:
            for entry in self.game.pending_harvest_slays:
                self.game._log_game_event(
                    f"{self.game._player_label(entry.get('player_id'))} skipped slay "
                    f"prompt from \"{entry.get('source_label', 'Effect')}\" (silent harvest)."
                )
            self.game.pending_harvest_slays = []
        for player in self.game.player_list:
            print(f"Player {player.name}: {player.gold_score} G, {player.strength_score} S, {player.magic_score} M,"
                  f" {player.victory_score} VP, Monsters: {len(player.owned_monsters)}, "
                  f"Citizens: {len(player.owned_citizens)}, Domains {len(player.owned_domains)}")

    def _maybe_resume_harvest_prompt(self):
        # A may-slay flow that opened a follow-up prompt via the slain monster's
        # special_reward stashes its resume here; once the chain finishes (which
        # is what brought us back to this resume point) we have to drain it
        # BEFORE attempting any further harvest automation, because the engine
        # is otherwise idle but still owes the slay-flow a continuation.
        self.game.payouts._maybe_resume_post_slay_continuation()
        if self.game.phase != "harvest" or getattr(self.game, "harvest_processed", False):
            return
        if getattr(self.game, "harvest_player_order", None) is None:
            return
        if self._harvest_action_blocked():
            return
        self._harvest_run_automation_until_blocked()

    def _want_harvest_optional_exchange_prompt(self, raw_command):
        """
        During interactive harvest only: pure \"exchange pay gain\" specials pause for confirm/skip.
        Batch harvest_phase() sets _silent_harvest_batch so exchanges auto-resolve when affordable.
        """
        if getattr(self.game, "phase", None) != "harvest":
            return False
        if getattr(self.game, "_silent_harvest_batch", False):
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
        opponents = [p for p in self.game.player_list if p.player_id != player_id]
        if not opponents:
            return [0, 0, 0, 0]
        opponents = [
            p for p in opponents
            if not self.game._player_has_take_immunity(p)
            and self.game._player_is_negative_effect_target(p)
        ]
        if not opponents:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} could not steal — all opponents are immune."
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
        self.game.pending_required_choice = {
            "kind": "harvest_steal",
            "stage": "victim",
            "player_id": player_id,
            "victim_options": victim_options,
            "resource_options": resource_options,
            "options": options,
        }
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "harvest_steal"
        return [0, 0, 0, 0]

    def _apply_harvest_steal_choice(self, player_id, victim_id, resource, amount):
        thief = self.game._player_by_id(player_id)
        victim = self.game._player_by_id(victim_id)
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
        before_thief = self.game._player_scores_line(thief)
        before_victim = self.game._player_scores_line(victim)
        setattr(victim, attr_s, have_s - actual_s)
        setattr(thief, attr_s, int(getattr(thief, attr_s, 0) or 0) + actual_s)
        dg = actual_s if res_s == "g" else 0
        ds = actual_s if res_s == "s" else 0
        dm = actual_s if res_s == "m" else 0
        dv = actual_s if res_s == "v" else 0
        self._bump_harvest_delta(thief, dg, ds, dm, dv)
        after_thief = self.game._player_scores_line(thief)
        after_victim = self.game._player_scores_line(victim)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} stole {actual_s}{res_s} from "
            f"{self.game._player_label(victim_id)}; "
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
        if cost_res not in self.game._WILD_SCORE_MAP or cost_amt <= 0 or gain_amt <= 0:
            return [-9999, 0, 0, 0]
        player = self.game._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        if int(getattr(player, self.game._WILD_SCORE_MAP[cost_res], 0) or 0) < cost_amt:
            return [0, 0, 0, 0]
        self.game.pending_required_choice = {
            "kind": "harvest_wild_gain_exchange",
            "player_id": player_id,
            "cost_resource": cost_res,
            "cost_amount": cost_amt,
            "gain_amount": gain_amt,
            "command": command,
        }
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "harvest_wild_gain_exchange"
        return [0, 0, 0, 0]

    def _apply_wild_gain_exchange_choice(self, player_id, gain_res, prc):
        """Deduct the fixed cost then award the chosen resource."""
        player = self.game._player_by_id(player_id)
        if not player:
            return
        cost_res = prc["cost_resource"]
        cost_amt = prc["cost_amount"]
        gain_amt = prc["gain_amount"]
        before = self.game._player_scores_line(player)
        setattr(player, self.game._WILD_SCORE_MAP[cost_res],
                int(getattr(player, self.game._WILD_SCORE_MAP[cost_res], 0)) - cost_amt)
        setattr(player, self.game._WILD_SCORE_MAP[gain_res],
                int(getattr(player, self.game._WILD_SCORE_MAP[gain_res], 0)) + gain_amt)
        dg = (-cost_amt if cost_res == "g" else 0) + (gain_amt if gain_res == "g" else 0)
        ds = (-cost_amt if cost_res == "s" else 0) + (gain_amt if gain_res == "s" else 0)
        dm = (-cost_amt if cost_res == "m" else 0) + (gain_amt if gain_res == "m" else 0)
        dv = (-cost_amt if cost_res == "v" else 0) + (gain_amt if gain_res == "v" else 0)
        self._bump_harvest_delta(player, dg, ds, dm, dv)
        after = self.game._player_scores_line(player)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} wild-gain exchange ({prc.get('command')}): "
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
        if gain_res not in self.game._WILD_SCORE_MAP or cost_amt <= 0 or gain_amt <= 0:
            return [-9999, 0, 0, 0]
        player = self.game._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        options = [
            {"resource": res, "amount": cost_amt}
            for res in ("g", "s", "m")
            if int(getattr(player, self.game._WILD_SCORE_MAP[res], 0) or 0) >= cost_amt
        ]
        if not options:
            return [0, 0, 0, 0]
        self.game.pending_required_choice = {
            "kind": "harvest_wild_cost_exchange",
            "player_id": player_id,
            "cost_options": options,
            "gain_resource": gain_res,
            "gain_amount": gain_amt,
            "command": command,
        }
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "harvest_wild_cost_exchange"
        return [0, 0, 0, 0]

    def _apply_wild_cost_exchange_choice(self, player_id, cost_res, prc):
        """Deduct the chosen resource then award the fixed gain."""
        player = self.game._player_by_id(player_id)
        if not player:
            return
        cost_opts = prc.get("cost_options") or []
        cost_amt = next((o["amount"] for o in cost_opts if o["resource"] == cost_res), None)
        if cost_amt is None:
            return
        gain_res = prc["gain_resource"]
        gain_amt = prc["gain_amount"]
        before = self.game._player_scores_line(player)
        setattr(player, self.game._WILD_SCORE_MAP[cost_res],
                int(getattr(player, self.game._WILD_SCORE_MAP[cost_res], 0)) - cost_amt)
        setattr(player, self.game._WILD_SCORE_MAP[gain_res],
                int(getattr(player, self.game._WILD_SCORE_MAP[gain_res], 0)) + gain_amt)
        dg = (-cost_amt if cost_res == "g" else 0) + (gain_amt if gain_res == "g" else 0)
        ds = (-cost_amt if cost_res == "s" else 0) + (gain_amt if gain_res == "s" else 0)
        dm = (-cost_amt if cost_res == "m" else 0) + (gain_amt if gain_res == "m" else 0)
        dv = (-cost_amt if cost_res == "v" else 0) + (gain_amt if gain_res == "v" else 0)
        self._bump_harvest_delta(player, dg, ds, dm, dv)
        after = self.game._player_scores_line(player)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} wild-cost exchange ({prc.get('command')}): "
            f"paid {cost_res}; scores {before} -> {after}"
        )

    def _drain_pending_harvest_slays(self):
        """Open a may-slay prompt for the next pending harvest slay, or finish harvest.

        Called after the regular harvest scan completes and after each pending
        slay resolves. Once the queue is empty we finish harvest the same way
        `_harvest_run_automation_until_blocked` would have.
        """
        # Clean up any prompt residue from the just-resolved entry.
        if isinstance(self.game.action_required, dict):
            aa = str(self.game.action_required.get("action", "") or "")
            if aa in ("choose_monster_slay", "slay_monster_payment"):
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
        self.game.pending_required_choice = None
        while self.game.pending_harvest_slays:
            entry = self.game.pending_harvest_slays[0]
            pid = entry.get("player_id")
            label = entry.get("source_label", "Effect")
            options = self.game.slay._immediate_slay_monster_options()
            if not options:
                self.game._log_game_event(
                    f"{self.game._player_label(pid)} could not use \"{label}\" "
                    f"(no accessible monsters to slay)."
                )
                self.game.pending_harvest_slays.pop(0)
                continue
            # Pop now so the prompt resolution doesn't double-drain.
            self.game.pending_harvest_slays.pop(0)
            self.game.slay._open_immediate_slay_prompt(pid, label, resume_kind="harvest_pending_slay")
            return
        # Queue empty: complete harvest normally.
        if getattr(self.game, "phase", None) == "harvest" and not getattr(self.game, "harvest_processed", False):
            self._harvest_complete_finalize()

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
            if self.game._domain_recurring_passive_on_build_turn_cooldown(d):
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
        before = self.game._player_scores_line(player)
        player.gold_score = int(player.gold_score) + dg
        player.strength_score = int(player.strength_score) + ds
        player.magic_score = int(player.magic_score) + dm
        player.victory_score = int(player.victory_score) + dv
        self._bump_harvest_delta(player, dg, ds, dm, dv)
        after = self.game._player_scores_line(player)
        self.game._log_game_event(
            f"{self.game._player_label(player.player_id)} harvest passive \"{getattr(domain, 'name', 'Domain')}\" "
            f"({unit_name} {pool_label} x{n}): scores {before} -> {after}"
        )

    def _apply_harvest_on_any_magic_gain_passives(self, player):
        """Fire `harvest.on_any_magic_gain <r> <n>` passives for the given player.

        Called at the end of the player's harvest processing (when all their
        slots are exhausted). If the player gained any magic this harvest
        phase (harvest_delta["magic"] > 0), each matching domain grants
        the specified bonus resource once.

        Example (Opera House): `harvest.on_any_magic_gain m 1`
        """
        if not player:
            return
        hd = getattr(player, "harvest_delta", None) or {}
        if int(hd.get("magic", 0)) <= 0:
            return
        for d in list(getattr(player, "owned_domains", []) or []):
            if self.game._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            raw = (getattr(d, "passive_effect", None) or "").strip()
            if not raw:
                continue
            parts = raw.split()
            if len(parts) != 3 or parts[0].lower() != "harvest.on_any_magic_gain":
                continue
            gain_r = parts[1].lower()
            try:
                gain_n = int(parts[2])
            except (ValueError, TypeError):
                continue
            if gain_r not in ("g", "s", "m", "v") or gain_n <= 0:
                continue
            before = self.game._player_scores_line(player)
            self.game.domain_effects._bank_gain_for_active(player, gain_r, gain_n)
            after = self.game._player_scores_line(player)
            if before != after:
                self.game._log_game_event(
                    f"{self.game._player_label(player.player_id)} \"{getattr(d, 'name', 'Domain')}\" "
                    f"harvest magic bonus; scores {before} -> {after}"
                )

    def _apply_all_players_on_any_slay_passives(self):
        """Fire `action.on_any_slay <r> <n>` passives for ALL players.

        Called from slay_monster after a successful slay. Fires only during
        the action phase (not harvest-phase slays). Every player who owns a
        domain with this passive receives the stated resource gain.

        Example (Raven's Outpost): `action.on_any_slay s 1`
        """
        if getattr(self.game, "phase", None) != "action":
            return
        for player in list(getattr(self.game, "player_list", []) or []):
            for d in list(getattr(player, "owned_domains", []) or []):
                if self.game._domain_recurring_passive_on_build_turn_cooldown(d):
                    continue
                raw = (getattr(d, "passive_effect", None) or "").strip()
                if not raw:
                    continue
                parts = raw.split()
                if len(parts) != 3 or parts[0].lower() != "action.on_any_slay":
                    continue
                gain_r = parts[1].lower()
                try:
                    gain_n = int(parts[2])
                except (ValueError, TypeError):
                    continue
                if gain_r not in ("g", "s", "m", "v") or gain_n <= 0:
                    continue
                before = self.game._player_scores_line(player)
                self.game.domain_effects._bank_gain_for_active(player, gain_r, gain_n)
                after = self.game._player_scores_line(player)
                if before != after:
                    self.game._log_game_event(
                        f"{self.game._player_label(player.player_id)} \"{getattr(d, 'name', 'Domain')}\" "
                        f"reactive slay bonus; scores {before} -> {after}"
                    )

