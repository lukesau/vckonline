"""PayoutsEngine -- composed sub-engine of Game.

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


class PayoutsEngine:
    def __init__(self, game):
        self.game = game

    def _execute_grant_domain_payout(self, player_id):
        """Grant one free domain chosen from the accessible center stacks (no cost, no role check)."""
        player = self.game._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        options = []
        for stack_idx, domain_stack in enumerate(self.game.domain_grid):
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
        source_name = getattr(self.game, "_immediate_slay_source_label", None) or "Effect"
        if not options:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} could not use \"{source_name}\" "
                f"(no domains available to take)."
            )
            return [0, 0, 0, 0]
        self.game.pending_required_choice = {
            "kind": "grant_domain_reward",
            "player_id": player_id,
            "source_name": source_name,
            "options": options,
        }
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_domain_reward"
        return [0, 0, 0, 0]

    def _apply_grant_domain_choice(self, player_id, stack_idx):
        """Acquire the chosen domain for free, running all the normal post-acquisition steps."""
        player = self.game._player_by_id(player_id)
        if not player:
            return
        domain_stacks = self.game.domain_grid
        if stack_idx < 0 or stack_idx >= len(domain_stacks):
            return
        domain_stack = domain_stacks[stack_idx]
        if not domain_stack:
            return
        top = domain_stack[-1]
        if getattr(top, "domain_id", None) is None:
            return
        source_name = (getattr(self.game, "pending_required_choice", None) or {}).get("source_name", "Effect")
        before = self.game._player_scores_line(player)
        acquired = domain_stack.pop(-1)
        acquired.acquired_turn_number = int(self.game.turn_number)
        player.owned_domains.append(acquired)
        vp_gain = int(getattr(acquired, "vp_reward", 0) or 0)
        if vp_gain:
            player.victory_score = int(getattr(player, "victory_score", 0)) + vp_gain
            self.game.harvest._bump_harvest_delta(player, 0, 0, 0, vp_gain)
        if not domain_stack and self.game.exhausted_stack:
            self.game.events.reveal_exhausted_onto_stack(domain_stack)
        after = self.game._player_scores_line(player)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} took domain \"{acquired.name}\" "
            f"via \"{source_name}\" (free); scores {before} -> {after}"
        )
        self.game.domain_effects._apply_domain_activation_effect(player, acquired)

    def _execute_build_domain_activation_payout(self, player_id, balance_hint=None):
        """Offer the active player an optional free domain build (Ararmartin Ridge).

        `balance_hint` carries the running resource totals when this runs as a leg
        of a compound payout (e.g. Ararmartin Ridge's `g 3 + build_domain`). The
        earlier `g 3` leg's gold is accumulated into the hint but not yet written
        to `player.gold_score`, so affordability must consult the hint to avoid
        reporting "no affordable domains" against the player's pre-gain gold.
        """
        player = self.game._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        if isinstance(balance_hint, dict) and "g" in balance_hint:
            available_gold = int(balance_hint.get("g", 0) or 0)
        else:
            available_gold = int(getattr(player, "gold_score", 0) or 0)
        have = self.game._player_citizen_role_totals(player)
        has_pratchett = self.game._player_has_action_effect_flag(player, "action.pratchettsplateau")
        options = []
        for stack_idx, domain_stack in enumerate(self.game.domain_grid):
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
            if self.game._player_has_action_effect_flag(player, "action.blessedlands"):
                gold_cost = max(0, gold_cost - self.game.events.blessed_lands_discount())
            if available_gold < gold_cost:
                continue
            options.append({
                "stack_idx": stack_idx,
                "domain_id": int(getattr(top, "domain_id", 0)),
                "name": getattr(top, "name", "Domain"),
                "gold_cost": gold_cost,
            })
        if not options:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} gained +3 Gold from \"Ararmartin Ridge\" "
                f"(no affordable domains available to build)."
            )
            return [0, 0, 0, 0]
        self.game.pending_required_choice = {
            "kind": "domain_build_opportunity",
            "player_id": player_id,
            "options": options,
        }
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_domain_to_build"
        return [0, 0, 0, 0]

    def _execute_banish_center_payout(self, command, player_id):
        """Parse `banish_center <kind> [optional]` and prompt for a center-stack card.

        `kind` is one of citizen / monster / domain. Gnoll Bonewitch-style banish
        removes an accessible card from the board, not from a player's tableau.
        The removed card lands in the global banish pile.
        """
        parts = (command or "").strip().split()
        if not parts or parts[0].lower() != "banish_center":
            return [-9999, 0, 0, 0]
        if len(parts) < 2:
            return [-9999, 0, 0, 0]
        kind = parts[1].lower()
        optional = any(p.lower() == "optional" for p in parts[2:])
        if kind not in ("citizen", "monster", "domain"):
            return [-9999, 0, 0, 0]
        options = []
        if kind == "citizen":
            for i, stack in enumerate(list(getattr(self.game, "citizen_grid", []) or [])):
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
        elif kind == "domain":
            for i, stack in enumerate(list(getattr(self.game, "domain_grid", []) or [])):
                if not stack:
                    continue
                top = stack[-1]
                if not getattr(top, "is_accessible", False) or not getattr(top, "is_visible", True):
                    continue
                if getattr(top, "domain_id", None) is None:
                    continue  # Event/Exhausted placeholder — not a valid domain target
                options.append({
                    "token": "domain.center",
                    "idx": i,
                    "name": getattr(top, "name", "?"),
                    "domain_id": int(getattr(top, "domain_id", -1)),
                    "gold_cost": int(getattr(top, "gold_cost", 0) or 0),
                })
        else:  # monster
            for i, stack in enumerate(list(getattr(self.game, "monster_grid", []) or [])):
                if not stack:
                    continue
                top = stack[-1]
                if not getattr(top, "is_accessible", False):
                    continue
                if getattr(top, "monster_id", None) is None:
                    continue  # Event/Exhausted placeholder — not a valid monster target
                options.append({
                    "token": "monster.center",
                    "idx": i,
                    "name": getattr(top, "name", "?"),
                    "monster_id": int(getattr(top, "monster_id", -1)),
                    "strength_cost": int(getattr(top, "strength_cost", 0) or 0),
                    "magic_cost": int(getattr(top, "magic_cost", 0) or 0),
                })
        if not options:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} had no center-stack {kind} to banish; effect skipped."
            )
            return [0, 0, 0, 0]
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_owned_card"
        self.game.pending_required_choice = {
            "kind": "banish_center_card",
            "player_id": player_id,
            "card_kind": kind,
            "options": options,
            "allow_skip": optional,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} is choosing a center-stack {kind} to banish."
        )
        return [0, 0, 0, 0]

    def _banish_center_citizen(self, stack_idx):
        """Remove the accessible top citizen from a board stack and push it to the banish pile."""
        stacks = list(getattr(self.game, "citizen_grid", []) or [])
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
        self.game._citizen_set_flipped(banished, False)
        self.game.banish_pile.append(banished)
        self.game.choose._finalize_citizen_stack_after_claiming_top(stack)
        return banished

    def _banish_center_monster(self, stack_idx):
        """Remove the top monster from a center stack and push it to the banish pile."""
        from cards import Event as _Event
        stacks = list(getattr(self.game, "monster_grid", []) or [])
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
        self.game.banish_pile.append(banished)
        if stack:
            stack[-1].toggle_accessibility(True)
        elif self.game.exhausted_stack:
            self.game.events.reveal_exhausted_onto_stack(stack)
        return banished

    def _banish_center_domain(self, stack_idx):
        """Banish the face-up top domain of a center stack, then reveal the next domain.

        Mirrors the Giants of Ostendaar card text: the banished domain leaves the
        game and, if the stack still holds a card, the next one is flipped face-up
        immediately (rather than deferring to the turn-end reveal). An emptied
        stack refills from the exhausted deck like a normal purchase.
        """
        stacks = list(getattr(self.game, "domain_grid", []) or [])
        if stack_idx < 0 or stack_idx >= len(stacks):
            return None
        stack = stacks[stack_idx]
        if not stack:
            return None
        top = stack[-1]
        if not getattr(top, "is_accessible", False) or not getattr(top, "is_visible", True):
            return None
        if getattr(top, "domain_id", None) is None:
            return None  # Event/Exhausted placeholder — not banishable as a domain
        banished = stack.pop(-1)
        self.game.banish_pile.append(banished)
        if stack:
            stack[-1].toggle_visibility(True)
            stack[-1].toggle_accessibility(True)
        elif self.game.exhausted_stack:
            self.game.events.reveal_exhausted_onto_stack(stack)
        return banished

    def _maybe_fire_northern_wall_banish(self, player_id):
        """If the active player owns The Northern Wall, open an optional Minion-banish prompt."""
        player = self.game._player_by_id(player_id)
        if not player:
            return
        if not self.game._player_has_action_effect_flag(player, "action.northernwall"):
            return
        options = []
        for stack_idx, stack in enumerate(getattr(self.game, "monster_grid", []) or []):
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
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_owned_card"
        self.game.pending_required_choice = {
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
        tableau and lands on the global `self.game.banish_pile`. Distinct from
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
        player = self.game._player_by_id(player_id)
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
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} had no {kind} to banish; effect skipped."
            )
            return [0, 0, 0, 0]
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_owned_card"
        self.game.pending_required_choice = {
            "kind": "banish_owned_card",
            "player_id": player_id,
            "card_kind": kind,
            "options": options,
            "allow_skip": optional,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} is choosing a {kind} to banish."
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
            self.game._citizen_set_flipped(citizen, False)
        del player.owned_citizens[src_idx]
        self.game.banish_pile.append(citizen)
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
        for p in self.game.player_list:
            if p.player_id == player_id:
                continue
            if not self.game._player_is_negative_effect_target(p):
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
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} could not flip a citizen (no eligible tableau)."
            )
            return [0, 0, 0, 0]
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_player"
        self.game.pending_required_choice = {
            "kind": "monster_flip_citizen_targeted",
            "player_id": player_id,
            "stage": "player",
            "options": options,
            "allow_skip": optional,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} is choosing a player to flip a citizen from."
        )
        return [0, 0, 0, 0]

    def _execute_steal_citizen_payout(self, command, player_id):
        """Hobb's End: steal a citizen (cost <= max_cost) from an opponent's tableau.

        Grammar: steal_citizen gold_cost<=N
        The stolen citizen is moved to the acting player's tableau (not banished).
        """
        parts = (command or "").strip().split()
        max_cost = 2
        for p in parts[1:]:
            if p.lower().startswith("gold_cost<="):
                try:
                    max_cost = int(p.split("<=", 1)[1])
                except (ValueError, IndexError):
                    pass
        options = []
        for p in self.game.player_list:
            if p.player_id == player_id:
                continue
            if not self.game._player_is_negative_effect_target(p):
                continue
            owned = list(getattr(p, "owned_citizens", []) or [])
            eligible = [c for c in owned if int(getattr(c, "gold_cost", 0) or 0) <= max_cost]
            if not eligible:
                continue
            options.append({
                "token": "player",
                "player_id": p.player_id,
                "name": getattr(p, "name", "?"),
            })
        if not options:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} could not use \"Hobb's End\" "
                f"(no opponents have citizens costing {max_cost}g or less)."
            )
            return [0, 0, 0, 0]
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_player"
        self.game.pending_required_choice = {
            "kind": "steal_citizen",
            "player_id": player_id,
            "max_cost": max_cost,
            "item": {"domain_name": "Hobb's End"},
            "explain": f"Choose a player to steal a citizen (cost ≤{max_cost}g) from (Hobb's End).",
            "options": options,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} is choosing a player to steal a citizen from (Hobb's End)."
        )
        return [0, 0, 0, 0]

    def _execute_banish_player_citizen_payout(self, player_id):
        """Sunder Bay: choose a player, then banish one of their citizens permanently."""
        options = []
        for p in self.game.player_list:
            if p.player_id == player_id:
                continue
            if not self.game._player_is_negative_effect_target(p):
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
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} could not use \"Sunder Bay\" "
                f"(no opponents have citizens)."
            )
            return [0, 0, 0, 0]
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_player"
        self.game.pending_required_choice = {
            "kind": "banish_player_citizen",
            "player_id": player_id,
            "stage": "player",
            "item": {"domain_name": "Sunder Bay"},
            "options": options,
            "allow_skip": False,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} is choosing a player to banish a citizen from (Sunder Bay)."
        )
        return [0, 0, 0, 0]

    def _execute_banish_random_player_monster_payout(self, player_id):
        """Wandering Flame: choose a player, then a random monster from their tableau is banished."""
        options = []
        for p in self.game.player_list:
            if p.player_id == player_id:
                continue
            if list(getattr(p, "owned_monsters", []) or []):
                options.append({
                    "token": "player",
                    "player_id": p.player_id,
                    "name": getattr(p, "name", "?"),
                })
        if not options:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} could not use \"Wandering Flame\" "
                f"(no opponents have monsters)."
            )
            return [0, 0, 0, 0]
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_player"
        self.game.pending_required_choice = {
            "kind": "banish_random_player_monster",
            "player_id": player_id,
            "item": {"domain_name": "Wandering Flame"},
            "explain": "A random monster from the chosen player's tableau will be permanently banished.",
            "options": options,
            "allow_skip": False,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} is choosing a player to banish a random monster from (Wandering Flame)."
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
        player = self.game._player_by_id(player_id)
        if not player:
            return [-9999, 0, 0, 0]
        prior_action = (self.game.action_required or {}).get("action", "")
        prior_concurrent = getattr(self.game, "concurrent_action", None)
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
            new_action = (self.game.action_required or {}).get("action", "")
            new_concurrent = getattr(self.game, "concurrent_action", None)
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

    def _has_top_level_plus(self, s):
        """Return True if `s` contains a ` + ` token outside any `<...>` group.

        Used by `execute_special_payout` to detect compound payouts
        (e.g. `<domains> + <citizens>`, `s 5 + slay`) without splitting on the
        `+` inside a citizens-where extras clause like `<citizens + v 1>`.
        Quoting via `"` is honored the same way as `_tokenize_payout` so
        multi-word area names that happen to contain `+` (none today, but
        consistent with the tokenizer) cannot be split either.
        """
        text = s or ""
        if " + " not in text:
            return False
        depth = 0
        in_quote = False
        n = len(text)
        i = 0
        while i < n:
            ch = text[i]
            if ch == '"':
                in_quote = not in_quote
            elif not in_quote and ch == "<":
                depth += 1
            elif not in_quote and ch == ">":
                depth = max(0, depth - 1)
            elif (
                not in_quote
                and depth == 0
                and ch == " "
                and i + 2 < n
                and text[i + 1] == "+"
                and text[i + 2] == " "
            ):
                return True
            i += 1
        return False

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
            self.game.pending_payout_continuation = None
            return
        self.game.pending_payout_continuation = {
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
        cont = getattr(self.game, "pending_payout_continuation", None)
        if not cont:
            self._maybe_resume_post_slay_continuation()
            return
        self.game.pending_payout_continuation = None
        player_id = cont.get("player_id")
        parts = [p for p in (cont.get("parts") or []) if p]
        if not parts or not player_id:
            self._maybe_resume_post_slay_continuation()
            return
        balance_hint = cont.get("balance_hint")
        if len(parts) == 1:
            payout = self.execute_special_payout(parts[0], player_id, balance_hint=balance_hint)
        else:
            payout = self._execute_compound_payout(" + ".join(parts), player_id, balance_hint=balance_hint)
        if not (isinstance(payout, list) and len(payout) >= 4):
            self._maybe_resume_post_slay_continuation()
            return
        if payout[0] == -9999:
            self._maybe_resume_post_slay_continuation()
            return
        if payout[0] == 0 and payout[1] == 0 and payout[2] == 0 and payout[3] == 0:
            self._maybe_resume_post_slay_continuation()
            return
        player = self.game._player_by_id(player_id)
        if not player:
            self._maybe_resume_post_slay_continuation()
            return
        player.gold_score = int(player.gold_score) + payout[0]
        player.strength_score = int(player.strength_score) + payout[1]
        player.magic_score = int(player.magic_score) + payout[2]
        player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
        self.game.harvest._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
        self._maybe_resume_post_slay_continuation()

    def _maybe_resume_post_slay_continuation(self):
        """Drain a stashed may-slay resume if the engine is idle.

        Stashed by the `slay_monster_payment` handler when the slain monster's
        `special_reward` opened a follow-up prompt (so the handler couldn't
        immediately call `_resume_after_immediate_slay` without clobbering the
        new prompt). Fires only when every prompt the special reward chained
        has resolved — i.e. no `action_required.action`, no
        `pending_payout_continuation`, and no `concurrent_action`.
        """
        cont = getattr(self.game, "pending_post_slay_resume", None)
        if not cont:
            return
        ar = self.game.action_required if isinstance(self.game.action_required, dict) else None
        if ar and (ar.get("action") or ""):
            return
        if getattr(self.game, "pending_payout_continuation", None):
            return
        if getattr(self.game, "concurrent_action", None):
            return
        self.game.pending_post_slay_resume = None
        resume_kind = cont.get("resume_kind", "domain_activation")
        self.game.slay._resume_after_immediate_slay(resume_kind)

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
            return self.game.domain_effects._execute_manipulate_resources_payout(raw, player_id)
        if low == "slay":
            return self.game.slay._execute_slay_payout(player_id)
        if low.startswith("steal_citizen"):
            return self._execute_steal_citizen_payout(raw, player_id)
        if low.startswith("steal"):
            return self.game.harvest._execute_steal_payout(raw, player_id)
        if low.startswith("take_owned"):
            return self.game.domain_effects._execute_take_owned_payout(raw, player_id)
        # Compound payouts split on top-level " + " must be dispatched BEFORE
        # the bracket shortcuts (`<domains>`, `<citizens>`) so a string like
        # `<domains> + <citizens>` doesn't get hijacked by the first shortcut
        # and lose the rest of the compound. We use a top-level scanner so
        # we don't split on `+` that lives inside a `<citizens + v 1>` clause.
        if not low.startswith("choose") and self._has_top_level_plus(raw):
            return self._execute_compound_payout(
                raw,
                player_id,
                auto_apply_single_choice=auto_apply_single_choice,
                balance_hint=balance_hint,
                suppress_exchange_optional_prompt=suppress_exchange_optional_prompt,
            )
        if low == "<domains>" or low.startswith("<domains"):
            return self._execute_grant_domain_payout(player_id)
        # Defensive fallback for a bare `<citizens ...>` token (no leading
        # `choose `). The canonical form for "gain a citizen of your choice"
        # rewards is `choose <citizens>` (with optional `where ...`), and every
        # other monster in the DB stores it that way. Historically a few rows
        # (Frost Ogre, Wendigo) shipped without the `choose ` prefix, which
        # silently fell through to the default `case _:` branch and returned
        # the `-9999` sentinel without opening a prompt. Normalize to the
        # canonical choose form so future malformed rows don't repeat the bug.
        if low == "<citizens>" or low.startswith("<citizens"):
            return self.execute_special_payout(
                f"choose {raw}",
                player_id,
                auto_apply_single_choice=auto_apply_single_choice,
                balance_hint=balance_hint,
                suppress_exchange_optional_prompt=suppress_exchange_optional_prompt,
            )
        if low == "build_domain":
            return self._execute_build_domain_activation_payout(player_id, balance_hint=balance_hint)
        if low == "concurrent_flip_one_citizen":
            self.game.dice._begin_concurrent_flip_one_citizen(player_id)
            return [0, 0, 0, 0]
        if low.startswith("flip_citizen"):
            return self._execute_flip_citizen_payout(raw, player_id)
        if low == "flip_opponent_citizen":
            result = self._execute_flip_citizen_payout("flip_citizen targeted", player_id)
            prc = getattr(self.game, "pending_required_choice", None)
            if prc and prc.get("kind") == "monster_flip_citizen_targeted":
                prc["explain"] = "Choose a player to flip one of their citizens face-down (Laborium)."
            return result
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
        if first_word == "p":
            # Maps (Crimson Seas) have no slot in the [g, s, m, v] payout vector,
            # so grant them directly to the player (mirrors how the choose engine
            # awards maps) and return an empty vector.
            try:
                amount = int(second_word)
            except (TypeError, ValueError):
                payout[0] = -9999
                return payout
            target_p = self.game._player_by_id(player_id)
            if not target_p:
                payout[0] = -9999
                return payout
            target_p.map_score = int(getattr(target_p, "map_score", 0)) + amount
            self.game.harvest._bump_harvest_delta(target_p, 0, 0, 0, 0, amount)
            return [0, 0, 0, 0]
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
                        # Filtered count: flipped citizens skip their own
                        # harvest payouts and are excluded from role spends,
                        # so they also do not contribute to "per owned
                        # citizen" payouts. Mirrors the flipped-exclusion
                        # already used by `count owned_citizen_name`.
                        # `calc_roles()['owned_citizens']` intentionally
                        # stays as the raw `len(owned_citizens)` (it is the
                        # literal pile size used by serialization and Duke
                        # scoring, the latter after every citizen is
                        # unflipped for final scoring).
                        player_oc = self.game._player_by_id(player_id)
                        if not player_oc:
                            payout[0] = -9999
                        else:
                            n_oc = sum(
                                1 for c in list(getattr(player_oc, "owned_citizens", []) or [])
                                if not getattr(c, "is_flipped", False)
                            )
                            try:
                                mult_oc = int(split_command[3])
                            except (TypeError, ValueError):
                                payout[0] = -9999
                                mult_oc = None
                            if mult_oc is not None:
                                match third_word:
                                    case 'g':
                                        payout[0] = n_oc * mult_oc
                                    case 's':
                                        payout[1] = n_oc * mult_oc
                                    case 'm':
                                        payout[2] = n_oc * mult_oc
                                    case 'v':
                                        payout[3] = n_oc * mult_oc
                                    case _:
                                        payout[0] = -9999
                    case "owned_domains":
                        self.update_payout_for_role('owned_domains', player_id, payout, split_command)
                    case "owned_citizen_name":
                        # count owned_citizen_name NAME R N
                        # third_word = citizen name, fourth_word = resource, split_command[4] = multiplier
                        want = third_word.strip().lower()
                        player_cn = self.game._player_by_id(player_id)
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
                        player_sn = self.game._player_by_id(player_id)
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
                    case "owned_monster_name":
                        want = third_word.strip().lower()
                        player_om = self.game._player_by_id(player_id)
                        if not player_om or not want:
                            payout[0] = -9999
                        else:
                            n = self.game._owned_monster_name_count(player_om, want)
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
                            (self.game.owned_monster_attributes(player_id) or {}).get(third_word, 0) or 0
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
                    case "type":
                        # count type TYPE R N -- scale by owned monsters of a
                        # given monster_type (e.g. Minion, Beast), counted across
                        # every area the player has slain.
                        type_count = self.game._owned_monster_type_count(player_id, third_word)
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
                if second_word == "wild":
                    return self.game.harvest._execute_wild_cost_exchange_payout(raw, player_id)
                if fourth_word == "wild":
                    return self.game.harvest._execute_wild_gain_exchange_payout(raw, player_id)
                player_x = self.game._player_by_id(player_id)
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
                    and self.game.harvest._want_harvest_optional_exchange_prompt(raw)
                ):
                    self.game.pending_required_choice = {
                        "kind": "harvest_optional_exchange",
                        "player_id": player_id,
                        "command": raw,
                    }
                    self.game.action_required["id"] = player_id
                    self.game.action_required["action"] = "harvest_optional_exchange"
                    return [0, 0, 0, 0]
                print(payout)
                return payout
            case "choose":
                normalized, options = self.game.choose._normalize_choose_command(command)
                options = self.game.choose._filter_unavailable_choose_options(options)
                if not options:
                    payout[0] = -9999
                    return payout
                prompt_options = self.game.choose._expand_choose_options_for_prompt(options)
                if not prompt_options:
                    payout[0] = -9999
                    return payout
                if auto_apply_single_choice and len(prompt_options) == 1:
                    ok = self.game.choose._apply_choose_option(player_id, prompt_options[0])
                    if not ok:
                        payout[0] = -9999
                    return payout
                self.game.action_required["id"] = player_id
                self.game.action_required["action"] = normalized
                self.game.pending_required_choice = {
                    "kind": "special_payout_choose",
                    "player_id": player_id,
                    "command": normalized,
                    "options": prompt_options,
                }
            case _:
                payout[0] = -9999
        print(payout)
        return payout

    def update_payout_for_role(self, role_name, player_id, payout, split_command):
        role_count = 0
        for player in self.game.player_list:
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

