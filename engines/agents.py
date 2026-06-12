"""AgentsEngine -- composed sub-engine of Game.

Face-up Agents are engaged during the Action Phase for one action. Each
engagement resolves an instantaneous activation effect (same grammar as domain
activations), then returns the used Agent to the bottom of the deck and refills
the slot from the top.
"""
from card_filters import is_unimplemented_agent
from game_helpers import _parse_domain_effect_kv, _parse_resource_kv


class AgentsEngine:
    def __init__(self, game):
        self.game = game

    def _agent_is_engageable(self, agent):
        if not agent:
            return False
        row = {"activation_effect": getattr(agent, "activation_effect", None)}
        return not is_unimplemented_agent(row)

    def _player_can_afford_agent(self, player, agent):
        effect = (getattr(agent, "activation_effect", None) or "").strip()
        if not effect:
            return False
        low = effect.lower()
        if not low.startswith("manipulate_resources"):
            return True
        kv = _parse_domain_effect_kv(effect)
        if (kv.get("mode") or "").strip().lower() != "self_convert":
            return True
        pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
        if not pay_k or pay_n <= 0:
            return False
        return self.game.choose._player_can_afford_self_convert_resources(player, pay_k, pay_n)

    def _complete_agent_recycle(self, slot_index):
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

    def _finish_agent_engage_and_resume(self):
        pending = getattr(self.game, "pending_agent_engage", None)
        if pending:
            self._complete_agent_recycle(pending.get("slot_index"))
            self.game.pending_agent_engage = None
        self.game.pending_required_choice = None
        if getattr(self.game, "phase", None) == "action" and int(getattr(self.game, "actions_remaining", 0) or 0) > 0:
            self.game.action_required["id"] = self.game.lifecycle.current_player_id()
            self.game.action_required["action"] = "standard_action"
            return
        self.game.action_required["id"] = self.game.game_id
        self.game.action_required["action"] = ""
        if getattr(self.game, "phase", None) == "action" and int(getattr(self.game, "actions_remaining", 0) or 0) == 0:
            if self.game.domain_effects._start_action_end_domain_sequence(self.game.lifecycle.current_player_id()):
                return

    def _resume_after_agent_engage_follow_up(self):
        self._finish_agent_engage_and_resume()

    def _apply_agent_activation_effect(self, player, agent):
        effect = (getattr(agent, "activation_effect", None) or "").strip()
        if not effect:
            return
        low = effect.lower()
        agent_name = getattr(agent, "name", "Agent")
        if low.startswith("manipulate_resources"):
            kv = _parse_domain_effect_kv(effect)
            mode = (kv.get("mode") or "").strip().lower()
            if mode == "self_convert":
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
                player.gold_score = int(player.gold_score) + payout[0]
                player.strength_score = int(player.strength_score) + payout[1]
                player.magic_score = int(player.magic_score) + payout[2]
                player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
                self.game.harvest._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
                after = self.game._player_scores_line(player)
                if before != after:
                    self.game._log_game_event(
                        f"{self.game._player_label(player.player_id)} engaged agent \"{agent_name}\"; "
                        f"scores {before} -> {after}"
                    )
                return
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
            if isinstance(payout, list) and len(payout) >= 4 and payout[0] != -9999:
                player.gold_score = int(player.gold_score) + payout[0]
                player.strength_score = int(player.strength_score) + payout[1]
                player.magic_score = int(player.magic_score) + payout[2]
                player.victory_score = int(getattr(player, "victory_score", 0)) + payout[3]
                self.game.harvest._bump_harvest_delta(player, payout[0], payout[1], payout[2], payout[3])
            self.game._log_game_event(
                f"{self.game._player_label(player.player_id)} triggered activation effect on "
                f"\"{agent_name}\" and is choosing options."
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

        agent_name = getattr(agent, "name", "Agent")
        self.game.pending_agent_engage = {"slot_index": idx, "player_id": player_id}
        _prior_action = (self.game.action_required or {}).get("action", "")
        _prior_concurrent = getattr(self.game, "concurrent_action", None)

        self._apply_agent_activation_effect(player, agent)

        _new_action = (self.game.action_required or {}).get("action", "")
        _new_concurrent = getattr(self.game, "concurrent_action", None)
        if (_new_action and _new_action != _prior_action) or (_new_concurrent is not _prior_concurrent):
            return

        self.game._log_game_event(
            f"{self.game._player_label(player_id)} engaged agent \"{agent_name}\"."
        )
        self._resume_after_agent_engage_follow_up()
