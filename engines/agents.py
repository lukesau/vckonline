"""AgentsEngine -- composed sub-engine of Game.

Face-up Agents are engaged during the Action Phase for one action. Each
engagement returns the used Agent to the bottom of the deck and refills the slot
from the top (done immediately, since the slot is independent of effect
resolution), then resolves the Agent's instantaneous activation effect (same
grammar as domain activations).
"""
import re

from card_filters import is_unimplemented_agent
from game_helpers import _parse_domain_effect_kv, _parse_resource_kv

# A leading bare cost leg, e.g. `g -3` (pay 3 Gold to the bank with no resource
# gain). Used by agents like the Assassin whose only "gain" is a board effect.
_BARE_COST_RE = re.compile(r"^([gsm])\s+-(\d+)$")
_RESOURCE_SCORE_ATTR = {"g": "gold_score", "s": "strength_score", "m": "magic_score"}


class AgentsEngine:
    def __init__(self, game):
        self.game = game

    def _agent_is_engageable(self, agent):
        if not agent:
            return False
        row = {"activation_effect": getattr(agent, "activation_effect", None)}
        return not is_unimplemented_agent(row)

    def _agent_cost(self, agent):
        """Return (resource_kind, amount) the player must pay to engage, or
        (None, 0) for a free effect. Handles both a leading
        `manipulate_resources self_convert pay=` cost and a leading bare
        negative resource leg (`g -3`)."""
        effect = (getattr(agent, "activation_effect", None) or "").strip()
        if not effect:
            return None, 0
        first = effect.split(" + ", 1)[0].strip()
        low = first.lower()
        if low.startswith("manipulate_resources"):
            kv = _parse_domain_effect_kv(first)
            if (kv.get("mode") or "").strip().lower() == "self_convert":
                pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
                if pay_k in _RESOURCE_SCORE_ATTR and pay_n > 0:
                    return pay_k, pay_n
            return None, 0
        m = _BARE_COST_RE.match(low)
        if m:
            return m.group(1), int(m.group(2))
        return None, 0

    def _player_can_afford_agent(self, player, agent):
        """Affordability gate: the player must be able to pay the effect's cost."""
        effect = (getattr(agent, "activation_effect", None) or "").strip()
        if not effect:
            return False
        kind, amount = self._agent_cost(agent)
        if not kind or amount <= 0:
            return True
        return int(getattr(player, _RESOURCE_SCORE_ATTR[kind], 0) or 0) >= amount

    def _agent_has_valid_target(self, player_id, agent):
        """For agents whose whole effect is a board interaction (e.g. the
        Assassin's opponent-citizen flip), refuse to engage when no legal target
        exists so the player never pays a cost for nothing. Effects without such
        a hard target requirement always return True."""
        effect = (getattr(agent, "activation_effect", None) or "").lower()
        if "flip_opponent_citizen" in effect or "flip_citizen targeted" in effect:
            return self._opponent_has_unflipped(player_id, "owned_citizens")
        if "flip_opponent_domain" in effect or "flip_domain targeted" in effect:
            return self._opponent_has_unflipped(player_id, "owned_domains")
        if "take_owned monster" in effect:
            return self._opponent_has_takeable(player_id, "owned_monsters")
        if "take_owned citizen" in effect:
            return self._opponent_has_takeable(player_id, "owned_citizens")
        if effect.startswith("steal"):
            return self._has_steal_target(player_id)
        if "banish_owned citizen" in effect:
            return self._player_has_owned(player_id, "owned_citizens")
        if "<citizens" in effect or "banish_center citizen" in effect:
            return self._center_has_accessible("citizen")
        return True

    def _player_has_owned(self, player_id, attr):
        player = self.game._player_by_id(player_id)
        return bool(player and list(getattr(player, attr, []) or []))

    def _center_has_accessible(self, kind):
        if kind == "citizen":
            stacks = list(getattr(self.game, "citizen_grid", []) or [])
            id_attr = "citizen_id"
        elif kind == "monster":
            stacks = list(getattr(self.game, "monster_grid", []) or [])
            id_attr = "monster_id"
        elif kind == "domain":
            stacks = list(getattr(self.game, "domain_grid", []) or [])
            id_attr = "domain_id"
        else:
            return False
        for stack in stacks:
            if not stack:
                continue
            top = stack[-1]
            if getattr(top, id_attr, None) is None:
                continue
            if not getattr(top, "is_accessible", False):
                continue
            return True
        return False

    def _has_steal_target(self, player_id):
        """A legal steal victim: an opponent in play (not resting) who is not
        protected by `immunity.take` (Castle of the Seven Suns)."""
        for p in self.game.player_list:
            if p.player_id == player_id:
                continue
            if not self.game._player_is_negative_effect_target(p):
                continue
            if self.game._player_has_take_immunity(p):
                continue
            return True
        return False

    def _opponent_has_unflipped(self, player_id, attr):
        for p in self.game.player_list:
            if p.player_id == player_id:
                continue
            if not self.game._player_is_negative_effect_target(p):
                continue
            if any(not getattr(c, "is_flipped", False)
                   for c in (getattr(p, attr, []) or [])):
                return True
        return False

    def _opponent_has_takeable(self, player_id, attr):
        """An eligible take target: an opponent in play (not resting), not
        protected by `immunity.take` (Castle of the Seven Suns), who owns at
        least one card of the requested kind."""
        for p in self.game.player_list:
            if p.player_id == player_id:
                continue
            if not self.game._player_is_negative_effect_target(p):
                continue
            if self.game._player_has_take_immunity(p):
                continue
            if list(getattr(p, attr, []) or []):
                return True
        return False

    def _recycle_agent_slot(self, slot_index):
        """Move the used Agent to the bottom of the deck and refill the slot
        from the top. Leaves the slot empty only if the deck is exhausted."""
        idx = int(slot_index)
        slots = self.game.agents_slots
        if idx < 0 or idx >= len(slots):
            return
        used = slots[idx]
        if not used:
            return
        deck = self.game.agents_deck
        deck.insert(0, used)
        if deck:
            new_top = deck.pop()
            new_top.toggle_visibility(True)
            new_top.toggle_accessibility(True)
            slots[idx] = new_top
        else:
            slots[idx] = None

    def _apply_payout_vector(self, player, payout):
        player.gold_score = int(player.gold_score) + payout[0]
        player.strength_score = int(player.strength_score) + payout[1]
        player.magic_score = int(player.magic_score) + payout[2]
        player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
        self.game.harvest._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])

    def _apply_agent_activation_effect(self, player, agent):
        effect = (getattr(agent, "activation_effect", None) or "").strip()
        if not effect:
            return
        low = effect.lower()
        agent_name = getattr(agent, "name", "Agent")
        is_compound = self.game.payouts._has_top_level_plus(effect)

        # Pure (non-compound) self_convert trades resolve through the same
        # affordable-auto-apply / optional-prompt path as domain activations.
        if not is_compound and low.startswith("manipulate_resources"):
            kv = _parse_domain_effect_kv(effect)
            if (kv.get("mode") or "").strip().lower() == "self_convert":
                before = self.game._player_scores_line(player)
                _prior_action = (self.game.action_required or {}).get("action", "")
                payout = self.game.domain_effects._prompt_or_apply_self_convert(
                    effect, player, domain=None, context="agent_engage"
                )
                _new_action = (self.game.action_required or {}).get("action", "")
                if _new_action and _new_action != _prior_action:
                    self.game._log_game_event(
                        f"{self.game._player_label(player.player_id)} triggered activation effect on "
                        f"\"{agent_name}\" and is choosing options."
                    )
                    return
                if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
                    return
                self._apply_payout_vector(player, payout)
                after = self.game._player_scores_line(player)
                if before != after:
                    self.game._log_game_event(
                        f"{self.game._player_label(player.player_id)} engaged agent \"{agent_name}\"; "
                        f"scores {before} -> {after}"
                    )
                return

        # Everything else (including compound `pay + choose <citizens ...>`)
        # routes through the generic payout interpreter.
        before = self.game._player_scores_line(player)
        _prior_action = (self.game.action_required or {}).get("action", "")
        _prior_concurrent = getattr(self.game, "concurrent_action", None)
        self.game._immediate_slay_source_label = agent_name
        try:
            payout = self.game.payouts.execute_special_payout(
                effect, player.player_id, auto_apply_single_choice=False
            )
        finally:
            self.game._immediate_slay_source_label = None
        _new_action = (self.game.action_required or {}).get("action", "")
        _new_concurrent = getattr(self.game, "concurrent_action", None)
        if (_new_action and _new_action != _prior_action) or (_new_concurrent is not _prior_concurrent):
            # A leg opened a blocking prompt (e.g. the `choose <citizens>` leg).
            # Apply any resource legs that resolved before it so they are not lost.
            if isinstance(payout, list) and len(payout) >= 4 and payout[0] != -9999:
                self._apply_payout_vector(player, payout)
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} triggered activation effect on "
                f"\"{agent_name}\" and is choosing options."
            )
            return
        if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
            return
        self._apply_payout_vector(player, payout)
        after = self.game._player_scores_line(player)
        if before != after:
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} engaged agent \"{agent_name}\"; "
                f"scores {before} -> {after}"
            )

    def engage_agent(self, player_id, slot_index):
        if not self.game.agents_enabled():
            raise ValueError("Agents are not in play for this game.")
        idx = int(slot_index)
        slots = self.game.agents_slots
        if idx < 0 or idx >= len(slots):
            raise ValueError("Invalid agent slot.")
        agent = slots[idx]
        if not agent:
            raise ValueError("No agent in that slot.")
        if not self._agent_is_engageable(agent):
            raise ValueError("That agent is not implemented yet.")
        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        if not self._player_can_afford_agent(player, agent):
            raise ValueError("Insufficient resources to engage that agent.")
        if not self._agent_has_valid_target(player_id, agent):
            raise ValueError("No valid target to engage that agent.")

        agent_name = getattr(agent, "name", "Agent")
        # Recycle now: the used Agent goes to the bottom of the deck and the slot
        # refills from the top. The `agent` reference still drives the effect
        # below, so resolution (including any prompt it opens) is unaffected.
        self._recycle_agent_slot(idx)

        _prior_action = (self.game.action_required or {}).get("action", "")
        _prior_concurrent = getattr(self.game, "concurrent_action", None)

        self.game._log_game_event(
            f"{self.game._player_label(player_id)} engaged agent \"{agent_name}\"."
        )
        self._apply_agent_activation_effect(player, agent)

        _new_action = (self.game.action_required or {}).get("action", "")
        _new_concurrent = getattr(self.game, "concurrent_action", None)
        if (_new_action != _prior_action) or (_new_concurrent is not _prior_concurrent):
            # The effect either opened a blocking prompt (its resolution restores
            # the action phase) or already self-resumed (e.g. a bare `slay` leg
            # with no legal target clears the prompt and re-arms standard_action /
            # ends the turn). Either way, don't resume again — that could rebuild
            # and re-apply the end-of-action domain queue.
            return
        self.game.domain_effects._resume_after_domain_activation_follow_up()
