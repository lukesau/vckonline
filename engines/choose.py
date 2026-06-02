"""ChooseEngine -- composed sub-engine of Game.

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


class ChooseEngine:
    def __init__(self, game):
        self.game = game

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
                area_tok = self.game.payouts._emit_payout_token(o.get('area'))
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
        parts = self.game.payouts._tokenize_payout(s)
        if len(parts) >= 5 and parts[0].lower() == "count" and parts[1].lower() == "area":
            area = parts[2]
            resource = parts[3].lower()
            try:
                mult = int(parts[4])
            except (TypeError, ValueError):
                return None
            if mult <= 0 or resource not in ("g", "s", "m", "v"):
                return None
            if area not in self.game._active_areas():
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
        for stack in self.game.citizen_grid:
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
        self.game.harvest._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])

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
        if self.game.exhausted_stack:
            self.game.events.reveal_exhausted_onto_stack(citizen_stack)

    def _claim_specific_board_citizen(self, player_id, citizen_id):
        target = self.game._player_by_id(player_id)
        if not target:
            return False
        try:
            wanted = int(citizen_id)
        except (TypeError, ValueError):
            return False
        for stack in self.game.citizen_grid:
            if not stack:
                continue
            top = stack[-1]
            if not getattr(top, "is_accessible", False):
                continue
            if int(getattr(top, "citizen_id", -1)) != wanted:
                continue
            claimed = stack.pop(-1)
            self.game._citizen_set_flipped(claimed, False)
            target.owned_citizens.append(claimed)
            self._finalize_citizen_stack_after_claiming_top(stack)
            return True
        return False

    def _apply_choose_option(self, player_id, opt):
        target = self.game._player_by_id(player_id)
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
                    self.game.harvest._bump_harvest_delta(target, n, 0, 0, 0)
                elif t == "s":
                    target.strength_score = int(target.strength_score) + n
                    self.game.harvest._bump_harvest_delta(target, 0, n, 0, 0)
                elif t == "m":
                    target.magic_score = int(target.magic_score) + n
                    self.game.harvest._bump_harvest_delta(target, 0, 0, n, 0)
                elif t == "v":
                    target.victory_score = int(getattr(target, "victory_score", 0)) + n
                    self.game.harvest._bump_harvest_delta(target, 0, 0, 0, n)
                else:
                    return False
            return True
        if token == "count_area":
            area = opt.get("area")
            resource = (opt.get("resource") or "").strip().lower()
            mult = int(opt.get("mult", 0) or 0)
            count = int((self.game.owned_monster_attributes(player_id) or {}).get(area, 0) or 0)
            total = count * mult
            if resource == "g":
                target.gold_score = int(target.gold_score) + total
                self.game.harvest._bump_harvest_delta(target, total, 0, 0, 0)
            elif resource == "s":
                target.strength_score = int(target.strength_score) + total
                self.game.harvest._bump_harvest_delta(target, 0, total, 0, 0)
            elif resource == "m":
                target.magic_score = int(target.magic_score) + total
                self.game.harvest._bump_harvest_delta(target, 0, 0, total, 0)
            elif resource == "v":
                target.victory_score = int(getattr(target, "victory_score", 0)) + total
                self.game.harvest._bump_harvest_delta(target, 0, 0, 0, total)
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
        self.game.harvest._bump_harvest_delta(target, dg, ds, dm, dv)
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

