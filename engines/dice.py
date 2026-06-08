"""DiceEngine -- composed sub-engine of Game.

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


class DiceEngine:
    def __init__(self, game):
        self.game = game

    def _begin_concurrent_flip_one_citizen(self, buyer_player_id):
        """Start unordered concurrent prompt: each player with ≥1 unflipped citizen picks one to flip."""
        if getattr(self.game, "concurrent_action", None):
            raise ValueError("Another concurrent prompt is already active.")
        targets = []
        for p in list(getattr(self.game, "player_list", []) or []):
            if not self.game._player_is_negative_effect_target(p):
                continue
            oc = list(getattr(p, "owned_citizens", []) or [])
            if any(not getattr(c, "is_flipped", False) for c in oc):
                targets.append(p.player_id)
        if not targets:
            self.game._log_game_event(
                f"{self.game._player_label(buyer_player_id)} played Cursed Cavern — no player had a citizen to flip."
            )
            return
        self.game.concurrent_action = _new_concurrent_action(
            "flip_one_citizen",
            targets,
            data={"buyer_id": buyer_player_id, "source": "cursed_cavern"},
        )
        self.game._log_game_event(
            f"{self.game._player_label(buyer_player_id)} played Cursed Cavern (+4 magic); "
            f"each player with citizens must choose one to flip face-down."
        )

    def _iter_roll_set_one_die_effects(self, player):
        """Yield owned-domain `roll.set_one_die` passive specs for the player.

        Recognized KV options:
          target=N       absolute set to N (1..6)
          subtract=N     relative: new value = old - N
          add=N          relative: new value = old + N
          cost=g:N | cost=g_per_owned_role:<role>    optional; omitted = free
        """
        for d in list(getattr(player, "owned_domains", []) or []):
            if self.game._domain_recurring_passive_on_build_turn_cooldown(d):
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
            n = self.game._owned_citizen_count_for_role_selector(player, role)
            return {"gold": n}
        if spec in ("g:per_owned_holy_citizen", "per_owned_holy_citizen"):
            n = self.game._owned_citizen_count_for_role_selector(player, "holy_citizen")
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
        before = self.game._player_scores_line(player)
        if gold_cost:
            player.gold_score = int(player.gold_score) - gold_cost
        after = self.game._player_scores_line(player)
        if gold_cost:
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} used {effect.get('domain_name')} "
                f"(pay {gold_cost} gold) during roll: die {old_value} -> {new_value}; scores {before} -> {after}"
            )
        else:
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} used {effect.get('domain_name')} "
                f"during roll: die {old_value} -> {new_value}"
            )

    def _compute_roll_events(self, die_one, die_two):
        """Return the list of event tokens for the given FINAL dice.

        Centralizes "what happened on the dice this roll" so that any listener
        (roll-phase passives now, harvest/action effects later) can ask the
        same question without re-deriving things like "were the dice
        doubles?". Called from `finalize_roll` against the post-modification
        dice so the answer agrees with `self.game.die_one == self.game.die_two` and
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

        Reads `self.game.roll_events`, which is populated in `finalize_roll` from
        the FINAL dice (post-modification). A player who spent roll modifiers
        to land on e.g. doubles legitimately triggered the event; the engine
        treats the final dice as the source of truth.
        """
        events = set(getattr(self.game, "roll_events", None) or [])
        if not events:
            return
        for p in list(getattr(self.game, "player_list", []) or []):
            for d in list(getattr(p, "owned_domains", []) or []):
                if self.game._domain_recurring_passive_on_build_turn_cooldown(d):
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
                before = self.game._player_scores_line(p)
                if res == "g":
                    p.gold_score = int(p.gold_score) + amount
                elif res == "s":
                    p.strength_score = int(p.strength_score) + amount
                elif res == "m":
                    p.magic_score = int(p.magic_score) + amount
                elif res == "v":
                    p.victory_score = int(getattr(p, "victory_score", 0)) + amount
                after = self.game._player_scores_line(p)
                self.game._log_game_event(
                    f"{self.game._player_label(p.player_id)} \"{getattr(d, 'name', 'Domain')}\" triggered "
                    f"({event}); scores {before} -> {after}"
                )

    def _apply_board_event_roll_effects(self, d1, d2):
        """Check all board stacks for Event cards with roll effects matching d1 or d2.

        Iterates monster_grid (plus citizen_grid, domain_grid for future-proofing).
        When an Event card's roll_match1 equals d1 or d2, fires its roll_effect.
        """
        active_player_id = self.game.lifecycle.current_player_id()
        grids = [self.game.monster_grid, self.game.citizen_grid, self.game.domain_grid]
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
          banish_center_citizen [optional]  — active player banishes (or may
                                              skip) a citizen from center stacks
          banish_center_domain [optional]   — active player banishes (or may
                                              skip) a face-up domain from center
                                              stacks; the next domain is revealed
          add_self_slay_cost s|m|g N [max=K]  — add N to THIS event's own slay
                                              cost (no choice); capped at +K
        """
        raw = (event.roll_effect or "").strip()
        if not raw:
            return
        parts = raw.split()
        verb = parts[0].lower()
        banish_center_kinds = {
            "banish_center_citizen": "citizen",
            "banish_center_domain": "domain",
        }
        if verb in banish_center_kinds:
            optional = any(p.lower() == "optional" for p in parts[1:])
            command = f"banish_center {banish_center_kinds[verb]}"
            if optional:
                command += " optional"
            self.game.payouts._execute_banish_center_payout(command, player_id)
            return

        if len(parts) < 3:
            self.game._log_game_event(
                f"Event \"{event.name}\" triggered but roll_effect is malformed: {raw!r}"
            )
            return

        resource = parts[1].lower()
        try:
            amount = int(parts[2])
        except (TypeError, ValueError):
            self.game._log_game_event(
                f"Event \"{event.name}\" triggered but amount is not an int: {parts[2]!r}"
            )
            return

        if verb == "all_lose":
            res_map = {"g": "gold_score", "s": "strength_score", "m": "magic_score"}
            attr = res_map.get(resource)
            if not attr:
                self.game._log_game_event(
                    f"Event \"{event.name}\" all_lose: unknown resource {resource!r}"
                )
                return
            for p in list(getattr(self.game, "player_list", []) or []):
                if not self.game._player_is_negative_effect_target(p):
                    self.game._log_game_event(
                        f"{self.game._player_label(p.player_id)} is resting; "
                        f"loses 0{resource} from event \"{event.name}\"."
                    )
                    continue
                current = int(getattr(p, attr, 0) or 0)
                new_val = max(0, current - amount)
                if current != new_val:
                    self.game._log_game_event(
                        f"{self.game._player_label(p.player_id)} loses {amount}{resource} "
                        f"from event \"{event.name}\" (was {current}, now {new_val})."
                    )
                else:
                    self.game._log_game_event(
                        f"{self.game._player_label(p.player_id)} loses 0{resource} "
                        f"from event \"{event.name}\" (already at {current}, floored)."
                    )
                setattr(p, attr, new_val)

        elif verb == "add_slay_cost":
            # Check if any accessible monster exists on the board.
            has_target = False
            for stack in (self.game.monster_grid or []):
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
                self.game._log_game_event(
                    f"Event \"{event.name}\" triggered add_slay_cost but no accessible "
                    f"monsters on the board; skipped."
                )
                return
            self.game.pending_event_slay_cost = {
                "player_id": player_id,
                "resource": resource,
                "amount": amount,
                "event_name": event.name,
            }
            self.game.action_required["id"] = player_id
            self.game.action_required["action"] = "event_slay_cost_choice"
            self.game._log_game_event(
                f"Event \"{event.name}\" triggered: {self.game._player_label(player_id)} must add "
                f"{amount}{resource} to a chosen monster's slay cost."
            )

        elif verb == "add_self_slay_cost":
            # Leviathan-style accrual: bump THIS event card's own slay cost by
            # `amount` of `resource` (no player choice), capped at an optional
            # `max=N` ceiling on the accumulated extra cost.
            attr_map = {"s": "extra_strength_cost", "m": "extra_magic_cost", "g": "extra_gold_cost"}
            attr = attr_map.get(resource)
            if not attr:
                self.game._log_game_event(
                    f"Event \"{event.name}\" add_self_slay_cost: unknown resource {resource!r}"
                )
                return
            cap = None
            for tok in parts[3:]:
                if tok.lower().startswith("max="):
                    try:
                        cap = int(tok.split("=", 1)[1])
                    except (TypeError, ValueError):
                        cap = None
            current = int(getattr(event, attr, 0) or 0)
            new_val = current + amount
            if cap is not None:
                new_val = min(new_val, cap)
            if new_val == current:
                self.game._log_game_event(
                    f"Event \"{event.name}\" is already at its maximum {resource} slay cost "
                    f"({current}); no token added."
                )
            else:
                setattr(event, attr, new_val)
                self.game._log_game_event(
                    f"Event \"{event.name}\" gained +{new_val - current}{resource} slay cost "
                    f"(now +{new_val}{resource})."
                )
        else:
            self.game._log_game_event(
                f"Event \"{event.name}\" triggered but unknown verb: {verb!r}"
            )

    def apply_event_slay_cost(self, player_id, monster_id=None, event_id=None):
        """Resolve the pending_event_slay_cost choice.

        The active player chooses an accessible monster (by monster_id or event_id)
        and we apply the extra cost modifier to that card.
        """
        pesc = getattr(self.game, "pending_event_slay_cost", None)
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
            for stack in (self.game.monster_grid or []):
                if not stack:
                    continue
                t = stack[-1]
                if not getattr(t, "is_accessible", False):
                    continue
                if int(getattr(t, "monster_id", -1)) == int(monster_id):
                    target = t
                    break
        elif event_id is not None:
            for stack in (self.game.monster_grid or []):
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

        self.game._log_game_event(
            f"{self.game._player_label(player_id)} applied event \"{event_name}\": "
            f"\"{getattr(target, 'name', '?')}\" slay cost +{amount}{resource}."
        )

        # Clear the pending state.
        self.game.pending_event_slay_cost = None
        self.game.action_required["id"] = self.game.game_id
        self.game.action_required["action"] = ""

