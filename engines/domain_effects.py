"""DomainEffectsEngine -- composed sub-engine of Game.

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


class DomainEffectsEngine:
    def __init__(self, game):
        self.game = game

    def _resume_after_domain_activation_follow_up(self):
        """Clear optional domain activation prompts and restore action/end-turn resolution."""
        self.game.pending_required_choice = None
        if getattr(self.game, "phase", None) == "action" and int(getattr(self.game, "actions_remaining", 0) or 0) > 0:
            self.game.action_required["id"] = self.game.lifecycle.current_player_id()
            self.game.action_required["action"] = "standard_action"
            return
        self.game.action_required["id"] = self.game.game_id
        self.game.action_required["action"] = ""
        if getattr(self.game, "phase", None) == "action" and int(getattr(self.game, "actions_remaining", 0) or 0) == 0:
            if self._start_action_end_domain_sequence(self.game.lifecycle.current_player_id()):
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
        can_pay = self.game.choose._player_can_afford_self_convert_resources(player, pay_k, pay_n)
        if optional:
            if not can_pay:
                return [0, 0, 0, 0]
            domain_name = "Domain"
            if domain is not None:
                domain_name = getattr(domain, "name", None) or domain_name
            self.game.action_required["id"] = player.player_id
            self.game.action_required["action"] = "domain_self_convert"
            self.game.pending_required_choice = {
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
        pi = idx[pay_k]
        payout[pi] -= pay_n
        if gain_k == "p":
            target = self.game._player_by_id(player.player_id)
            if not target:
                payout[0] = -9999
                return payout
            target.map_score = int(getattr(target, "map_score", 0)) + gain_n
            self.game.harvest._bump_harvest_delta(target, 0, 0, 0, 0, gain_n)
        else:
            gi = idx[gain_k]
            payout[gi] += gain_n
        return payout

    def _execute_manipulate_resources_self_convert_payout(self, raw, player_id):
        """Activation / compound payout fragment: bank trade (e.g. Wisborg)."""
        player = self.game._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        return self._prompt_or_apply_self_convert(raw, player, None)

    def _execute_manipulate_resources_gain_payout(self, raw, player_id):
        """Activation / compound payout fragment: simple bank gain (mode=gain gain=<r>:<n>)."""
        player = self.game._player_by_id(player_id)
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
            self.game.harvest._bump_harvest_delta(player, gain_n, 0, 0, 0)
        elif gain_k == "s":
            player.strength_score = int(player.strength_score) + gain_n
            self.game.harvest._bump_harvest_delta(player, 0, gain_n, 0, 0)
        elif gain_k == "m":
            player.magic_score = int(player.magic_score) + gain_n
            self.game.harvest._bump_harvest_delta(player, 0, 0, gain_n, 0)
        elif gain_k == "v":
            player.victory_score = int(getattr(player, "victory_score", 0)) + gain_n
            self.game.harvest._bump_harvest_delta(player, 0, 0, 0, gain_n)
        elif gain_k == "p":
            player.map_score = int(getattr(player, "map_score", 0)) + gain_n
            self.game.harvest._bump_harvest_delta(player, 0, 0, 0, 0, gain_n)

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
        before = self.game._player_scores_line(player)
        self._bank_gain_for_active(player, gain_k, gain_n)
        after = self.game._player_scores_line(player)
        if before != after:
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} \"{source_label}\" gain; scores {before} -> {after}"
            )
        return True

    def _apply_action_event_gain_passives(self, player, event_name):
        """Fire owned-domain `action.<event_name> manipulate_resources mode=gain gain=...` passives.

        Generic dispatcher for action-phase triggers: `start`, `end`, `hire`, `slay`,
        and any future verb. Only mode=gain is handled here -- player-targeted modes
        (take_from_player, pay_to_player) route through the action.end queue/prompt
        machinery and are intentionally ignored at the per-event call sites.

        The caller is responsible for invoking this only when the firing player is the
        active player; we still guard on `self.game.phase == "action"` so card text that says
        "During your Action Phase, ..." stays honest if a slay/hire ever leaks into
        another phase (e.g. via a granted action triggered from harvest).
        """
        if not player or not event_name:
            return
        if getattr(self.game, "phase", None) != "action":
            return
        prefix = f"action.{str(event_name).lower()}"
        for d in list(getattr(player, "owned_domains", []) or []):
            if self.game._domain_recurring_passive_on_build_turn_cooldown(d):
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
        if not player or getattr(self.game, "phase", None) != "action":
            return
        for d in list(getattr(player, "owned_domains", []) or []):
            if self.game._domain_recurring_passive_on_build_turn_cooldown(d):
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
                    if (self.game.action_required or {}).get("action") == "domain_self_convert":
                        return
            elif rest_low.startswith("exchange") and "wild" in rest_low:
                self._execute_action_start_wild_gain_exchange(rest, player, d)
                if (self.game.action_required or {}).get("action") == "harvest_wild_gain_exchange":
                    return

    def _execute_action_start_wild_gain_exchange(self, command, player, domain):
        """Fire a `exchange <res> N wild M` passive at action.start.

        Delegates to the existing wild-gain exchange machinery but stamps the
        pending_required_choice with context="action_start" so the resolution
        handler resumes the action phase instead of harvest.
        """
        result = self.game.harvest._execute_wild_gain_exchange_payout(command, player.player_id)
        prc = getattr(self.game, "pending_required_choice", None)
        if prc and prc.get("kind") == "harvest_wild_gain_exchange":
            prc["context"] = "action_start"
            prc["domain_name"] = getattr(domain, "name", "Domain")

    def _parse_action_end_choose(self, passive_text):
        """Parse `action.end choose <r1> <n1> <r2> <n2>` passive into a choose_resource queue item.

        Returns a dict with mode="choose_resource" and choices=[(r, n), ...], or None.
        """
        s = (passive_text or "").strip()
        low = s.lower()
        if not low.startswith("action.end"):
            return None
        rest = s[len("action.end"):].strip()
        if not rest.lower().startswith("choose"):
            return None
        tokens = rest.split()
        # tokens: ["choose", r1, n1, r2, n2, ...]
        if len(tokens) < 5 or tokens[0].lower() != "choose":
            return None
        choices = []
        i = 1
        while i + 1 < len(tokens):
            res = tokens[i].strip().lower()
            try:
                amt = int(tokens[i + 1])
            except (ValueError, TypeError):
                return None
            if res not in ("g", "s", "m", "v") or amt <= 0:
                return None
            choices.append((res, amt))
            i += 2
        if len(choices) < 2:
            return None
        return {"mode": "choose_resource", "choices": choices}

    def _collect_action_end_manipulate_queue(self, active_player):
        out = []
        for d in list(getattr(active_player, "owned_domains", []) or []):
            if self.game._domain_recurring_passive_on_build_turn_cooldown(d):
                continue
            raw = (getattr(d, "passive_effect", None) or "").strip()
            # Try choose_resource first (action.end choose ...)
            choose_kv = self._parse_action_end_choose(raw)
            if choose_kv:
                out.append({
                    "domain_name": getattr(d, "name", "Domain"),
                    "mode": "choose_resource",
                    "choices": choose_kv["choices"],
                })
                continue
            kv = self._parse_manipulate_action_end(raw)
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
        for p in self.game.player_list:
            if p.player_id == active_pid:
                continue
            # Resting seat is "not in play" for negative effects, but pay_to_player
            # is a positive effect for the target so it stays eligible.
            if take_or_pay == "take" and not self.game._player_is_negative_effect_target(p):
                continue
            if take_or_pay == "take" and self.game._player_has_take_immunity(p):
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
        active = self.game._player_by_id(active_pid)
        if not active:
            return False
        q = self._collect_action_end_manipulate_queue(active)
        self.game.pending_action_end_queue = q
        if not q:
            return False
        self.game.phase = "action_end_pending"
        blocked = self._drain_action_end_manipulate_queue()
        if not blocked:
            self.game.phase = "action"
        return blocked

    def _drain_action_end_manipulate_queue(self):
        while self.game.pending_action_end_queue:
            item = self.game.pending_action_end_queue[0]
            active_pid = self.game.lifecycle.current_player_id()
            active = self.game._player_by_id(active_pid)
            if not active:
                self.game.pending_action_end_queue = []
                return False
            mode = item["mode"]
            # choose_resource items (Lost Gardens): prompt player to pick one of several gains.
            if mode == "choose_resource":
                choices = list(item.get("choices") or [])
                if not choices:
                    self.game.pending_action_end_queue.pop(0)
                    continue
                self.game.action_required["id"] = active_pid
                self.game.action_required["action"] = "domain_choose_resource"
                self.game.pending_required_choice = {
                    "kind": "domain_choose_resource",
                    "player_id": active_pid,
                    "choices": choices,
                    "domain_name": item.get("domain_name", "Domain"),
                    "context": "action_end_queue",
                }
                return True
            kv = item["kv"]
            # self_convert items (Rime Temple, Switch Wind Fortress): prompt player to
            # optionally trade one resource for another. Skip silently if unaffordable.
            if mode == "self_convert":
                pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
                can_pay = bool(pay_k) and self.game.choose._player_can_afford_self_convert_resources(active, pay_k, pay_n)
                if not can_pay:
                    self.game.pending_action_end_queue.pop(0)
                    continue
                self.game.action_required["id"] = active_pid
                self.game.action_required["action"] = "domain_self_convert"
                self.game.pending_required_choice = {
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
                self.game.pending_action_end_queue.pop(0)
                if optional_effective:
                    continue
                self.game.pending_action_end_queue = []
                return False
            gain_k, gain_n = parsed.get("gain_k"), int(parsed.get("gain_n") or 0)
            res_k, res_n = parsed.get("res_k"), int(parsed.get("res_n") or 0)
            opts = parsed["options"]
            if mode == "pay_to_player":
                ap = self.game._player_by_id(active_pid)
                pk, pn = _parse_resource_kv(kv.get("pay", ""))
                if not pk or pn <= 0 or int(self._player_resource_tuple(ap)[{"g": 0, "s": 1, "m": 2, "v": 3}[pk]]) < pn:
                    self.game.pending_action_end_queue.pop(0)
                    if optional_effective:
                        continue
                    self.game.pending_action_end_queue = []
                    return False
            self.game.action_required["id"] = active_pid
            self.game.action_required["action"] = "choose_player"
            self.game.pending_required_choice = {
                "kind": "domain_manipulate_player",
                "player_id": active_pid,
                "item": item,
                "options": opts,
                "allow_skip": optional_effective,
            }
            return True
        return False

    def _apply_manipulate_player_choice(self, active_pid, target_pid, item):
        active = self.game._player_by_id(active_pid)
        victim = self.game._player_by_id(target_pid)
        if not active or not victim:
            return
        mode = item["mode"]
        kv = item["kv"]
        before_a = self.game._player_scores_line(active)
        before_v = self.game._player_scores_line(victim)
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
        after_a = self.game._player_scores_line(active)
        after_v = self.game._player_scores_line(victim)
        bank_vp_note = ""
        if mode == "pay_to_player" and gain_k == "v" and gain_n > 0:
            bank_vp_note = f" (+{gain_n} VP from bank, not from target)"
        source_label = item.get("source_label") or "end-of-action"
        self.game._log_game_event(
            f"{self.game._player_label(active_pid)} {source_label} \"{item.get('domain_name')}\" vs "
            f"{self.game._player_label(target_pid)}: active {before_a} -> {after_a}; target {before_v} -> {after_v}"
            f"{bank_vp_note}"
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
        for stack in self.game.monster_grid:
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
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} could not use \"{getattr(domain, 'name', 'Domain')}\" "
                f"(no accessible monsters)."
            )
            return
        if len(options) == 1:
            self._apply_monster_strength_boost(options[0]["monster_id"], delta)
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} activated \"{getattr(domain, 'name', 'Domain')}\" "
                f"on \"{options[0].get('name')}\" (+{delta} strength cost)."
            )
            return
        self.game.action_required["id"] = player.player_id
        self.game.action_required["action"] = "choose_monster_strength"
        self.game.pending_required_choice = {
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
        for stack in self.game.monster_grid:
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
                before = self.game._player_scores_line(player)
                payout = self._prompt_or_apply_self_convert(effect, player, domain)
                if isinstance(self.game.action_required, dict) and self.game.action_required.get("action"):
                    self.game._log_game_event(
                        f"{self.game._player_label(player.player_id)} triggered activation effect on \"{getattr(domain, 'name', 'Domain')}\" and is choosing options."
                    )
                    return
                if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
                    return
                player.gold_score = int(player.gold_score) + payout[0]
                player.strength_score = int(player.strength_score) + payout[1]
                player.magic_score = int(player.magic_score) + payout[2]
                player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
                self.game.harvest._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
                after = self.game._player_scores_line(player)
                if before != after:
                    self.game._log_game_event(
                        f"{self.game._player_label(player.player_id)} activated domain \"{getattr(domain, 'name', 'Domain')}\"; scores {before} -> {after}"
                    )
                return
            if mode in ("take_from_player", "pay_to_player"):
                self._prompt_activation_manipulate_player(player, domain, kv)
                return
        before = self.game._player_scores_line(player)
        _prior_action = (self.game.action_required or {}).get("action", "")
        _prior_concurrent = getattr(self.game, "concurrent_action", None)
        # Tag any bare-verb `slay` payout in the effect with this domain's name so the
        # prompt knows what to call out. Cleared in finally so the tag never leaks
        # into other payout paths (harvest, action.end queues, etc.).
        self.game._immediate_slay_source_label = getattr(domain, "name", "Domain")
        try:
            payout = self.game.payouts.execute_special_payout(effect, player.player_id, auto_apply_single_choice=False)
        finally:
            self.game._immediate_slay_source_label = None
        _new_action = (self.game.action_required or {}).get("action", "")
        _new_concurrent = getattr(self.game, "concurrent_action", None)
        if (_new_action and _new_action != _prior_action) or (_new_concurrent is not _prior_concurrent):
            # Compound payouts (e.g. Cloudrider's Camp: "s 3 + choose <citizens ...>") resolve the
            # resource leg before the blocking choose; apply those gains now so they are not lost.
            if isinstance(payout, list) and len(payout) >= 4 and payout[0] != -9999:
                player.gold_score = int(player.gold_score) + payout[0]
                player.strength_score = int(player.strength_score) + payout[1]
                player.magic_score = int(player.magic_score) + payout[2]
                player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
                self.game.harvest._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} triggered activation effect on \"{getattr(domain, 'name', 'Domain')}\" and is choosing options."
            )
            return
        if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
            return
        player.gold_score = int(player.gold_score) + payout[0]
        player.strength_score = int(player.strength_score) + payout[1]
        player.magic_score = int(player.magic_score) + payout[2]
        player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
        self.game.harvest._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
        after = self.game._player_scores_line(player)
        if before != after:
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} activated domain \"{getattr(domain, 'name', 'Domain')}\"; scores {before} -> {after}"
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
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} could not use \"{domain_name}\" "
                f"(no eligible players)."
            )
            return
        if mode == "pay_to_player":
            pk, pn = _parse_resource_kv(kv.get("pay", ""))
            res_idx = {"g": 0, "s": 1, "m": 2, "v": 3}
            if not pk or pn <= 0 or int(self._player_resource_tuple(player)[res_idx[pk]]) < pn:
                self.game._log_game_event(
                    f"{self.game._player_label(player.player_id)} could not use \"{domain_name}\" "
                    f"(insufficient resources to pay)."
                )
                return
        item = {"domain_name": domain_name, "mode": mode, "kv": kv, "source_label": "activated"}
        self.game.action_required["id"] = player.player_id
        self.game.action_required["action"] = "choose_player"
        self.game.pending_required_choice = {
            "kind": "domain_manipulate_player",
            "player_id": player.player_id,
            "item": item,
            "options": parsed["options"],
            "allow_skip": optional_effective,
            "from_activation": True,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player.player_id)} triggered activation effect on \"{domain_name}\" and is choosing a player."
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
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} could not use \"{domain_name}\" "
                f"(no owned {kind}s to return)."
            )
            return
        self.game.action_required["id"] = player.player_id
        self.game.action_required["action"] = "choose_owned_card"
        self.game.pending_required_choice = {
            "kind": "domain_return_owned",
            "player_id": player.player_id,
            "domain_name": domain_name,
            "card_kind": kind,
            "resource": parsed["resource"],
            "amount": int(parsed["amount"]),
            "allow_skip": optional,
            "options": options,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player.player_id)} triggered activation effect on \"{domain_name}\" and is choosing a {kind} to return."
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
        player = self.game._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        source_name = getattr(self.game, "_immediate_slay_source_label", None) or "Effect"
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
        for p in self.game.player_list:
            if p.player_id == active_pid:
                continue
            if not self.game._player_is_negative_effect_target(p):
                continue
            # `take_owned` removes a card from the target's tableau, so it is a
            # "take" effect under Castle of the Seven Suns' operator-icon
            # reading ("you" includes your cards). Players with `immunity.take`
            # are not eligible targets.
            if self.game._player_has_take_immunity(p):
                continue
            if not list(getattr(p, attr, []) or []):
                continue
            options.append({
                "token": "player",
                "player_id": p.player_id,
                "name": getattr(p, "name", "?"),
            })
        if not options:
            self.game._log_game_event(
                f"{self.game._player_label(active_pid)} could not use \"{domain_name}\" "
                f"(no other player owns a {kind})."
            )
            return
        self.game.action_required["id"] = active_pid
        self.game.action_required["action"] = "choose_player"
        self.game.pending_required_choice = {
            "kind": "domain_take_owned",
            "player_id": active_pid,
            "domain_name": domain_name,
            "card_kind": kind,
            "pick": pick,
            "allow_skip": optional,
            "options": options,
            "from_activation": True,
        }
        self.game._log_game_event(
            f"{self.game._player_label(active_pid)} triggered activation effect on \"{domain_name}\" "
            f"and is choosing a player to steal a {kind} from."
        )

    def _monster_stack_index_for_area(self, area):
        """Return the monster_grid stack index assigned to `area` at game setup, or None."""
        if not area:
            return None
        mapping = list(getattr(self.game, "monster_stack_areas", []) or [])
        for i, a in enumerate(mapping):
            if a == area:
                return i
        return None

    def _unexhaust_stack_top_if_present(self, stack):
        """If stack's top card is an exhausted-slot card, pop it back to the pool. Returns True if popped.

        Recognized exhausted-slot cards: a plain Exhausted token, or a revealed
        non-monster Event (a spent activation or in-play passive event). Returning
        the event to the exhausted stack lets it be re-revealed and re-fire later;
        an in-play passive stops applying while it is back in the deck. Monster
        events are slayable board cards and are never recycled here.
        """
        if not stack:
            return False
        # Recruit the King's Guard sits under its un-hired guards. Pull those back
        # to the reserve first so the event beneath becomes the stack top and can
        # recycle like any other spent event placeholder.
        self.game.events.retract_kings_guard_from_stack(stack)
        if not stack:
            return False
        top = stack[-1]
        is_plain_exhausted = getattr(top, "name", "") == "Exhausted"
        is_nonmonster_event = isinstance(top, Event) and not bool(getattr(top, "is_monster", 0))
        if not (is_plain_exhausted or is_nonmonster_event):
            return False
        if is_nonmonster_event:
            # A "rest of the game" grant (Blessed Lands / Dark Lord Rising) is
            # tied to its card being in play: reverse it as the event leaves.
            self.game.events.on_event_unexhausted(top)
        stack.pop(-1)
        self.game.exhausted_stack.append(top)
        self.game.exhausted_count = max(0, int(self.game.exhausted_count) - 1)
        return True

    def _return_monster_to_stack(self, monster):
        """Place a previously-owned monster back on its area stack. Handles un-exhausting if needed."""
        stack_idx = self._monster_stack_index_for_area(getattr(monster, "area", None))
        if stack_idx is None:
            return False
        stack = self.game.monster_grid[stack_idx]
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
        stack = self.game.citizen_grid[stack_idx]
        self._unexhaust_stack_top_if_present(stack)
        if stack:
            stack[-1].toggle_accessibility(False)
        # Citizens always come back face-up on the board (face-down only applies to owned tableau cards).
        self.game._citizen_set_flipped(citizen, False)
        stack.append(citizen)
        return True

