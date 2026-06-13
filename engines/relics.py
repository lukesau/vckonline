"""RelicsEngine -- composed sub-engine of Game.

Each player keeps one face-up Relic (held in `player.owned_relics`). A relic is
used at most once per turn during the owner's Action Phase (see
`Game.use_relic` / `Game.relic_available_for`). The relic's power lives in the
`passive_effect` string and is executed here, reusing the same bare-leg payout
grammar as agents.

This first pass covers the click-to-use relics whose effects resolve through
the existing payout interpreter: pure resource trades plus optional follow-up
prompts like `slay`, `recruit`, and `build_domain`. It also handles the
"both-wild" exchange (Treant Chest: pay N of any one resource, gain M of any
one resource), which has no payout-grammar form and runs as its own two-stage
prompt.
"""
import re

from card_filters import is_unimplemented_relic

# A leading bare cost leg, e.g. `m -4` (pay 4 Magic). Relic costs are always the
# first leg of the effect string.
_BARE_COST_RE = re.compile(r"^([gsm])\s+-(\d+)$")
# A both-wild exchange, e.g. `exchange wild 3 wild 5`: pay N of any one of
# gold/strength/magic, then gain M of any one of gold/strength/magic.
_WILD_EXCHANGE_RE = re.compile(r"^exchange\s+wild\s+(\d+)\s+wild\s+(\d+)$")
_RESOURCE_SCORE_ATTR = {"g": "gold_score", "s": "strength_score", "m": "magic_score"}

# Passive "buy a Domain" relics gain 2 VP per build (Violet Ring).
_BUILD_DOMAIN_VP_RE = re.compile(r"^action\.build_domain\s+v\s+(\d+)$")
# Passive "ignore 1 Domain requirement" relic marker prefix (Evermap).
_IGNORE_REQUIREMENT_PREFIX = "action.build_domain ignore_requirement"
# Evermap alternative: gain N Magic on a Domain build when the ignore is unused
# (`action.build_domain ignore_requirement 1 or m 1`).
_BUILD_DOMAIN_OR_MAGIC_RE = re.compile(r"\bor\s+m\s+(\d+)")
# Passive slay-cost reducer (Thunder Axe): `action.slay_discount magic=1 strength=1`.
_SLAY_DISCOUNT_PREFIX = "action.slay_discount"
_SLAY_DISCOUNT_MAGIC_RE = re.compile(r"magic=(\d+)")
_SLAY_DISCOUNT_STRENGTH_RE = re.compile(r"strength=(\d+)")


class RelicsEngine:
    def __init__(self, game):
        self.game = game

    def _relic_effect(self, relic):
        return (getattr(relic, "passive_effect", None) or "").strip()

    def _relic_is_implemented(self, relic):
        return not is_unimplemented_relic(
            {"passive_effect": getattr(relic, "passive_effect", None)}
        )

    def _owned_relic(self, player):
        relics = list(getattr(player, "owned_relics", []) or []) if player else []
        return relics[0] if relics else None

    def _relic_is_passive(self, relic):
        """Passive/triggered relics (Evermap, Violet Ring) fire automatically on a
        game event rather than being clicked. Their effect string uses the
        `action.*` trigger-marker grammar, so they are never click-usable."""
        return self._relic_effect(relic).lower().startswith("action.")

    def player_can_ignore_one_build_requirement(self, player):
        """Evermap: when buying a Domain, the player may ignore exactly one
        missing role-icon requirement."""
        relic = self._owned_relic(player)
        if not relic:
            return False
        return self._relic_effect(relic).lower().startswith(_IGNORE_REQUIREMENT_PREFIX)

    def relic_build_domain_vp_bonus(self, player):
        """Violet Ring: VP gained whenever the player buys a Domain (0 if none)."""
        relic = self._owned_relic(player)
        if not relic:
            return 0
        m = _BUILD_DOMAIN_VP_RE.match(self._relic_effect(relic).lower())
        return int(m.group(1)) if m else 0

    def relic_build_domain_magic_bonus(self, player):
        """Evermap: Magic gained on a Domain build when the role-ignore is not
        used (the `or m N` alternative). 0 if the player owns no such relic."""
        relic = self._owned_relic(player)
        if not relic:
            return 0
        eff = self._relic_effect(relic).lower()
        if not eff.startswith(_IGNORE_REQUIREMENT_PREFIX):
            return 0
        m = _BUILD_DOMAIN_OR_MAGIC_RE.search(eff)
        return int(m.group(1)) if m else 0

    def relic_slay_discount(self, player):
        """Thunder Axe: when slaying a Monster, the owner may ignore up to N
        face-value Magic OR M face-value Strength of the cost. Returns
        {"magic": N, "strength": M}, or None if the player owns no such relic.

        The caps apply only to the monster's printed (face-value) costs — never
        to event surcharges or to magic spent as wild Strength."""
        relic = self._owned_relic(player)
        if not relic:
            return None
        eff = self._relic_effect(relic).lower()
        if not eff.startswith(_SLAY_DISCOUNT_PREFIX):
            return None
        m = _SLAY_DISCOUNT_MAGIC_RE.search(eff)
        s = _SLAY_DISCOUNT_STRENGTH_RE.search(eff)
        return {
            "magic": int(m.group(1)) if m else 0,
            "strength": int(s.group(1)) if s else 0,
        }

    def _relic_wild_exchange(self, relic):
        """Return (cost_amount, gain_amount) for a both-wild exchange relic, or
        None if the relic's effect is not a wild exchange."""
        m = _WILD_EXCHANGE_RE.match(self._relic_effect(relic).lower())
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    def _wild_exchange_cost_options(self, player, cost_amt):
        """Resources the player can afford to pay `cost_amt` of (one button each)."""
        return [
            {"resource": r, "amount": cost_amt}
            for r in ("g", "s", "m")
            if int(getattr(player, _RESOURCE_SCORE_ATTR[r], 0) or 0) >= cost_amt
        ]

    def _relic_cost(self, relic):
        """Return (resource_kind, amount) the player must pay to use the relic,
        or (None, 0) for a free effect. The cost is the leading bare negative
        resource leg (e.g. `m -4`)."""
        effect = self._relic_effect(relic)
        if not effect:
            return None, 0
        first = effect.split(" + ", 1)[0].strip().lower()
        m = _BARE_COST_RE.match(first)
        if m:
            return m.group(1), int(m.group(2))
        return None, 0

    def _player_can_afford_relic(self, player, relic):
        we = self._relic_wild_exchange(relic)
        if we:
            cost_amt, _gain_amt = we
            return bool(self._wild_exchange_cost_options(player, cost_amt))
        if not self._relic_has_required_target(player, relic):
            return False
        kind, amount = self._relic_cost(relic)
        if not kind or amount <= 0:
            return True
        return int(getattr(player, _RESOURCE_SCORE_ATTR[kind], 0) or 0) >= amount

    def _relic_has_required_target(self, player, relic):
        """Targeted banish relics should glow only when their required target exists."""
        effect = self._relic_effect(relic).lower()
        if effect.startswith("banish_owned citizen"):
            return bool(getattr(player, "owned_citizens", []) or [])
        if effect.startswith("banish_owned monster"):
            return bool(getattr(player, "owned_monsters", []) or [])
        if effect.startswith("banish_center monster"):
            type_filter = None
            first = effect.split(" + ", 1)[0]
            for token in first.split()[2:]:
                if token.startswith("type="):
                    type_filter = token.split("=", 1)[1].strip()
            for stack in list(getattr(self.game, "monster_grid", []) or []):
                if not stack:
                    continue
                top = stack[-1]
                if getattr(top, "monster_id", None) is None:
                    continue
                if not getattr(top, "is_accessible", False):
                    continue
                if type_filter:
                    monster_type = (getattr(top, "monster_type", "") or "").strip().lower()
                    if monster_type != type_filter:
                        continue
                return True
            return False
        return True

    def _apply_relic_payout_vector(self, player, payout):
        player.gold_score = int(player.gold_score) + payout[0]
        player.strength_score = int(player.strength_score) + payout[1]
        player.magic_score = int(player.magic_score) + payout[2]
        player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
        self.game.harvest._bump_harvest_delta(
            player, payout[0], payout[1], payout[2], payout[3]
        )

    def _apply_relic_effect(self, player, relic):
        """Resolve an implemented relic's `passive_effect`.

        The generic payout interpreter returns a net [g, s, m, v] vector for
        immediate resource legs. Compound effects may also open a blocking
        prompt (e.g. `s 1 + slay`); in that case apply the resource legs that
        resolved before the prompt and leave the prompt open. Both-wild
        exchanges (Treant Chest) open their own dedicated two-stage prompt.
        """
        effect = self._relic_effect(relic)
        if not effect:
            return
        we = self._relic_wild_exchange(relic)
        if we:
            self._open_wild_exchange_prompt(player, relic, we[0], we[1])
            return
        relic_name = getattr(relic, "name", "Relic")
        before = self.game._player_scores_line(player)
        _prior_action = (self.game.action_required or {}).get("action", "")
        _prior_concurrent = getattr(self.game, "concurrent_action", None)
        self.game._immediate_slay_source_label = relic_name
        try:
            payout = self.game.payouts.execute_special_payout(
                effect, player.player_id, auto_apply_single_choice=False
            )
        finally:
            self.game._immediate_slay_source_label = None
        _new_action = (self.game.action_required or {}).get("action", "")
        _new_concurrent = getattr(self.game, "concurrent_action", None)
        if (_new_action and _new_action != _prior_action) or (_new_concurrent is not _prior_concurrent):
            if isinstance(payout, list) and len(payout) >= 4 and payout[0] != -9999:
                self._apply_relic_payout_vector(player, payout)
            after_prompt = self.game._player_scores_line(player)
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} used relic \"{relic_name}\" "
                f"and is choosing options."
            )
            if before != after_prompt:
                self.game._log_game_event(
                    f"{self.game._player_label(player.player_id)} used relic \"{relic_name}\"; "
                    f"scores {before} -> {after_prompt}"
                )
            return
        if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
            return
        if isinstance(payout, list) and len(payout) >= 4:
            self._apply_relic_payout_vector(player, payout)
        after = self.game._player_scores_line(player)
        if before != after:
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} used relic \"{relic_name}\"; "
                f"scores {before} -> {after}"
            )

    def _open_wild_exchange_prompt(self, player, relic, cost_amt, gain_amt):
        """Open stage 1 (choose what to pay) of a both-wild exchange. Availability
        is gated upstream, so there is always at least one affordable resource."""
        relic_name = getattr(relic, "name", "Relic")
        options = self._wild_exchange_cost_options(player, cost_amt)
        if not options:
            return
        self.game.pending_required_choice = {
            "kind": "relic_wild_exchange",
            "stage": "pay",
            "player_id": player.player_id,
            "relic_name": relic_name,
            "cost_options": options,
            "cost_amount": int(cost_amt),
            "gain_amount": int(gain_amt),
        }
        self.game.action_required["id"] = player.player_id
        self.game.action_required["action"] = "relic_wild_exchange"
        self.game._log_game_event(
            f"{self.game._player_label(player.player_id)} used relic \"{relic_name}\" "
            f"and is choosing a resource to pay."
        )

    def resolve_wild_exchange_action(self, player_id, action):
        """Handle `relic_pay <r>` (stage 1) and `relic_gain <r>` (stage 2) for the
        both-wild exchange prompt. Stage 1 deducts the chosen cost and advances to
        stage 2; stage 2 awards the chosen gain and resumes the action phase."""
        prc = getattr(self.game, "pending_required_choice", None) or {}
        if prc.get("kind") != "relic_wild_exchange" or prc.get("player_id") != player_id:
            return
        player = self.game._player_by_id(player_id)
        if not player:
            return
        act = (action or "").strip().lower()
        stage = prc.get("stage")
        relic_name = prc.get("relic_name", "Relic")

        if stage == "pay":
            if not act.startswith("relic_pay "):
                return
            parts = act.split()
            res = parts[1] if len(parts) > 1 else ""
            valid = {o["resource"] for o in (prc.get("cost_options") or [])}
            if res not in valid:
                return
            cost_amt = int(prc.get("cost_amount", 0))
            if int(getattr(player, _RESOURCE_SCORE_ATTR[res], 0) or 0) < cost_amt:
                return
            before = self.game._player_scores_line(player)
            setattr(player, _RESOURCE_SCORE_ATTR[res],
                    int(getattr(player, _RESOURCE_SCORE_ATTR[res], 0)) - cost_amt)
            self.game.harvest._bump_harvest_delta(
                player,
                -cost_amt if res == "g" else 0,
                -cost_amt if res == "s" else 0,
                -cost_amt if res == "m" else 0,
                0,
            )
            after = self.game._player_scores_line(player)
            self.game.pending_required_choice = {
                "kind": "relic_wild_exchange",
                "stage": "gain",
                "player_id": player_id,
                "relic_name": relic_name,
                "gain_amount": int(prc.get("gain_amount", 0)),
                "paid_resource": res,
                "paid_amount": cost_amt,
            }
            self.game.action_required["id"] = player_id
            self.game.action_required["action"] = "relic_wild_exchange"
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} paid {cost_amt} "
                f"{_RESOURCE_SCORE_ATTR[res].split('_')[0]} for relic \"{relic_name}\"; "
                f"scores {before} -> {after}"
            )
            return

        if stage == "gain":
            if not act.startswith("relic_gain "):
                return
            parts = act.split()
            res = parts[1] if len(parts) > 1 else ""
            if res not in ("g", "s", "m"):
                return
            gain_amt = int(prc.get("gain_amount", 0))
            before = self.game._player_scores_line(player)
            setattr(player, _RESOURCE_SCORE_ATTR[res],
                    int(getattr(player, _RESOURCE_SCORE_ATTR[res], 0)) + gain_amt)
            self.game.harvest._bump_harvest_delta(
                player,
                gain_amt if res == "g" else 0,
                gain_amt if res == "s" else 0,
                gain_amt if res == "m" else 0,
                0,
            )
            after = self.game._player_scores_line(player)
            self.game.pending_required_choice = None
            self.game.action_required["action"] = ""
            self.game.action_required["id"] = self.game.game_id
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} gained {gain_amt} "
                f"{_RESOURCE_SCORE_ATTR[res].split('_')[0]} from relic \"{relic_name}\"; "
                f"scores {before} -> {after}"
            )
            self.game.domain_effects._resume_after_domain_activation_follow_up()
            return
