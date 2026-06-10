"""PlayerActionsEngine -- composed sub-engine of Game.

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


class PlayerActionsEngine:
    def __init__(self, game):
        self.game = game

    def wait_for_input(self, command, player_id):
        print("waiting for input")
        while self.game.action_required["id"] != self.game.game_id:
            time.sleep(1)  # wait for 1 second before checking again
        print("input received")
        choice = []
        payout = [0, 0, 0, 0]
        match self.game.action_required['action']:
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
        for player in self.game.player_list:
            if player.player_id == player_id:
                player.gold_score = player.gold_score + payout[0]
                player.strength_score = player.strength_score + payout[1]
                player.magic_score = player.magic_score + payout[2]
                player.victory_score = player.victory_score + payout[3]
                # If this payout is resolving a harvest-time choice, track it on the same harvest delta.
                if not hasattr(player, "harvest_delta") or not isinstance(player.harvest_delta, dict):
                    player.harvest_delta = {"gold": 0, "strength": 0, "magic": 0, "victory": 0, "map": 0}
                player.harvest_delta["gold"] = int(player.harvest_delta.get("gold", 0)) + int(payout[0])
                player.harvest_delta["strength"] = int(player.harvest_delta.get("strength", 0)) + int(payout[1])
                player.harvest_delta["magic"] = int(player.harvest_delta.get("magic", 0)) + int(payout[2])
                player.harvest_delta["victory"] = int(player.harvest_delta.get("victory", 0)) + int(payout[3])
        for player in self.game.player_list:
            print(f"Player {player.name}: {player.gold_score} G, {player.strength_score} S, {player.magic_score} M,"
                  f" {player.victory_score} VP, Monsters: {len(player.owned_monsters)}, "
                  f"Citizens: {len(player.owned_citizens)}, Domains {len(player.owned_domains)}")
        self.game.harvest._maybe_resume_harvest_prompt()

    def act_on_required_action(self, player_id, action):
        if self.game.action_required['id'] == player_id:
            print("correct player responded to action")
            current_required = self.game.action_required.get("action", "")

            # Special: bonus resource choice (imaginary starter on "no payout" harvest)
            if current_required == "bonus_resource_choice":
                choice = (action or "").strip().lower()
                if choice not in ("gold", "strength", "magic"):
                    return
                target = self.game._player_by_id(player_id)
                if not target:
                    return
                before = self.game._player_scores_line(target)
                if choice == "gold":
                    target.gold_score += 1
                    target.harvest_delta["gold"] = int(target.harvest_delta.get("gold", 0)) + 1
                elif choice == "strength":
                    target.strength_score += 1
                    target.harvest_delta["strength"] = int(target.harvest_delta.get("strength", 0)) + 1
                else:
                    target.magic_score += 1
                    target.harvest_delta["magic"] = int(target.harvest_delta.get("magic", 0)) + 1
                after = self.game._player_scores_line(target)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} harvest bonus +1 {choice} (no gold/strength/magic spent); "
                    f"scores {before} -> {after}"
                )

                # Pop current pending player and either fire the next bonus, or clear blocking.
                if self.game.pending_harvest_choices and self.game.pending_harvest_choices[0] == player_id:
                    self.game.pending_harvest_choices.pop(0)
                if self.game.pending_harvest_choices:
                    self.game.harvest._activate_finalize_bonus_for(self.game.pending_harvest_choices[0])
                    return

                self.game.action_required['action'] = ""
                self.game.action_required['id'] = self.game.game_id
                return

            # Event "pay N for an additional action" (e.g. The Wizards of Nae).
            if current_required == "event_gain_action":
                prc_ga = getattr(self.game, "pending_required_choice", None) or {}
                if prc_ga.get("kind") != "event_gain_action" or prc_ga.get("player_id") != player_id:
                    return
                act_ga = (action or "").strip().lower()
                if act_ga in ("accept", "confirm", "pay", "yes"):
                    self.game.events.resolve_gain_action(player_id, True)
                elif act_ga in ("skip", "decline", "no"):
                    self.game.events.resolve_gain_action(player_id, False)
                return

            # Event "choose one of two options" (e.g. Golden Idol). Numeric
            # selections are 1-based ("choose 1", "1"); letters map a->1, b->2.
            if current_required == "event_active_choose":
                act_c = (action or "").strip().lower()
                if act_c in ("option_a", "a"):
                    idx_c = 0
                elif act_c in ("option_b", "b"):
                    idx_c = 1
                else:
                    if act_c.startswith("choose "):
                        act_c = act_c.split(None, 1)[1].strip()
                    try:
                        idx_c = int(act_c) - 1
                    except (TypeError, ValueError):
                        return
                self.game.events.resolve_active_choose(player_id, idx_c)
                return

            # Event "in turn order" sequential resolution (Alms / Night Terror /
            # Worthy Sacrifice). The acting player is always queue[0].
            if current_required == "event_sequence":
                self.game.events.resolve_sequence_response(player_id, action)
                return

            if current_required == "harvest_optional_exchange":
                prc_h = getattr(self.game, "pending_required_choice", None) or {}
                if prc_h.get("kind") != "harvest_optional_exchange" or prc_h.get("player_id") != player_id:
                    return
                act_h = (action or "").strip().lower()
                if act_h not in ("confirm_harvest_exchange", "skip_harvest_exchange"):
                    return
                cmd_h = (prc_h.get("command") or "").strip()
                target_h = self.game._player_by_id(player_id)
                self.game.pending_required_choice = None
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                if not target_h or not cmd_h:
                    self.game.harvest._maybe_resume_harvest_prompt()
                    return
                before_h = self.game._player_scores_line(target_h)
                if act_h == "skip_harvest_exchange":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} skipped optional harvest exchange ({cmd_h}); "
                        f"scores unchanged ({before_h})."
                    )
                    self.game.harvest._maybe_resume_harvest_prompt()
                    return
                payout_h = self.game.payouts.execute_special_payout(
                    cmd_h,
                    player_id,
                    suppress_exchange_optional_prompt=True,
                )
                if isinstance(payout_h, list) and len(payout_h) >= 4 and payout_h[0] != -9999:
                    target_h.gold_score = int(target_h.gold_score) + int(payout_h[0])
                    target_h.strength_score = int(target_h.strength_score) + int(payout_h[1])
                    target_h.magic_score = int(target_h.magic_score) + int(payout_h[2])
                    target_h.victory_score = int(getattr(target_h, "victory_score", 0)) + int(payout_h[3])
                    self.game.harvest._bump_harvest_delta(target_h, payout_h[0], payout_h[1], payout_h[2], payout_h[3])
                    after_h = self.game._player_scores_line(target_h)
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} took harvest exchange ({cmd_h}); scores {before_h} -> {after_h}"
                    )
                self.game.harvest._maybe_resume_harvest_prompt()
                return

            if current_required == "harvest_steal":
                prc_s = getattr(self.game, "pending_required_choice", None) or {}
                if prc_s.get("kind") != "harvest_steal" or prc_s.get("player_id") != player_id:
                    return
                victim_opts_s = list(prc_s.get("victim_options") or [])
                resource_opts_s = list(prc_s.get("resource_options") or [])
                act_s = (action or "").strip().lower()
                stage_s = (prc_s.get("stage") or "victim").strip().lower()
                if stage_s == "victim" and act_s.startswith("steal_victim "):
                    try:
                        idx_s = int(act_s.split()[1]) - 1
                    except (IndexError, ValueError):
                        return
                    if idx_s < 0 or idx_s >= len(victim_opts_s):
                        return
                    victim_opt_s = victim_opts_s[idx_s]
                    if len(resource_opts_s) == 1:
                        res_opt_s = resource_opts_s[0]
                        self.game.pending_required_choice = None
                        self.game.action_required["action"] = ""
                        self.game.action_required["id"] = self.game.game_id
                        self.game.harvest._apply_harvest_steal_choice(
                            player_id,
                            victim_opt_s.get("victim_id"),
                            res_opt_s.get("resource"),
                            res_opt_s.get("amount"),
                        )
                        self.game.harvest._maybe_resume_harvest_prompt()
                        return
                    self.game.pending_required_choice = {
                        "kind": "harvest_steal",
                        "stage": "resource",
                        "player_id": player_id,
                        "victim": victim_opt_s,
                        "resource_options": resource_opts_s,
                    }
                    self.game.action_required["action"] = "harvest_steal"
                    self.game.action_required["id"] = player_id
                    return
                if stage_s == "resource" and act_s.startswith("steal_resource "):
                    try:
                        idx_s = int(act_s.split()[1]) - 1
                    except (IndexError, ValueError):
                        return
                    if idx_s < 0 or idx_s >= len(resource_opts_s):
                        return
                    victim_opt_s = prc_s.get("victim") or {}
                    res_opt_s = resource_opts_s[idx_s]
                    self.game.pending_required_choice = None
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.harvest._apply_harvest_steal_choice(
                        player_id,
                        victim_opt_s.get("victim_id"),
                        res_opt_s.get("resource"),
                        res_opt_s.get("amount"),
                    )
                    self.game.harvest._maybe_resume_harvest_prompt()
                    return
                # Backward compatibility for the old flat "steal N" client action.
                opts_s = list(prc_s.get("options") or [])
                if act_s.startswith("steal "):
                    try:
                        idx_s = int(act_s.split()[1]) - 1
                    except (IndexError, ValueError):
                        return
                    if idx_s < 0 or idx_s >= len(opts_s):
                        return
                    opt_s = opts_s[idx_s]
                    self.game.pending_required_choice = None
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.harvest._apply_harvest_steal_choice(
                        player_id,
                        opt_s.get("victim_id"),
                        opt_s.get("resource"),
                        opt_s.get("amount"),
                    )
                    self.game.harvest._maybe_resume_harvest_prompt()
                    return
                return

            if current_required == "harvest_wild_gain_exchange":
                prc_wg = getattr(self.game, "pending_required_choice", None) or {}
                if prc_wg.get("kind") != "harvest_wild_gain_exchange" or prc_wg.get("player_id") != player_id:
                    return
                act_wg = (action or "").strip().lower()
                # All harvest exchanges (plain and wild) are optional. Treat
                # `skip_harvest_exchange` as a uniform decline that resumes the
                # harvest pipeline (or the domain `action.start` follow-up)
                # without mutating any resources.
                if act_wg == "skip_harvest_exchange":
                    cmd_wg = (prc_wg.get("command") or "").strip()
                    target_wg = self.game._player_by_id(player_id)
                    resume_kind = prc_wg.get("context")
                    self.game.pending_required_choice = None
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    if target_wg:
                        scores_wg = self.game._player_scores_line(target_wg)
                        self.game._log_game_event(
                            f"{self.game._player_label(player_id)} skipped optional harvest exchange "
                            f"({cmd_wg}); scores unchanged ({scores_wg})."
                        )
                    if resume_kind == "action_start":
                        self.game.domain_effects._resume_after_domain_activation_follow_up()
                    else:
                        self.game.harvest._maybe_resume_harvest_prompt()
                    return
                if not act_wg.startswith("wild_gain_resource "):
                    return
                res_wg = act_wg.split()[1] if len(act_wg.split()) > 1 else ""
                if res_wg not in ("g", "s", "m"):
                    return
                self.game.pending_required_choice = None
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.harvest._apply_wild_gain_exchange_choice(player_id, res_wg, prc_wg)
                if prc_wg.get("context") == "action_start":
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                else:
                    self.game.harvest._maybe_resume_harvest_prompt()
                return

            if current_required == "harvest_wild_cost_exchange":
                prc_wc = getattr(self.game, "pending_required_choice", None) or {}
                if prc_wc.get("kind") != "harvest_wild_cost_exchange" or prc_wc.get("player_id") != player_id:
                    return
                act_wc = (action or "").strip().lower()
                if act_wc == "skip_harvest_exchange":
                    cmd_wc = (prc_wc.get("command") or "").strip()
                    target_wc = self.game._player_by_id(player_id)
                    self.game.pending_required_choice = None
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    if target_wc:
                        scores_wc = self.game._player_scores_line(target_wc)
                        self.game._log_game_event(
                            f"{self.game._player_label(player_id)} skipped optional harvest exchange "
                            f"({cmd_wc}); scores unchanged ({scores_wc})."
                        )
                    self.game.harvest._maybe_resume_harvest_prompt()
                    return
                if not act_wc.startswith("wild_cost_resource "):
                    return
                res_wc = act_wc.split()[1] if len(act_wc.split()) > 1 else ""
                valid_wc = {o["resource"] for o in (prc_wc.get("cost_options") or [])}
                if res_wc not in valid_wc:
                    return
                self.game.pending_required_choice = None
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.harvest._apply_wild_cost_exchange_choice(player_id, res_wc, prc_wc)
                self.game.harvest._maybe_resume_harvest_prompt()
                return

            if current_required == "choose_domain_reward":
                prc_dr = getattr(self.game, "pending_required_choice", None) or {}
                if prc_dr.get("kind") != "grant_domain_reward" or prc_dr.get("player_id") != player_id:
                    return
                act_dr = (action or "").strip().lower()
                if not act_dr.startswith("grant_domain "):
                    return
                opts_dr = list(prc_dr.get("options") or [])
                try:
                    sel_dr = int(act_dr.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel_dr < 0 or sel_dr >= len(opts_dr):
                    return
                stack_idx_dr = opts_dr[sel_dr]["stack_idx"]
                self.game.pending_required_choice = None
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.payouts._apply_grant_domain_choice(player_id, stack_idx_dr)
                # If `<domains>` was a leg of a compound payout (e.g. a
                # monster `special_reward = "<domains> + <citizens>"`), drain
                # the next leg now. If that leg opens its own follow-up
                # prompt, leave it standing instead of letting the domain
                # activation resume clobber it.
                self.game.payouts._resume_payout_continuation()
                if (self.game.action_required or {}).get("action", ""):
                    return
                self.game.domain_effects._resume_after_domain_activation_follow_up()
                return

            if current_required == "choose_domain_to_build":
                prc_db = getattr(self.game, "pending_required_choice", None) or {}
                if prc_db.get("kind") != "domain_build_opportunity" or prc_db.get("player_id") != player_id:
                    return
                act_db = (action or "").strip().lower()
                if act_db == "skip":
                    self.game.pending_required_choice = None
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to build a domain (Ararmartin Ridge)."
                    )
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                if not act_db.startswith("build_domain_pick "):
                    return
                opts_db = list(prc_db.get("options") or [])
                try:
                    sel_db = int(act_db.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel_db < 0 or sel_db >= len(opts_db):
                    return
                chosen = opts_db[sel_db]
                domain_id_db = chosen["domain_id"]
                gold_cost_db = int(chosen.get("gold_cost", 0))
                self.game.pending_required_choice = None
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.build_domain(player_id, domain_id_db, gp=gold_cost_db)
                if not (self.game.action_required.get("action") and self.game.action_required.get("id") != self.game.game_id):
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                return

            prc0 = getattr(self.game, "pending_required_choice", None) or {}

            # Immediate "may slay a Monster" prompt — stage 1: pick a monster.
            if prc0.get("kind") == "immediate_slay" and str(current_required).strip() == "choose_monster_slay":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                resume_kind = prc0.get("resume_kind", "domain_activation")
                source_label = prc0.get("source_label", "Effect")
                if act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to slay (\"{source_label}\")."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.slay._resume_after_immediate_slay(resume_kind)
                    return
                if not act.startswith("choose_monster_slay "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    idx = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if idx < 0 or idx >= len(opts):
                    return
                # Stage 2: collect the slay payment.
                self.game.slay._enter_slay_payment_stage(prc0, opts[idx])
                return

            # Immediate "may slay a Monster" prompt — stage 2: collect payment + slay.
            if prc0.get("kind") == "immediate_slay" and str(current_required).strip() == "slay_monster_payment":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                resume_kind = prc0.get("resume_kind", "domain_activation")
                source_label = prc0.get("source_label", "Effect")
                if act == "back":
                    self.game.action_required["action"] = "choose_monster_slay"
                    self.game.action_required["id"] = player_id
                    self.game.pending_required_choice = {
                        "kind": "immediate_slay",
                        "stage": "pick_monster",
                        "player_id": player_id,
                        "source_label": source_label,
                        "resume_kind": resume_kind,
                        "options": list(prc0.get("options") or []),
                        "allow_skip": True,
                    }
                    return
                if act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to slay (\"{source_label}\")."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.slay._resume_after_immediate_slay(resume_kind)
                    return
                if not act.startswith("slay_pay "):
                    return
                parts = act.split()
                if len(parts) < 4:
                    return
                try:
                    gp = int(parts[1])
                    sp = int(parts[2])
                    mp = int(parts[3])
                except (TypeError, ValueError):
                    return
                event_id_opt = prc0.get("event_id")
                monster_id = int(prc0.get("monster_id", -1)) if event_id_opt is None else None
                if event_id_opt is None and monster_id < 0:
                    return
                target = self.game._player_by_id(player_id)
                before_tup = self.game.domain_effects._player_resource_tuple(target) if target else (0, 0, 0, 0)
                # Snapshot prompt state so we can detect whether slay_monster's
                # special_reward opened a follow-up prompt (e.g. Warg's "choose
                # m 3 <citizens where name==Peasant>") that we must NOT clobber.
                _prior_concurrent = getattr(self.game, "concurrent_action", None)
                try:
                    self.slay_monster(player_id, monster_id, sp, mp, gp, event_id=event_id_opt)
                except ValueError as e:
                    # Payment didn't validate; surface in the log so the player
                    # sees why nothing happened, but keep the prompt open so they
                    # can retry with a corrected payment.
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} could not slay "
                        f"\"{prc0.get('monster_name', '?')}\" via \"{source_label}\": {e}"
                    )
                    return
                # When the slay was triggered by a citizen harvest payout (resolved at
                # end of harvest), count the net resource delta toward harvest_delta so
                # the empty-harvest bonus_resource_choice gate sees it correctly.
                if resume_kind == "harvest_pending_slay" and target:
                    after_tup = self.game.domain_effects._player_resource_tuple(target)
                    self.game.harvest._bump_harvest_delta(
                        target,
                        after_tup[0] - before_tup[0],
                        after_tup[1] - before_tup[1],
                        after_tup[2] - before_tup[2],
                        after_tup[3] - before_tup[3],
                    )
                # Detect a follow-up prompt opened by the slain monster's
                # special_reward. If present, leave the new prompt intact and
                # stash the may-slay resume — it'll fire from
                # `_maybe_resume_post_slay_continuation` once the full chain
                # clears (compound legs + final choose / banish / flip / etc.).
                _new_required_action = (self.game.action_required or {}).get("action", "") if isinstance(self.game.action_required, dict) else ""
                _new_concurrent = getattr(self.game, "concurrent_action", None)
                _opened_followup = (
                    (_new_required_action and _new_required_action != "slay_monster_payment")
                    or (_new_concurrent is not _prior_concurrent)
                    or (getattr(self.game, "pending_payout_continuation", None) is not None)
                )
                if _opened_followup:
                    self.game.pending_post_slay_resume = {
                        "player_id": player_id,
                        "resume_kind": resume_kind,
                    }
                    return
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                self.game.slay._resume_after_immediate_slay(resume_kind)
                return

            if prc0.get("kind") == "domain_boost_monster" and str(current_required).strip() == "choose_monster_strength":
                act = (action or "").strip().lower()
                opts = list(prc0.get("options") or [])
                if not act.startswith("choose_monster "):
                    return
                try:
                    idx = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if idx < 0 or idx >= len(opts):
                    return
                target = self.game._player_by_id(player_id)
                if not target:
                    return
                mid = int(opts[idx].get("monster_id", -1))
                delta = int(prc0.get("delta", 0) or 0)
                if not self.game.domain_effects._apply_monster_strength_boost(mid, delta):
                    return
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} chose \"{opts[idx].get('name', '?')}\" for "
                    f"\"{prc0.get('domain_name', 'Domain')}\" (+{delta} strength cost)."
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                return

            if prc0.get("kind") == "domain_self_convert" and str(current_required).strip() == "domain_self_convert":
                act = (action or "").strip().lower()
                if player_id != prc0.get("player_id"):
                    return
                ctx = prc0.get("context", "domain_activation")
                if act == "skip":
                    self.game.pending_required_choice = None
                    self.game.action_required["id"] = self.game.game_id
                    self.game.action_required["action"] = ""
                    if ctx == "action_end_queue":
                        self.game.pending_action_end_queue.pop(0) if self.game.pending_action_end_queue else None
                        if not self.game.domain_effects._drain_action_end_manipulate_queue():
                            pass  # advance_tick handles turn end
                    else:
                        self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                if act != "confirm_self_convert":
                    return
                kv = prc0.get("kv") or {}
                pay_k, pay_n = _parse_resource_kv(kv.get("pay", ""))
                target = self.game._player_by_id(player_id)
                if not target or not pay_k or pay_n <= 0:
                    return
                if not self.game.choose._player_can_afford_self_convert_resources(target, pay_k, pay_n):
                    return
                before = self.game._player_scores_line(target)
                self.game.choose._apply_self_convert_kv_to_player(target, kv)
                after = self.game._player_scores_line(target)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} confirmed \"{prc0.get('domain_name', 'Domain')}\" trade; scores {before} -> {after}"
                )
                self.game.pending_required_choice = None
                self.game.action_required["id"] = self.game.game_id
                self.game.action_required["action"] = ""
                if ctx == "action_end_queue":
                    self.game.pending_action_end_queue.pop(0) if self.game.pending_action_end_queue else None
                    if not self.game.domain_effects._drain_action_end_manipulate_queue():
                        pass  # advance_tick handles turn end
                else:
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "domain_manipulate_player" and str(current_required).strip() == "choose_player":
                act = (action or "").strip().lower()
                from_activation = bool(prc0.get("from_activation"))
                if prc0.get("allow_skip") and act == "skip":
                    if not from_activation and self.game.pending_action_end_queue:
                        self.game.pending_action_end_queue.pop(0)
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    if from_activation:
                        self.game.domain_effects._resume_after_domain_activation_follow_up()
                    elif not self.game.domain_effects._drain_action_end_manipulate_queue():
                        self.game.action_required["id"] = self.game.game_id
                        self.game.action_required["action"] = ""
                    return
                opts = list(prc0.get("options") or [])
                if not act.startswith("choose_player "):
                    return
                try:
                    idx = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if idx < 0 or idx >= len(opts):
                    return
                item = prc0.get("item") or {}
                tid = opts[idx].get("player_id")
                self.game.domain_effects._apply_manipulate_player_choice(player_id, tid, item)
                if not from_activation and self.game.pending_action_end_queue:
                    self.game.pending_action_end_queue.pop(0)
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                if from_activation:
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                elif not self.game.domain_effects._drain_action_end_manipulate_queue():
                    self.game.action_required["id"] = self.game.game_id
                    self.game.action_required["action"] = ""
                return

            if prc0.get("kind") == "monster_flip_citizen_targeted" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if prc0.get("allow_skip") and act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to flip a citizen."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    return
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self.game._player_by_id(target_pid)
                if not target:
                    return
                citizen_opts = []
                for i, c in enumerate(list(getattr(target, "owned_citizens", []) or [])):
                    if getattr(c, "is_flipped", False):
                        continue
                    citizen_opts.append({
                        "token": "citizen.owned",
                        "idx": i,
                        "name": getattr(c, "name", "?"),
                        "citizen_id": int(getattr(c, "citizen_id", -1)),
                    })
                if not citizen_opts:
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} could not flip a citizen from "
                        f"{self.game._player_label(target_pid)} (no eligible citizens); effect lost."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    return
                self.game.pending_required_choice = {
                    "kind": "monster_flip_citizen_targeted",
                    "player_id": player_id,
                    "stage": "citizen",
                    "target_player_id": target_pid,
                    "options": citizen_opts,
                    "allow_skip": bool(prc0.get("allow_skip")),
                }
                self.game.action_required["id"] = player_id
                self.game.action_required["action"] = "choose_owned_card"
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} chose {self.game._player_label(target_pid)} "
                    f"and is now picking a citizen to flip."
                )
                return

            if prc0.get("kind") == "monster_flip_citizen_targeted" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if prc0.get("allow_skip") and act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to flip a citizen."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    return
                if not act.startswith("choose_owned_card "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = prc0.get("target_player_id")
                target = self.game._player_by_id(target_pid)
                if not target:
                    return
                src_idx = int(opts[sel].get("idx", -1))
                owned = list(getattr(target, "owned_citizens", []) or [])
                if src_idx < 0 or src_idx >= len(owned):
                    return
                citizen = owned[src_idx]
                if getattr(citizen, "is_flipped", False):
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    return
                self.game._citizen_set_flipped(citizen, True)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} flipped citizen "
                    f"\"{getattr(citizen, 'name', '?')}\" face-down on "
                    f"{self.game._player_label(target_pid)}'s tableau."
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                self.game.payouts._resume_payout_continuation()
                return

            if prc0.get("kind") == "banish_player_citizen" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self.game._player_by_id(target_pid)
                if not target:
                    return
                citizen_opts = []
                for i, c in enumerate(list(getattr(target, "owned_citizens", []) or [])):
                    citizen_opts.append({
                        "token": "citizen.owned",
                        "idx": i,
                        "name": getattr(c, "name", "?"),
                        "citizen_id": int(getattr(c, "citizen_id", -1)),
                    })
                if not citizen_opts:
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} could not banish a citizen from "
                        f"{self.game._player_label(target_pid)} (no citizens); effect lost."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                self.game.pending_required_choice = {
                    "kind": "banish_player_citizen",
                    "player_id": player_id,
                    "stage": "citizen",
                    "target_player_id": target_pid,
                    "options": citizen_opts,
                }
                self.game.action_required["id"] = player_id
                self.game.action_required["action"] = "choose_owned_card"
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} chose {self.game._player_label(target_pid)} "
                    f"and is now picking a citizen to banish (Sunder Bay)."
                )
                return

            if prc0.get("kind") == "banish_player_citizen" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose_owned_card "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = prc0.get("target_player_id")
                target = self.game._player_by_id(target_pid)
                if not target:
                    return
                src_idx = int(opts[sel].get("idx", -1))
                owned = list(getattr(target, "owned_citizens", []) or [])
                if src_idx < 0 or src_idx >= len(owned):
                    return
                citizen = owned[src_idx]
                citizen_name = getattr(citizen, "name", "?")
                target.owned_citizens.pop(src_idx)
                self.game._citizen_set_flipped(citizen, False)
                self.game.banish_pile.append(citizen)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} banished citizen \"{citizen_name}\" "
                    f"from {self.game._player_label(target_pid)}'s tableau (Sunder Bay)."
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                self.game.domain_effects._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "steal_citizen" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self.game._player_by_id(target_pid)
                if not target:
                    return
                max_cost = int(prc0.get("max_cost", 2))
                citizen_opts = []
                for i, c in enumerate(list(getattr(target, "owned_citizens", []) or [])):
                    if int(getattr(c, "gold_cost", 0) or 0) > max_cost:
                        continue
                    citizen_opts.append({
                        "token": "citizen.owned",
                        "idx": i,
                        "name": getattr(c, "name", "?"),
                        "citizen_id": int(getattr(c, "citizen_id", -1)),
                        "gold_cost": int(getattr(c, "gold_cost", 0) or 0),
                        "is_flipped": bool(getattr(c, "is_flipped", False)),
                    })
                if not citizen_opts:
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} could not steal from "
                        f"{self.game._player_label(target_pid)} (no eligible citizens); effect lost."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                self.game.pending_required_choice = {
                    "kind": "steal_citizen",
                    "player_id": player_id,
                    "stage": "citizen",
                    "target_player_id": target_pid,
                    "max_cost": max_cost,
                    "options": citizen_opts,
                }
                self.game.action_required["id"] = player_id
                self.game.action_required["action"] = "choose_owned_card"
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} chose {self.game._player_label(target_pid)} "
                    f"and is now picking a citizen to steal (Hobb's End)."
                )
                return

            if prc0.get("kind") == "steal_citizen" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose_owned_card "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = prc0.get("target_player_id")
                target = self.game._player_by_id(target_pid)
                actor = self.game._player_by_id(player_id)
                if not target or not actor:
                    return
                src_idx = int(opts[sel].get("idx", -1))
                owned = list(getattr(target, "owned_citizens", []) or [])
                if src_idx < 0 or src_idx >= len(owned):
                    return
                citizen = owned[src_idx]
                citizen_name = getattr(citizen, "name", "?")
                target.owned_citizens.pop(src_idx)
                self.game._citizen_set_flipped(citizen, False)
                actor.owned_citizens.append(citizen)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} stole citizen \"{citizen_name}\" "
                    f"from {self.game._player_label(target_pid)}'s tableau (Hobb's End)."
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                self.game.domain_effects._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "domain_choose_resource" and str(current_required).strip() == "domain_choose_resource":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                choices = list(prc0.get("choices") or [])
                if not act.startswith("choose "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(choices):
                    return
                r, amt = choices[sel]
                player_obj = self.game._player_by_id(player_id)
                if player_obj:
                    before = self.game._player_scores_line(player_obj)
                    self.game.domain_effects._bank_gain_for_active(player_obj, r, int(amt))
                    after = self.game._player_scores_line(player_obj)
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} chose {r}+{amt} from \"{prc0.get('domain_name', 'Domain')}\"; "
                        f"scores {before} -> {after}"
                    )
                self.game.pending_required_choice = None
                self.game.action_required["id"] = self.game.game_id
                self.game.action_required["action"] = ""
                if self.game.pending_action_end_queue:
                    self.game.pending_action_end_queue.pop(0)
                if not self.game.domain_effects._drain_action_end_manipulate_queue():
                    pass  # advance_tick handles turn end
                return

            if prc0.get("kind") == "banish_random_player_monster" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self.game._player_by_id(target_pid)
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                if not target:
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                monsters = list(getattr(target, "owned_monsters", []) or [])
                if not monsters:
                    self.game._log_game_event(
                        f"{self.game._player_label(target_pid)} had no monsters to banish (Wandering Flame)."
                    )
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                idx = random.randrange(len(monsters))
                banished = monsters.pop(idx)
                target.owned_monsters = monsters
                self.game.banish_pile.append(banished)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} banished \"{getattr(banished, 'name', '?')}\" "
                    f"from {self.game._player_label(target_pid)}'s tableau at random (Wandering Flame)."
                )
                self.game.domain_effects._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "domain_take_owned" and str(current_required).strip() == "choose_player":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                domain_name = prc0.get("domain_name", "Domain")
                if prc0.get("allow_skip") and act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined activation effect on \"{domain_name}\"."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                if not act.startswith("choose_player "):
                    return
                opts = list(prc0.get("options") or [])
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                if sel < 0 or sel >= len(opts):
                    return
                target_pid = opts[sel].get("player_id")
                target = self.game._player_by_id(target_pid)
                active = self.game._player_by_id(player_id)
                if not target or not active:
                    return
                card_kind = prc0.get("card_kind")
                pick = (prc0.get("pick") or "random").lower()
                attr = "owned_monsters" if card_kind == "monster" else "owned_citizens"
                owned = list(getattr(target, attr, []) or [])
                if not owned:
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} could not steal a {card_kind} from "
                        f"{self.game._player_label(target_pid)} via \"{domain_name}\" "
                        f"(no {card_kind}s to take); activation effect lost."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                if pick == "random":
                    src_idx = random.randrange(len(owned))
                else:
                    src_idx = 0
                card = owned[src_idx]
                card_label = getattr(card, "name", "?")
                del getattr(target, attr)[src_idx]
                getattr(active, attr).append(card)
                if card_kind == "monster":
                    target.owned_monster_attributes = self.game.owned_monster_attributes(target_pid)
                    active.owned_monster_attributes = self.game.owned_monster_attributes(player_id)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} stole {card_kind} \"{card_label}\" from "
                    f"{self.game._player_label(target_pid)} via \"{domain_name}\"."
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                self.game.domain_effects._resume_after_domain_activation_follow_up()
                return

            if prc0.get("kind") == "banish_owned_card" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                card_kind = prc0.get("card_kind")
                if prc0.get("allow_skip") and act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to banish a {card_kind}."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.payouts._resume_payout_continuation()
                    return
                if not act.startswith("choose_owned_card "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                opts = list(prc0.get("options") or [])
                if sel < 0 or sel >= len(opts):
                    return
                src_idx = int(opts[sel].get("idx", -1))
                card_label = opts[sel].get("name", "?")
                player = self.game._player_by_id(player_id)
                if not player:
                    return
                if card_kind == "citizen":
                    banished = self.game.payouts._banish_owned_citizen(player, src_idx)
                else:
                    banished = None
                if not banished:
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.payouts._resume_payout_continuation()
                    return
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} banished {card_kind} "
                    f"\"{card_label}\" to the banish pile."
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                self.game.payouts._resume_payout_continuation()
                return

            if prc0.get("kind") == "banish_center_card" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                card_kind = prc0.get("card_kind")
                if prc0.get("allow_skip") and act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to banish a center-stack {card_kind}."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.payouts._resume_payout_continuation()
                    return
                if not act.startswith("choose_owned_card "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                opts = list(prc0.get("options") or [])
                if sel < 0 or sel >= len(opts):
                    return
                stack_idx = int(opts[sel].get("idx", -1))
                card_label = opts[sel].get("name", "?")
                if card_kind == "citizen":
                    banished = self.game.payouts._banish_center_citizen(stack_idx)
                elif card_kind == "monster":
                    banished = self.game.payouts._banish_center_monster(stack_idx)
                elif card_kind == "domain":
                    banished = self.game.payouts._banish_center_domain(stack_idx)
                else:
                    banished = None
                if not banished:
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.payouts._resume_payout_continuation()
                    return
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} banished center-stack {card_kind} "
                    f"\"{card_label}\" to the banish pile."
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                self.game.payouts._resume_payout_continuation()
                return

            if prc0.get("kind") == "banish_roll_minion" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                if act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to banish a Minion (The Northern Wall)."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    return
                if not act.startswith("choose_owned_card "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                opts = list(prc0.get("options") or [])
                if sel < 0 or sel >= len(opts):
                    return
                stack_idx = int(opts[sel].get("idx", -1))
                card_label = opts[sel].get("name", "?")
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                banished = self.game.payouts._banish_center_monster(stack_idx)
                if banished:
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} banished Minion \"{card_label}\" "
                        f"from the center (The Northern Wall)."
                    )
                return

            if prc0.get("kind") == "domain_return_owned" and str(current_required).strip() == "choose_owned_card":
                if player_id != prc0.get("player_id"):
                    return
                act = (action or "").strip().lower()
                domain_name = prc0.get("domain_name", "Domain")
                if prc0.get("allow_skip") and act == "skip":
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined activation effect on \"{domain_name}\"."
                    )
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                if not act.startswith("choose_owned_card "):
                    return
                try:
                    sel = int(act.split()[1]) - 1
                except (IndexError, ValueError):
                    return
                opts = list(prc0.get("options") or [])
                if sel < 0 or sel >= len(opts):
                    return
                target = self.game._player_by_id(player_id)
                if not target:
                    return
                opt = opts[sel]
                card_kind = prc0.get("card_kind")
                src_idx = int(opt.get("idx", -1))
                card_label = opt.get("name", "?")
                if card_kind == "monster":
                    owned = list(getattr(target, "owned_monsters", []) or [])
                    if src_idx < 0 or src_idx >= len(owned):
                        return
                    monster = owned[src_idx]
                    if not self.game.domain_effects._return_monster_to_stack(monster):
                        self.game._log_game_event(
                            f"{self.game._player_label(player_id)} could not return monster \"{card_label}\" "
                            f"(unknown area mapping); activation effect lost."
                        )
                        self.game.action_required["action"] = ""
                        self.game.action_required["id"] = self.game.game_id
                        self.game.pending_required_choice = None
                        self.game.domain_effects._resume_after_domain_activation_follow_up()
                        return
                    del target.owned_monsters[src_idx]
                    target.owned_monster_attributes = self.game.owned_monster_attributes(player_id)
                elif card_kind == "citizen":
                    owned = list(getattr(target, "owned_citizens", []) or [])
                    if src_idx < 0 or src_idx >= len(owned):
                        return
                    citizen = owned[src_idx]
                    if not self.game.domain_effects._return_citizen_to_stack(citizen):
                        self.game._log_game_event(
                            f"{self.game._player_label(player_id)} could not return citizen \"{card_label}\" "
                            f"(invalid roll mapping); activation effect lost."
                        )
                        self.game.action_required["action"] = ""
                        self.game.action_required["id"] = self.game.game_id
                        self.game.pending_required_choice = None
                        self.game.domain_effects._resume_after_domain_activation_follow_up()
                        return
                    del target.owned_citizens[src_idx]
                else:
                    return
                res = (prc0.get("resource") or "").strip().lower()
                amount = int(prc0.get("amount", 0) or 0)
                before = self.game._player_scores_line(target)
                if amount > 0:
                    if res == "g":
                        target.gold_score = int(target.gold_score) + amount
                        self.game.harvest._bump_harvest_delta(target, amount, 0, 0, 0)
                    elif res == "s":
                        target.strength_score = int(target.strength_score) + amount
                        self.game.harvest._bump_harvest_delta(target, 0, amount, 0, 0)
                    elif res == "m":
                        target.magic_score = int(target.magic_score) + amount
                        self.game.harvest._bump_harvest_delta(target, 0, 0, amount, 0)
                    elif res == "v":
                        target.victory_score = int(getattr(target, "victory_score", 0)) + amount
                        self.game.harvest._bump_harvest_delta(target, 0, 0, 0, amount)
                after = self.game._player_scores_line(target)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} returned {card_kind} \"{card_label}\" via "
                    f"\"{domain_name}\"; scores {before} -> {after}"
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                self.game.domain_effects._resume_after_domain_activation_follow_up()
                return

            # Resolve a blocking "choose ..." special payout prompt.
            if str(current_required).strip().lower().startswith("choose "):
                prc = getattr(self.game, "pending_required_choice", None) or {}
                normalized, options = self.game.choose._normalize_choose_command(current_required)
                if prc.get("kind") == "special_payout_choose":
                    options = list(prc.get("options") or [])
                else:
                    options = self.game.choose._expand_choose_options_for_prompt(
                        self.game.choose._filter_unavailable_choose_options(options)
                    )
                if not options:
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game.pending_required_choice = None
                    self.game.harvest._maybe_resume_harvest_prompt()
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
                target = self.game._player_by_id(player_id)
                if not target:
                    return
                before = self.game._player_scores_line(target)
                if not self.game.choose._apply_choose_option(player_id, opt):
                    return
                after = self.game._player_scores_line(target)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} chose ({idx + 1}/{len(options)}) from \"{normalized}\": "
                    f"{self.game.choose._describe_choose_option(opt)}; scores {before} -> {after}"
                )
                # Clear the prompt, then chain any remaining compound legs, and finally
                # resume harvest automation if applicable. If the continuation itself
                # opens a new prompt, harvest resume will see action_required set and
                # back off naturally.
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                if getattr(self.game, "pending_required_choice", None):
                    self.game.pending_required_choice = None
                self.game.payouts._resume_payout_continuation()
                # If we're in the post-finalize bonus-drain phase (Herald-style
                # `no_payout` activations open a regular `choose` prompt here),
                # pop this player and fire the next pending bonus.
                if (
                    self.game.phase == "harvest"
                    and getattr(self.game, "harvest_processed", False)
                    and (self.game.action_required.get("action") or "") == ""
                    and self.game.pending_harvest_choices
                    and self.game.pending_harvest_choices[0] == player_id
                ):
                    self.game.pending_harvest_choices.pop(0)
                    if self.game.pending_harvest_choices:
                        self.game.harvest._activate_finalize_bonus_for(self.game.pending_harvest_choices[0])
                        return
                self.game.harvest._maybe_resume_harvest_prompt()
                return

            self.game.action_required["action"] = action
            self.game.action_required["id"] = self.game.game_id

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
        ca = getattr(self.game, "concurrent_action", None) or None
        prior_ca = ca
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

        handler.apply(self.game, player_id, response)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} submitted ({ca.get('kind')})."
        )
        if not (ca.get("pending") or []):
            self.game._log_game_event(f"All players finished: {ca.get('kind')}.")
            handler.finalize(self.game)
            # If finalize reopened a new concurrent action, don't clobber it.
            if self.game.concurrent_action is prior_ca and not (prior_ca.get("pending") or []):
                self.game.concurrent_action = None
            # Drive the engine forward after the concurrent action resolves.
            if self.game.phase == "setup":
                # Setup stall: advance until the first actionable state.
                while self.game.lifecycle.advance_tick():
                    if self.game.phase == "action":
                        break
            elif self.game.phase == "harvest":
                # Harvest stall: concurrent gate just cleared; resume
                # harvest automation and any queued may-slay prompts.
                self.game.harvest._maybe_resume_harvest_prompt()
                # If harvest is fully resolved (e.g. the end-of-harvest bonus
                # gate just cleared), advance through to the action phase so
                # the next player can start their turn. Mirrors harvest_card
                # and finalize_roll which call advance_tick in the same spot.
                if (
                    self.game.phase == "harvest"
                    and getattr(self.game, "harvest_processed", False)
                    and not self.game.harvest._harvest_action_blocked()
                ):
                    while self.game.lifecycle.advance_tick():
                        if self.game.phase == "action":
                            break
            else:
                # Mid-game concurrent action (e.g. Cursed Cavern flip during action phase):
                # if the active player still has actions, refresh the standard-action
                # gate and drain any queued event activation that was waiting behind
                # this prompt. If they spent their last action, finish the turn now
                # that the block is cleared.
                if (
                    getattr(self.game, "phase", None) == "action"
                    and int(getattr(self.game, "actions_remaining", 0) or 0) > 0
                ):
                    self.game.lifecycle.advance_tick()
                self.game.lifecycle.finish_turn_if_no_actions_remaining()

    def hire_citizen(self, player_id, citizen_id, gp=0, mp=0, sp=0):
        """
        Hire the top/accessible citizen from a stack.

        Gold cost scales by +1 for each already-owned face-up card with the same
        name, counting owned citizens and starting cards. Flipped citizens stay
        known on the tableau, but do not count for duplicate citizen costs.

        Payment is (gold, magic, strength); only gold and magic may be used (strength must be 0).
        """
        gp, sp, mp = _n(gp), _n(sp), _n(mp)

        # Normally citizens only live on the citizen grid, but the Recruit the
        # King's Guard event drops its guards on top of the event card wherever it
        # was revealed (any grid). Scan every grid so those guards are hireable
        # too; non-citizen tops are skipped by the citizen_id guard below.
        all_stacks = (
            list(self.game.citizen_grid)
            + list(self.game.monster_grid)
            + list(self.game.domain_grid)
        )
        for citizen_stack in all_stacks:
            if not citizen_stack:
                continue
            top = citizen_stack[-1]
            if getattr(top, "citizen_id", None) is None:
                continue  # Event/Exhausted placeholder — not hirable
            if int(getattr(top, "citizen_id", -1)) != int(citizen_id) or not getattr(top, "is_accessible", False):
                continue

            if self.game._citizen_blocked_by_pirate_blockade(top):
                raise ValueError(
                    "Pirate Blockade: a citizen matching this turn's roll cannot be recruited."
                )

            player = None
            for p in self.game.player_list:
                if p.player_id == player_id:
                    player = p
                    break
            if not player:
                raise ValueError("Player not found.")

            owned_same_name = 0
            has_emerald = self.game._player_has_action_effect_flag(player, "action.emeraldstronghold")
            if not has_emerald:
                for c in getattr(player, "owned_citizens", []) or []:
                    if getattr(c, "is_flipped", False):
                        continue
                    if getattr(c, "name", None) == top.name:
                        owned_same_name += 1
                for s in getattr(player, "owned_starters", []) or []:
                    if getattr(s, "name", None) == top.name:
                        owned_same_name += 1

            scaled_cost = int(getattr(top, "gold_cost", 0) or 0) + int(owned_same_name)
            if self.game._player_has_action_effect_flag(player, "action.defiantridge"):
                scaled_cost = max(0, scaled_cost - 1)
            has_shilina = self.game._player_has_action_effect_flag(player, "action.newshilinatower")
            _validate_hire_or_domain_gold_payment(player, scaled_cost, gp, sp, mp, allow_strength=has_shilina)

            before = self.game._player_scores_line(player)
            player.gold_score = player.gold_score - gp
            player.magic_score = player.magic_score - mp
            player.strength_score = player.strength_score - sp
            hired = citizen_stack.pop(-1)
            self.game._citizen_set_flipped(hired, False)
            player.owned_citizens.append(hired)

            self.game.choose._finalize_citizen_stack_after_claiming_top(citizen_stack)
            after = self.game._player_scores_line(player)
            pay = self.game._format_resource_payment(gp, sp, mp)
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} hired citizen \"{top.name}\" ({pay}); scores {before} -> {after}"
            )
            self.game.domain_effects._apply_action_event_gain_passives(player, "hire")
            return

        raise ValueError("Citizen not available to hire.")

    def slay_monster(self, player_id, monster_id, sp=0, mp=0, gp=0, event_id=None):
        gp, sp, mp = _n(gp), _n(sp), _n(mp)
        payout = [0, 0, 0, 0]

        # Events can land on any grid depending on which stack emptied first.
        # Regular monsters normally only live in monster_grid, but the Undead
        # Samurai Lord event scatters Undead Samurai minions (regular monsters)
        # onto any grid, so search all three either way. Card ids are unique, so
        # the extra grids never produce a false match for a normal monster.
        candidate_grids = [self.game.monster_grid, self.game.citizen_grid, self.game.domain_grid]

        for grid in candidate_grids:
          for monster_stack in grid:
            if not monster_stack:
                continue
            top = monster_stack[-1]
            is_event_card = isinstance(top, Event)
            # Match by monster_id for regular monsters, or event_id for Event cards.
            if is_event_card:
                if event_id is not None:
                    if int(getattr(top, "event_id", -1)) != int(event_id):
                        continue
                else:
                    continue
            else:
                # When searching for an event, skip all non-Event cards.
                if event_id is not None:
                    continue
                if int(getattr(top, "monster_id", -1)) != int(monster_id):
                    continue
            if not getattr(top, "is_accessible", False):
                continue

            player = None
            for p in self.game.player_list:
                if p.player_id == player_id:
                    player = p
                    break
            if not player:
                raise ValueError("Player not found.")

            # Compute effective costs including any event-applied extra costs.
            effective_strength_cost = (
                int(getattr(top, "strength_cost", 0) or 0)
                + int(getattr(top, "extra_strength_cost", 0) or 0)
            )
            effective_magic_cost = (
                int(getattr(top, "magic_cost", 0) or 0)
                + int(getattr(top, "extra_magic_cost", 0) or 0)
            )
            effective_gold_cost = int(getattr(top, "extra_gold_cost", 0) or 0)
            if getattr(top, "has_special_cost", False):
                cost_deltas = self.game._monster_special_cost_deltas(
                    player, getattr(top, "special_cost", None)
                )
                effective_strength_cost += int(cost_deltas.get("s", 0) or 0)
                effective_magic_cost += int(cost_deltas.get("m", 0) or 0)
                effective_gold_cost += int(cost_deltas.get("g", 0) or 0)
            if self.game._player_has_action_effect_flag(player, "action.fortskyler"):
                effective_strength_cost = max(0, effective_strength_cost - 1)
            if self.game._player_has_action_effect_flag(player, "action.darklordrising"):
                effective_magic_cost += self.game.events.dark_lord_surcharge()

            _validate_monster_slay_payment(
                player, effective_strength_cost, effective_magic_cost, effective_gold_cost, gp, sp, mp
            )

            before = self.game._player_scores_line(player)
            monster_to_add = monster_stack.pop(-1)
            player.gold_score = player.gold_score - gp
            player.strength_score = player.strength_score - sp
            player.magic_score = player.magic_score - mp
            player.owned_monsters.append(monster_to_add)

            if top.has_special_reward:
                # Snapshot action_required / concurrent_action BEFORE the special
                # payout so the deferral check can tell whether *this* call opened
                # a follow-up prompt. Using "is there an action_required now?" as
                # the proxy breaks when slay_monster is invoked from inside a
                # prompt handler (the may-slay flow leaves action_required set to
                # `slay_monster_payment`), causing the -9999 sentinel to leak into
                # the player's gold score.
                _prior_required_action = (self.game.action_required or {}).get("action", "") if isinstance(self.game.action_required, dict) else ""
                _prior_concurrent = getattr(self.game, "concurrent_action", None)
                self.game._immediate_slay_source_label = getattr(top, "name", "Monster")
                # Expose the slain card so card-state rewards (Ghost Ship's
                # gain_self_gold_pool) can read accumulated tokens off it.
                self.game._immediate_slay_source_card = top
                try:
                    payout = self.game.payouts.execute_special_payout(top.special_reward, player_id)
                finally:
                    self.game._immediate_slay_source_label = None
                    self.game._immediate_slay_source_card = None
                _new_required_action = (self.game.action_required or {}).get("action", "") if isinstance(self.game.action_required, dict) else ""
                _new_concurrent = getattr(self.game, "concurrent_action", None)
                _opened_new_prompt = (
                    (_new_required_action and _new_required_action != _prior_required_action)
                    or (_new_concurrent is not _prior_concurrent)
                )
                if isinstance(payout, list) and len(payout) >= 1 and payout[0] == -9999:
                    if not _opened_new_prompt:
                        payout = [0, 0, 0, 0]
            payout[0] = payout[0] + int(getattr(top, "gold_reward", 0) or 0)
            payout[1] = payout[1] + int(getattr(top, "strength_reward", 0) or 0)
            payout[2] = payout[2] + int(getattr(top, "magic_reward", 0) or 0)
            payout[3] = payout[3] + int(getattr(top, "vp_reward", 0) or 0)
            player.gold_score = player.gold_score + payout[0]
            player.strength_score = player.strength_score + payout[1]
            player.magic_score = player.magic_score + payout[2]
            player.victory_score = player.victory_score + payout[3]
            player.owned_monster_attributes = self.game.owned_monster_attributes(player_id)

            if monster_stack:
                monster_stack[-1].toggle_accessibility(True)
            elif is_event_card:
                # Event already counted toward exhausted_count when it was placed.
                # Just drop a static placeholder so the slot still shows the exhausted back.
                from cards import Exhausted as _Exhausted
                placeholder = _Exhausted(int(self.game.exhausted_count))
                placeholder.toggle_visibility(True)
                monster_stack.append(placeholder)
            elif self.game.exhausted_stack:
                # Draw the next exhausted card onto the emptied slot. A revealed
                # activation/passive Event fires its effect here (see EventsEngine).
                self.game.events.reveal_exhausted_onto_stack(monster_stack)
            after = self.game._player_scores_line(player)
            pay = self.game._format_resource_payment(gp, sp, mp)
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} slew \"{monster_to_add.name}\" ({pay}); scores {before} -> {after}"
            )
            # Slaying the Undead Samurai Lord event banishes any of its minions
            # still scattered on the board (the slayer's owned minions were already
            # tallied for the VP reward via its `count area` special_reward above).
            if is_event_card and getattr(top, "name", "") == "Undead Samurai Lord":
                self.game.events.on_undead_samurai_lord_slain()
            self.game.domain_effects._apply_action_event_gain_passives(player, "slay")
            self.game.harvest._apply_reactive_slay_passives(slayer_id=player_id)
            return

        raise ValueError("Monster not available to slay.")

    def build_domain(self, player_id, domain_id, gp=0, mp=0, sp=0):
        gp, sp, mp = _n(gp), _n(sp), _n(mp)

        for domain_stack in self.game.domain_grid:
            if not domain_stack:
                continue
            top = domain_stack[-1]
            if getattr(top, "domain_id", None) is None:
                continue  # Event/Exhausted placeholder — not buildable
            if int(getattr(top, "domain_id", -1)) != int(domain_id):
                continue
            if not getattr(top, "is_accessible", False):
                continue
            if not getattr(top, "is_visible", True):
                continue

            player = None
            for p in self.game.player_list:
                if p.player_id == player_id:
                    player = p
                    break
            if not player:
                raise ValueError("Player not found.")

            # Domain role prerequisites must be satisfied by owned citizens.
            # Starters and already-owned domains do not count toward this gate.
            have = self.game._player_citizen_role_totals(player)
            req_shadow = int(getattr(top, "shadow_count", 0) or 0)
            req_holy = int(getattr(top, "holy_count", 0) or 0)
            req_soldier = int(getattr(top, "soldier_count", 0) or 0)
            req_worker = int(getattr(top, "worker_count", 0) or 0)
            missing = []
            if have["shadow"] < req_shadow:
                missing.append(f"shadow {have['shadow']}/{req_shadow}")
            if have["holy"] < req_holy:
                missing.append(f"holy {have['holy']}/{req_holy}")
            if have["soldier"] < req_soldier:
                missing.append(f"soldier {have['soldier']}/{req_soldier}")
            if have["worker"] < req_worker:
                missing.append(f"worker {have['worker']}/{req_worker}")
            if missing:
                raise ValueError(
                    "Domain role requirements not met (citizens only): " + ", ".join(missing)
                )

            gold_cost = int(getattr(top, "gold_cost", 0) or 0)
            has_pratchett = self.game._player_has_action_effect_flag(player, "action.pratchettsplateau")
            if has_pratchett:
                gold_cost = max(0, gold_cost - 1)
            if self.game._player_has_action_effect_flag(player, "action.blessedlands"):
                gold_cost = max(0, gold_cost - self.game.events.blessed_lands_discount())
            _validate_hire_or_domain_gold_payment(player, gold_cost, gp, sp, mp)

            before = self.game._player_scores_line(player)
            player.gold_score = player.gold_score - gp
            player.magic_score = player.magic_score - mp
            bought = domain_stack.pop(-1)
            bought.acquired_turn_number = int(self.game.turn_number)
            player.owned_domains.append(bought)

            vp_gain = int(getattr(bought, "vp_reward", 0) or 0)
            if vp_gain:
                player.victory_score = int(getattr(player, "victory_score", 0) or 0) + vp_gain
                self.game.harvest._bump_harvest_delta(player, 0, 0, 0, vp_gain)

            # Resolve the purchased domain's own activation/passive first so that,
            # if buying empties this stack, a revealed Event's activation does not
            # collide with the domain's prompt (the event defers if a prompt is open).
            self.game.domain_effects._apply_domain_activation_effect(player, bought)
            self.game.domain_effects._apply_action_event_gain_passives(player, "build")
            if not domain_stack and self.game.exhausted_stack:
                self.game.events.reveal_exhausted_onto_stack(domain_stack)
            after = self.game._player_scores_line(player)
            pay = self.game._format_resource_payment(gp, sp, mp)
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} bought domain \"{top.name}\" ({pay}); scores {before} -> {after}"
            )
            return

        raise ValueError("Domain not available to purchase.")

    def take_resource(self, player_id, resource):
        """
        Spend a standard action to gain +1 gold, strength, magic, or map (player's choice).
        """
        choice = (resource or "").strip().lower()
        if choice not in ("gold", "strength", "magic", "map"):
            raise ValueError('resource must be "gold", "strength", "magic", or "map".')
        if choice == "map" and not self.game.maps_enabled():
            raise ValueError("Maps are only available in the Crimson Seas preset.")

        player = None
        for p in self.game.player_list:
            if p.player_id == player_id:
                player = p
                break
        if not player:
            raise ValueError("Player not found.")

        before = self.game._player_scores_line(player)
        if choice == "gold":
            player.gold_score = int(getattr(player, "gold_score", 0)) + 1
        elif choice == "strength":
            player.strength_score = int(getattr(player, "strength_score", 0)) + 1
        elif choice == "map":
            player.map_score = int(getattr(player, "map_score", 0)) + 1
        else:
            player.magic_score = int(getattr(player, "magic_score", 0)) + 1

        after = self.game._player_scores_line(player)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} took +1 {choice} (standard action; no resource cost); "
            f"scores {before} -> {after}"
        )

