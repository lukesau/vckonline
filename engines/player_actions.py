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

            # Crimson Seas: place 1 of your resources into the Exekratys pool
            # (owed once per 6 rolled). Action form: "exekratys_offering <res>".
            if current_required == "exekratys_offering":
                prc_e = getattr(self.game, "pending_required_choice", None) or {}
                if prc_e.get("kind") != "exekratys_offering" or player_id != prc_e.get("player_id"):
                    return
                parts_e = (action or "").strip().lower().split()
                res_e = parts_e[1] if len(parts_e) > 1 and parts_e[0] == "exekratys_offering" else ""
                attr_e = {"gold": "gold_score", "strength": "strength_score", "magic": "magic_score"}.get(res_e)
                if not attr_e:
                    return
                target_e = self.game._player_by_id(player_id)
                if not target_e or int(getattr(target_e, attr_e, 0) or 0) <= 0:
                    return
                before_e = self.game._player_scores_line(target_e)
                setattr(target_e, attr_e, int(getattr(target_e, attr_e)) - 1)
                self.game.exekratys_resources[res_e] = int(self.game.exekratys_resources.get(res_e, 0)) + 1
                self.game.pending_exekratys_offerings = max(
                    0, int(getattr(self.game, "pending_exekratys_offerings", 0) or 0) - 1)
                after_e = self.game._player_scores_line(target_e)
                self.game._log_game_event(
                    f"{self.game._player_label(player_id)} placed 1 {res_e} on Exekratys (6 rolled); "
                    f"scores {before_e} -> {after_e}"
                )
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                self.game.pending_required_choice = None
                if self.game.pending_exekratys_offerings <= 0:
                    self.game.pending_exekratys_offering_player = None
                # Re-open for the next owed placement, if any (else advance_tick
                # will start harvest now that nothing is pending).
                self.game.dice._maybe_open_exekratys_offering_prompt(player_id)
                return

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

            # Crimson Seas "you may Sail" (Dampiar's Workshop). The actual sail
            # runs through the normal sail action_types (buy_goods / buy_tomes /
            # rescue_noble / sail_exekratys), consuming the bonus instead of a
            # regular action; here we only handle declining the opportunity.
            if current_required == "may_sail":
                prc_ms = getattr(self.game, "pending_required_choice", None) or {}
                if prc_ms.get("kind") != "sail_opportunity" or prc_ms.get("player_id") != player_id:
                    return
                act_ms = (action or "").strip().lower()
                if act_ms in ("skip", "decline", "no", "pass"):
                    self.game.pending_required_choice = None
                    self.game.pending_bonus_sail = None
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to Sail (Dampiar's Workshop)."
                    )
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
                # Stage 2: collect payment. The build behaves like a real build
                # action — Magic covers the Gold cost as a wild and face-up tomes
                # can help — so we hand off to a payment prompt rather than
                # spending an exact gold amount here.
                self.game.pending_required_choice = {
                    "kind": "domain_build_opportunity",
                    "stage": "pay",
                    "player_id": player_id,
                    "options": opts_db,
                    "domain_id": int(chosen["domain_id"]),
                    "domain_name": chosen.get("name", "Domain"),
                    "gold_cost": int(chosen.get("gold_cost", 0)),
                }
                self.game.action_required["action"] = "build_domain_payment"
                self.game.action_required["id"] = player_id
                return

            if current_required == "build_domain_payment":
                prc_b = getattr(self.game, "pending_required_choice", None) or {}
                if prc_b.get("kind") != "domain_build_opportunity" or prc_b.get("player_id") != player_id:
                    return
                act_b = (action or "").strip().lower()
                if act_b == "back":
                    self.game.pending_required_choice = {
                        "kind": "domain_build_opportunity",
                        "player_id": player_id,
                        "options": list(prc_b.get("options") or []),
                    }
                    self.game.action_required["action"] = "choose_domain_to_build"
                    self.game.action_required["id"] = player_id
                    return
                if act_b == "skip":
                    self.game.pending_required_choice = None
                    self.game.action_required["action"] = ""
                    self.game.action_required["id"] = self.game.game_id
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} declined to build a domain (Ararmartin Ridge)."
                    )
                    self.game.domain_effects._resume_after_domain_activation_follow_up()
                    return
                if not act_b.startswith("build_pay "):
                    return
                parts_b = act_b.split()
                if len(parts_b) < 3:
                    return
                try:
                    gp = int(parts_b[1])
                    mp = int(parts_b[2])
                except (TypeError, ValueError):
                    return
                # `gp`/`mp` are TOTAL payment (treasury + tomes). The optional
                # trailing `tg ts tm` are the tome portion: `build_pay g m tg ts tm`.
                build_tome_payment = None
                if len(parts_b) >= 6:
                    try:
                        build_tome_payment = self._sanitize_tome_payment({
                            "gold": int(parts_b[3]),
                            "strength": int(parts_b[4]),
                            "magic": int(parts_b[5]),
                        })
                    except (TypeError, ValueError):
                        build_tome_payment = None
                domain_name_b = prc_b.get("domain_name", "Domain")
                if build_tome_payment and (
                    build_tome_payment["gold"] > gp
                    or build_tome_payment["strength"] > 0
                    or build_tome_payment["magic"] > mp
                ):
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} could not build "
                        f"\"{domain_name_b}\" (Ararmartin Ridge): tome payment exceeds the amount being paid."
                    )
                    return
                domain_id_b = int(prc_b.get("domain_id"))
                self.game.pending_required_choice = None
                self.game.action_required["action"] = ""
                self.game.action_required["id"] = self.game.game_id
                redeemed = None
                try:
                    if build_tome_payment and any(build_tome_payment.values()):
                        redeemed = self.redeem_tomes_to_score(player_id, build_tome_payment)
                    self.build_domain(player_id, domain_id_b, gp=gp, mp=mp)
                except ValueError as e:
                    if redeemed:
                        self.refund_tomes_from_score(player_id, redeemed)
                    # Keep the payment prompt open so the player can retry.
                    self.game.pending_required_choice = prc_b
                    self.game.action_required["action"] = "build_domain_payment"
                    self.game.action_required["id"] = player_id
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} could not build "
                        f"\"{domain_name_b}\" (Ararmartin Ridge): {e}"
                    )
                    return
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
                # `gp`/`sp`/`mp` are TOTAL payment (treasury + tomes). The optional
                # trailing `tg ts tm` are the tome portion: `slay_pay gp sp mp tg ts tm`.
                # We redeem those tomes into the treasury up front, then run the
                # unchanged slay payment (which then simply spends them).
                slay_tome_payment = None
                if len(parts) >= 7:
                    try:
                        slay_tome_payment = self._sanitize_tome_payment({
                            "gold": int(parts[4]),
                            "strength": int(parts[5]),
                            "magic": int(parts[6]),
                        })
                    except (TypeError, ValueError):
                        slay_tome_payment = None
                if slay_tome_payment and (
                    slay_tome_payment["gold"] > gp
                    or slay_tome_payment["strength"] > sp
                    or slay_tome_payment["magic"] > mp
                ):
                    self.game._log_game_event(
                        f"{self.game._player_label(player_id)} could not slay "
                        f"\"{prc0.get('monster_name', '?')}\" via \"{source_label}\": "
                        f"tome payment exceeds the amount being paid."
                    )
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
                redeemed = None
                try:
                    if slay_tome_payment and any(slay_tome_payment.values()):
                        redeemed = self.redeem_tomes_to_score(player_id, slay_tome_payment)
                    self.slay_monster(player_id, monster_id, sp, mp, gp, event_id=event_id_opt)
                except ValueError as e:
                    # Payment didn't validate; surface in the log so the player
                    # sees why nothing happened, but keep the prompt open so they
                    # can retry with a corrected payment.
                    if redeemed:
                        self.refund_tomes_from_score(player_id, redeemed)
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
                elif card_kind == "noble":
                    banished = self.game.payouts._banish_center_noble(stack_idx)
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
        Tomes are redeemed into the player's score before this runs (see
        `redeem_tomes_to_score`), so they appear here as ordinary resources.
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

            # Domain role prerequisites must be satisfied by owned Citizens
            # and/or Nobles (Crimson Seas). Starters and already-owned domains
            # do not count toward this gate.
            have = self.game._player_build_role_totals(player)
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
                    "Domain role requirements not met (citizens and/or nobles): " + ", ".join(missing)
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
            # Build a Domain step 5 (base rules): reveal the next Domain in the
            # stack immediately as the final step of this action — not deferred
            # to turn end. An emptied stack refills from the exhausted deck.
            if domain_stack:
                new_top = domain_stack[-1]
                if getattr(new_top, "domain_id", None) is not None:
                    new_top.toggle_visibility(True)
                    new_top.toggle_accessibility(True)
            elif self.game.exhausted_stack:
                self.game.events.reveal_exhausted_onto_stack(domain_stack)
            after = self.game._player_scores_line(player)
            pay = self.game._format_resource_payment(gp, sp, mp)
            self.game._log_game_event(
                f"{self.game._player_label(player_id)} bought domain \"{top.name}\" ({pay}); scores {before} -> {after}"
            )
            return

        raise ValueError("Domain not available to purchase.")

    def _plan_sail_gold_payment(self, player, gold_cost, gp, mp, tome_payment, what):
        """Validate an explicit Gold/Magic payment for a Sail Gold cost.

        Magic is wild and may stand in for the Gold cost of buying Goods/Tomes,
        exactly like hiring a Citizen or building a Domain: `gp` Gold + `mp`
        Magic must total the cost, with at least 1 Gold paid whenever any Magic
        is used. Strength is not wild here. `gp`/`mp` are the TOTAL amounts
        (treasury + tomes); `tome_payment` says how much of each is funded by
        face-up tomes, so each tome count must not exceed its matching total
        (otherwise leftover redeemed credit would leak). Gold tomes count as
        Gold, Magic tomes as Magic.

        Validates against the post-redeem treasury (treasury portion is
        gp - gold-tomes / mp - magic-tomes) without mutating, and returns
        {tg, tm} for the caller to redeem. Raises ValueError on any problem.
        """
        gp, mp = _n(gp), _n(mp)
        gold_cost = int(gold_cost or 0)
        if gp < 0 or mp < 0:
            raise ValueError("Invalid payment (negative amounts).")
        tome_counts = self._sanitize_tome_payment(tome_payment)
        if tome_counts["strength"]:
            raise ValueError(f"Strength cannot pay for {what} (magic is the only wild).")
        tg = tome_counts["gold"]
        tm = tome_counts["magic"]
        if mp > 0 and gp < 1:
            raise ValueError("Must pay at least 1 gold to use magic as wild.")
        if gp + mp != gold_cost:
            raise ValueError(f"Payment must exactly match the {gold_cost} gold cost.")
        if tg > gp or tm > mp:
            raise ValueError("Tome payment exceeds the amount being paid.")
        self._verify_tome_payment_available(player, {"gold": tg, "strength": 0, "magic": tm})
        if int(getattr(player, "gold_score", 0) or 0) < gp - tg:
            raise ValueError(f"Insufficient gold to buy the selected {what}.")
        if int(getattr(player, "magic_score", 0) or 0) < mp - tm:
            raise ValueError(f"Insufficient magic to buy the selected {what}.")
        return {"tg": tg, "tm": tm}

    @staticmethod
    def _sail_pay_log_str(gold_portion, magic_portion):
        bits = []
        if gold_portion:
            bits.append(f"{gold_portion} gold")
        if magic_portion:
            bits.append(f"{magic_portion} magic")
        return " + ".join(bits) if bits else "0 gold"

    def buy_goods(self, player_id, slot_indices, gp=0, mp=0, tome_payment=None):
        """Sail to Araby and buy Goods tokens in one Sail action.

        A single Sail (costing 1 Map total) may buy ANY subset of the 3 face-up
        Goods slots; each costs its printed gold price (GOODS_SLOT_COSTS). After
        the purchase the board refreshes per the rulebook: the unbought tokens
        cascade down to the cheapest (bottom) slots preserving order, and new
        tokens are drawn from the supply to fill the emptied top slots.

        Payment is the explicit `gp` Gold + `mp` Magic totals (which must equal
        the gold cost). Magic is wild and may substitute for Gold as long as at
        least 1 Gold is paid. `tome_payment` says how much of `gp`/`mp` is funded
        by face-up Gold/Magic tomes (flipped face-down here, refreshed at end of
        turn); each tome count must not exceed its matching total.
        """
        from game_setup import GOODS_SLOT_COSTS

        if not self.game.crimson_seas_enabled():
            raise ValueError("Goods are only available in the Crimson Seas preset.")

        # Normalize + validate the selected slots.
        try:
            indices = sorted({int(i) for i in (slot_indices or [])})
        except (TypeError, ValueError):
            raise ValueError("Invalid goods selection.")
        if not indices:
            raise ValueError("Select at least 1 goods to buy.")
        slots = self.game.goods_slots
        for idx in indices:
            if idx < 0 or idx >= len(slots):
                raise ValueError("Invalid goods slot.")
            if not slots[idx]:
                raise ValueError("That goods slot is empty.")

        player = None
        for p in self.game.player_list:
            if p.player_id == player_id:
                player = p
                break
        if not player:
            raise ValueError("Player not found.")

        goods_discount = 1 if self.game._player_has_action_effect_flag(player, "action.portofdrake") else 0
        gold_cost = sum(max(0, int(GOODS_SLOT_COSTS[i]) - goods_discount) for i in indices)
        map_cost = 1
        plan = self._plan_sail_gold_payment(player, gold_cost, gp, mp, tome_payment, "goods")
        if int(getattr(player, "map_score", 0)) < map_cost:
            raise ValueError("Need 1 map to sail.")

        gp, mp = _n(gp), _n(mp)
        bought = [slots[i] for i in indices]
        before = self.game._player_scores_line(player)
        tome_pay = {"gold": plan["tg"], "magic": plan["tm"]}
        redeemed = self.redeem_tomes_to_score(player_id, tome_pay) if (plan["tg"] or plan["tm"]) else None
        player.gold_score = int(player.gold_score) - gp
        player.magic_score = int(player.magic_score) - mp
        player.map_score = int(player.map_score) - map_cost
        player.owned_goods.extend(bought)

        self.game.goods_slots = self._packed_island_slots(
            self.game.goods_slots, self.game.goods_supply, indices)

        after = self.game._player_scores_line(player)
        suffix = self._tome_pay_log_suffix(redeemed) if redeemed else ""
        pay_str = self._sail_pay_log_str(gp, mp)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} sailed to Araby and bought "
            f"{', '.join(bought)} for {pay_str} + 1 map{suffix}; scores {before} -> {after}"
        )

    def buy_tomes(self, player_id, slot_indices, gp=0, mp=0, tome_payment=None):
        """Sail to Nae Aerie and buy Tome tokens in one Sail action.

        Mirrors `buy_goods`: a single Sail (1 Map total) may buy any subset of
        the 3 face-up Tome slots, each at its printed gold price
        (TOME_SLOT_COSTS). Afterwards the board refreshes — unbought tomes
        cascade down to the cheapest slots and fresh tomes fill the top.

        Payment is the explicit `gp` Gold + `mp` Magic totals (which must equal
        the gold cost). Magic is wild and may substitute for Gold as long as at
        least 1 Gold is paid. `tome_payment` says how much of `gp`/`mp` is funded
        by face-up Gold/Magic tomes (redeemed up front, refreshed at end of
        turn); each tome count must not exceed its matching total.
        """
        from game_setup import TOME_SLOT_COSTS

        if not self.game.crimson_seas_enabled():
            raise ValueError("Tomes are only available in the Crimson Seas preset.")

        try:
            indices = sorted({int(i) for i in (slot_indices or [])})
        except (TypeError, ValueError):
            raise ValueError("Invalid tome selection.")
        if not indices:
            raise ValueError("Select at least 1 tome to buy.")
        slots = self.game.tome_slots
        for idx in indices:
            if idx < 0 or idx >= len(slots):
                raise ValueError("Invalid tome slot.")
            if not slots[idx]:
                raise ValueError("That tome slot is empty.")

        player = None
        for p in self.game.player_list:
            if p.player_id == player_id:
                player = p
                break
        if not player:
            raise ValueError("Player not found.")

        tome_discount = 1 if self.game._player_has_action_effect_flag(player, "action.browncoatssanctum") else 0
        gold_cost = sum(max(0, int(TOME_SLOT_COSTS[i]) - tome_discount) for i in indices)
        map_cost = 1
        plan = self._plan_sail_gold_payment(player, gold_cost, gp, mp, tome_payment, "tomes")
        if int(getattr(player, "map_score", 0)) < map_cost:
            raise ValueError("Need 1 map to sail.")

        gp, mp = _n(gp), _n(mp)
        bought = [slots[i] for i in indices]
        before = self.game._player_scores_line(player)
        tome_pay = {"gold": plan["tg"], "magic": plan["tm"]}
        redeemed = self.redeem_tomes_to_score(player_id, tome_pay) if (plan["tg"] or plan["tm"]) else None
        player.gold_score = int(player.gold_score) - gp
        player.magic_score = int(player.magic_score) - mp
        player.map_score = int(player.map_score) - map_cost
        player.owned_tomes.extend(Tome(t) for t in bought)

        self.game.tome_slots = self._packed_island_slots(
            self.game.tome_slots, self.game.tome_supply, indices)

        after = self.game._player_scores_line(player)
        suffix = self._tome_pay_log_suffix(redeemed) if redeemed else ""
        pay_str = self._sail_pay_log_str(gp, mp)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} sailed to Nae Aerie and bought "
            f"{', '.join(bought)} for {pay_str} + 1 map{suffix}; scores {before} -> {after}"
        )

    def rescue_noble(self, player_id, slot_index, resource, tome_payment=None):
        """Sail to Amarynth and rescue 1 Noble from a face-up slot.

        Costs 1 Map plus 9 of a single chosen Resource type (Wild), with an
        additional 1 of that same resource for each Noble already in the
        player's tableau. Only one noble may be rescued per visit. The emptied
        slot is refilled directly from the Noble deck (no cascade).

        `tome_payment` optionally funds part of the cost with face-up Tomes of
        the chosen resource type (redeemed up front, refreshed at end of turn).
        """
        if not self.game.crimson_seas_enabled():
            raise ValueError("Nobles are only available in the Crimson Seas preset.")

        res = (resource or "").strip().lower()
        attr = {"gold": "gold_score", "strength": "strength_score", "magic": "magic_score"}.get(res)
        if not attr:
            raise ValueError('resource must be "gold", "strength", or "magic".')

        try:
            idx = int(slot_index)
        except (TypeError, ValueError):
            raise ValueError("Invalid noble slot.")
        slots = self.game.noble_slots
        if idx < 0 or idx >= len(slots) or not slots[idx]:
            raise ValueError("That noble slot is empty.")

        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")

        owned = len(getattr(player, "owned_nobles", []) or [])
        # Murat Reis (Domain 73) waives the "+Wild" surcharge — the +1 per Noble
        # already in your tableau — so the rescue stays a flat 9 of one resource.
        surcharge = 0 if self.game._player_has_action_effect_flag(player, "action.muratreis") else owned
        cost = 9 + surcharge

        # The rescue is paid in a single resource type, so only tomes of that
        # same type may help (they spend as that resource).
        tome_counts = self._sanitize_tome_payment(tome_payment)
        for k in ("gold", "strength", "magic"):
            if k != res and tome_counts[k]:
                raise ValueError(f"Only {res} tomes can pay for this rescue.")
        tr = tome_counts[res]
        if tr > cost:
            raise ValueError("Too many tomes for this rescue.")
        self._verify_tome_payment_available(player, tome_counts)

        if int(getattr(player, attr, 0) or 0) + tr < cost:
            raise ValueError(f"Need {cost} {res} to rescue this noble.")
        if int(getattr(player, "map_score", 0)) < 1:
            raise ValueError("Need 1 map to sail.")

        noble = slots[idx]
        before = self.game._player_scores_line(player)
        redeemed = self.redeem_tomes_to_score(player_id, {res: tr}) if tr else None
        setattr(player, attr, int(getattr(player, attr)) - cost)
        player.map_score = int(player.map_score) - 1
        try:
            noble.toggle_visibility(True)
        except AttributeError:
            pass
        player.owned_nobles.append(noble)

        # Refill the emptied slot directly from the deck (Nobles don't cascade).
        new_noble = self.game.noble_supply.pop() if self.game.noble_supply else None
        if new_noble is not None:
            try:
                new_noble.toggle_visibility(True)
                new_noble.toggle_accessibility(True)
            except AttributeError:
                pass
        self.game.noble_slots[idx] = new_noble

        after = self.game._player_scores_line(player)
        suffix = self._tome_pay_log_suffix(redeemed) if redeemed else ""
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} sailed to Amarynth and rescued "
            f"\"{getattr(noble, 'name', 'Noble')}\" for {cost} {res} + 1 map{suffix}; scores {before} -> {after}"
        )

    def sail_exekratys(self, player_id, resource):
        """Sail to Exekratys and drain ALL of one resource type from the pool.

        Costs 1 Map (every Sail action does). The sailing player chooses one
        resource type and takes every token of that type currently in the
        Exekratys pool, emptying it for that resource.
        """
        if not self.game.crimson_seas_enabled():
            raise ValueError("Exekratys is only available in the Crimson Seas preset.")

        res = (resource or "").strip().lower()
        attr = {"gold": "gold_score", "strength": "strength_score", "magic": "magic_score"}.get(res)
        if not attr:
            raise ValueError('resource must be "gold", "strength", or "magic".')

        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        if int(getattr(player, "map_score", 0)) < 1:
            raise ValueError("Need 1 map to sail.")

        amount = int(self.game.exekratys_resources.get(res, 0) or 0)
        before = self.game._player_scores_line(player)
        player.map_score = int(player.map_score) - 1
        setattr(player, attr, int(getattr(player, attr, 0) or 0) + amount)
        self.game.exekratys_resources[res] = 0
        after = self.game._player_scores_line(player)
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} sailed to Exekratys and took {amount} {res} "
            f"for 1 map; scores {before} -> {after}"
        )

    @staticmethod
    def _packed_island_slots(slots, supply, taken_indices):
        """Refresh an Araby/Nae Aerie slot row after some tokens are taken.

        Unbought tokens keep their top-to-bottom order and pack into the bottom
        (cheapest) slots; the emptied top slots are filled with fresh draws from
        `supply` (mutated in place via pop). Returns the new slot list.
        """
        taken = set(taken_indices)
        kept = [slots[i] for i in range(len(slots)) if i not in taken and slots[i]]
        refilled = [supply.pop() if supply else None
                    for _ in range(len(slots) - len(kept))]
        return refilled + kept

    def take_tome_from_slot(self, player_id, slot_index):
        """Take 1 face-up Tome for free (e.g. a 'gain 1 Tome' reward), then refresh.

        Unlike `buy_tomes` this costs no gold and no map — the player simply
        takes the chosen face-up tome into their tableau and the Nae Aerie row
        refreshes (cascade down + redraw) like any other take.
        """
        slots = self.game.tome_slots
        try:
            idx = int(slot_index)
        except (TypeError, ValueError):
            return False
        if idx < 0 or idx >= len(slots) or not slots[idx]:
            return False
        player = self.game._player_by_id(player_id)
        if not player:
            return False
        player.owned_tomes.append(Tome(slots[idx]))
        self.game.tome_slots = self._packed_island_slots(
            self.game.tome_slots, self.game.tome_supply, [idx])
        return True

    def take_goods_from_slot(self, player_id, slot_index):
        """Take 1 face-up Goods for free (e.g. a 'take 1 Goods' reward), then refresh.

        Unlike `buy_goods` this costs no gold and no map — the player takes the
        chosen face-up goods into their tableau and the Araby row refreshes
        (cascade down + redraw) like any other take.
        """
        slots = self.game.goods_slots
        try:
            idx = int(slot_index)
        except (TypeError, ValueError):
            return False
        if idx < 0 or idx >= len(slots) or not slots[idx]:
            return False
        player = self.game._player_by_id(player_id)
        if not player:
            return False
        goods = slots[idx]
        player.owned_goods.append(goods)
        self.game.goods_slots = self._packed_island_slots(
            self.game.goods_slots, self.game.goods_supply, [idx])
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} gained Goods \"{goods}\" (free reward)."
        )
        return True

    def take_noble_from_slot(self, player_id, slot_index):
        """Take 1 face-up Noble for free (e.g. a 'gain 1 Noble' reward), then refill.

        Unlike `rescue_noble` this costs no resources and no map — the player
        takes the chosen face-up noble into their tableau and the emptied
        Amarynth slot refills directly from the Noble deck (no cascade).
        """
        slots = self.game.noble_slots
        try:
            idx = int(slot_index)
        except (TypeError, ValueError):
            return False
        if idx < 0 or idx >= len(slots) or not slots[idx]:
            return False
        player = self.game._player_by_id(player_id)
        if not player:
            return False
        noble = slots[idx]
        try:
            noble.toggle_visibility(True)
        except AttributeError:
            pass
        player.owned_nobles.append(noble)
        new_noble = self.game.noble_supply.pop() if self.game.noble_supply else None
        if new_noble is not None:
            try:
                new_noble.toggle_visibility(True)
                new_noble.toggle_accessibility(True)
            except AttributeError:
                pass
        self.game.noble_slots[idx] = new_noble
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} gained Noble "
            f"\"{getattr(noble, 'name', 'Noble')}\" (free reward)."
        )
        return True

    # ── Tome payment (Crimson Seas) ─────────────────────────────────────────
    # A face-up Tome can be flipped face-down to pay 1 of its resource type
    # (gold/strength/magic) for a market/sail action, refreshing at end of turn.
    # Rather than thread a tome split through every cost validator, we convert
    # the chosen tomes into ordinary treasury resources up front
    # (`redeem_tomes_to_score`): flip them face-down and credit their value to
    # the player's score, so the existing unchanged payment paths simply spend
    # them. The only invariant is that every redeemed unit is actually consumed
    # by the action (callers redeem at most as much per type as the action
    # spends); otherwise the leftover credit would be free resources.

    @staticmethod
    def _face_up_tome_counts(player):
        counts = {"gold": 0, "strength": 0, "magic": 0}
        for t in getattr(player, "owned_tomes", None) or []:
            if getattr(t, "is_flipped", False):
                continue
            ttype = getattr(t, "tome_type", None)
            if ttype in counts:
                counts[ttype] += 1
        return counts

    @staticmethod
    def _sanitize_tome_payment(tome_payment):
        tp = tome_payment or {}
        out = {}
        for k in ("gold", "strength", "magic"):
            try:
                v = int(tp.get(k, 0) or 0)
            except (TypeError, ValueError):
                v = 0
            out[k] = max(0, v)
        return out

    def _verify_tome_payment_available(self, player, counts):
        avail = self._face_up_tome_counts(player)
        for k in ("gold", "strength", "magic"):
            if counts[k] > avail[k]:
                raise ValueError(
                    f"Not enough face-up {k} tomes (need {counts[k]}, have {avail[k]})."
                )

    def _spend_tomes(self, player, counts):
        """Flip `counts[type]` face-up tomes of each type face-down. Assumes
        `_verify_tome_payment_available` already passed."""
        for k in ("gold", "strength", "magic"):
            need = int(counts.get(k, 0) or 0)
            if need <= 0:
                continue
            for t in getattr(player, "owned_tomes", None) or []:
                if need <= 0:
                    break
                if getattr(t, "tome_type", None) == k and not getattr(t, "is_flipped", False):
                    t.is_flipped = True
                    need -= 1

    def _unspend_tomes(self, player, counts):
        """Inverse of `_spend_tomes`: flip `counts[type]` face-down tomes back
        face-up (used to refund a redeem when an action then fails)."""
        for k in ("gold", "strength", "magic"):
            need = int(counts.get(k, 0) or 0)
            if need <= 0:
                continue
            for t in getattr(player, "owned_tomes", None) or []:
                if need <= 0:
                    break
                if getattr(t, "tome_type", None) == k and getattr(t, "is_flipped", False):
                    t.is_flipped = False
                    need -= 1

    @staticmethod
    def _tome_pay_log_suffix(counts):
        parts = []
        for k, short in (("gold", "g"), ("strength", "s"), ("magic", "m")):
            n = int(counts.get(k, 0) or 0)
            if n:
                parts.append(f"{n}{short}")
        return f" [tomes: {' '.join(parts)}]" if parts else ""

    def redeem_tomes_to_score(self, player_id, tome_payment):
        """Convert chosen face-up tomes into ordinary treasury resources so the
        normal (unchanged) payment paths can spend them: flip them face-down and
        credit their value to the player's score. Returns the applied
        {gold,strength,magic} counts (pass them to `refund_tomes_from_score` if
        the action then fails). Raises ValueError if the player lacks that many
        face-up tomes.

        Callers MUST ensure the action will spend at least the redeemed amount of
        each resource type — leftover credit would become free resources.
        """
        counts = self._sanitize_tome_payment(tome_payment)
        if not any(counts.values()):
            return counts
        player = self.game._player_by_id(player_id)
        if not player:
            raise ValueError("Player not found.")
        self._verify_tome_payment_available(player, counts)
        self._spend_tomes(player, counts)
        player.gold_score = int(player.gold_score) + counts["gold"]
        player.strength_score = int(player.strength_score) + counts["strength"]
        player.magic_score = int(player.magic_score) + counts["magic"]
        self.game._log_game_event(
            f"{self.game._player_label(player_id)} flipped tomes to spend"
            f"{self._tome_pay_log_suffix(counts)}."
        )
        return counts

    def refund_tomes_from_score(self, player_id, counts):
        """Undo `redeem_tomes_to_score` after a failed action: flip the tomes
        back face-up and remove the credited resources from the score."""
        counts = self._sanitize_tome_payment(counts)
        if not any(counts.values()):
            return
        player = self.game._player_by_id(player_id)
        if not player:
            return
        self._unspend_tomes(player, counts)
        player.gold_score = int(player.gold_score) - counts["gold"]
        player.strength_score = int(player.strength_score) - counts["strength"]
        player.magic_score = int(player.magic_score) - counts["magic"]

    def take_resource(self, player_id, resource):
        """
        Spend a standard action to gain +1 gold, strength, magic, or map (player's choice).
        """
        choice = (resource or "").strip().lower()
        if choice not in ("gold", "strength", "magic", "map"):
            raise ValueError('resource must be "gold", "strength", "magic", or "map".')
        if choice == "map" and not self.game.crimson_seas_enabled():
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

