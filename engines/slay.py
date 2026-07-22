"""SlayEngine -- composed sub-engine of Game.

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
)
from game_concurrent import CONCURRENT_HANDLERS, _new_concurrent_action


class SlayEngine:
    def __init__(self, game):
        self.game = game

    def _immediate_slay_monster_options(self, player_id=None):
        """Return option dicts for every accessible monster top across all grids.

        Includes Event cards with is_monster=True (they can occupy any grid slot)
        and regular monsters that the Undead Samurai Lord event scatters onto
        citizen/domain stacks. Event cards use event_id; monsters use monster_id.
        """
        surcharge = self.game.events.dark_lord_surcharge()
        options = []
        all_stacks = (
            list(self.game.monster_grid)
            + list(self.game.citizen_grid)
            + list(self.game.domain_grid)
        )
        for stack in all_stacks:
            if not stack:
                continue
            top = stack[-1]
            if not getattr(top, "is_accessible", False):
                continue
            cost_deltas = {"g": 0, "s": 0, "m": 0}
            if player_id is not None and getattr(top, "has_special_cost", False):
                cost_deltas = self.game._monster_special_cost_deltas(
                    player_id, getattr(top, "special_cost", None)
                )
            eid = getattr(top, "event_id", None)
            if eid is not None:
                # Event occupying a monster slot — only include if it acts as a monster.
                if not getattr(top, "is_monster", False):
                    continue
                options.append({
                    "event_id": int(eid),
                    "name": getattr(top, "name", "?"),
                    "area": "",
                    "gold_cost": (
                        int(getattr(top, "extra_gold_cost", 0) or 0)
                        + int(cost_deltas.get("g", 0) or 0)
                    ),
                    "strength_cost": (
                        int(getattr(top, "strength_cost", 0) or 0)
                        + int(getattr(top, "extra_strength_cost", 0) or 0)
                        + int(cost_deltas.get("s", 0) or 0)
                    ),
                    "magic_cost": (
                        int(getattr(top, "magic_cost", 0) or 0)
                        + int(getattr(top, "extra_magic_cost", 0) or 0)
                        + int(cost_deltas.get("m", 0) or 0)
                        + surcharge
                    ),
                    # Printed (face-value) costs, used to cap Thunder Axe's waiver.
                    "face_strength_cost": int(getattr(top, "strength_cost", 0) or 0),
                    "face_magic_cost": int(getattr(top, "magic_cost", 0) or 0),
                })
                continue
            mid = int(getattr(top, "monster_id", -1))
            if mid < 0:
                continue
            options.append({
                "monster_id": mid,
                "name": getattr(top, "name", "?"),
                "area": getattr(top, "area", ""),
                "gold_cost": (
                    int(getattr(top, "extra_gold_cost", 0) or 0)
                    + int(cost_deltas.get("g", 0) or 0)
                ),
                "strength_cost": (
                    int(getattr(top, "strength_cost", 0) or 0)
                    + int(getattr(top, "extra_strength_cost", 0) or 0)
                    + int(cost_deltas.get("s", 0) or 0)
                ),
                "magic_cost": (
                    int(getattr(top, "magic_cost", 0) or 0)
                    + int(getattr(top, "extra_magic_cost", 0) or 0)
                    + int(cost_deltas.get("m", 0) or 0)
                    + surcharge
                ),
                # Printed (face-value) costs, used to cap Thunder Axe's waiver.
                "face_strength_cost": int(getattr(top, "strength_cost", 0) or 0),
                "face_magic_cost": int(getattr(top, "magic_cost", 0) or 0),
            })
        return options

    def _open_immediate_slay_prompt(self, player_id, source_label, resume_kind="domain_activation"):
        """Open the pick_monster stage of the may-slay prompt.

        If no monster is accessible the prompt is skipped (and the appropriate
        resume kind fires immediately) so the activating player isn't stuck
        on a no-op blocker.
        """
        source_label = (source_label or "Effect").strip() or "Effect"
        options = self._immediate_slay_monster_options(player_id)
        if not options:
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} could not use \"{source_label}\" "
                f"(no accessible monsters to slay)."
            )
            self._resume_after_immediate_slay(resume_kind)
            return
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "choose_monster_slay"
        self.game.pending_required_choice = {
            "kind": "immediate_slay",
            "stage": "pick_monster",
            "player_id": player_id,
            "source_label": source_label,
            "resume_kind": resume_kind,
            "options": options,
            "allow_skip": True,
        }
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} may slay a monster (\"{source_label}\")."
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
            "face_strength_cost": int(chosen.get("face_strength_cost", 0) or 0),
            "face_magic_cost": int(chosen.get("face_magic_cost", 0) or 0),
            "options": list(prc.get("options") or []),
        }
        # Carry the right id depending on whether this is a regular monster or an Event.
        if chosen.get("event_id") is not None:
            stage["event_id"] = int(chosen["event_id"])
        else:
            stage["monster_id"] = int(chosen.get("monster_id", -1))
        self.game.pending_required_choice = stage
        self.game.action_required["id"] = player_id
        self.game.action_required["action"] = "slay_monster_payment"

    def _resume_after_immediate_slay(self, resume_kind):
        """Continue the engine after the may-slay prompt resolves (slay or pass)."""
        if resume_kind == "harvest_pending_slay":
            self.game.harvest._drain_pending_harvest_slays()
            return
        # Default: domain activation follow-up (existing behaviour).
        self.game.domain_effects._resume_after_domain_activation_follow_up()

    def _execute_slay_payout(self, player_id):
        """Bare-verb `slay` payout. Either prompts now (action phase) or queues for harvest end."""
        if getattr(self.game, "phase", None) == "harvest":
            label = getattr(self.game, "_immediate_slay_source_label", None) or "Effect"
            self.game.pending_harvest_slays.append({
                "player_id": player_id,
                "source_label": label,
            })
            return [0, 0, 0, 0]
        label = getattr(self.game, "_immediate_slay_source_label", None) or "Effect"
        self._open_immediate_slay_prompt(player_id, label, resume_kind="domain_activation")
        return [0, 0, 0, 0]

