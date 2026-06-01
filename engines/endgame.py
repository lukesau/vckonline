"""EndgameEngine -- composed sub-engine of Game.

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


class EndgameEngine:
    def __init__(self, game):
        self.game = game

    def _check_end_game_condition(self):
        """Returns a reason string if any end condition is met, else None."""
        from cards import Exhausted

        def _depleted(stack):
            """A stack counts as depleted if it is empty or holds only a
            non-purchasable placeholder (Event or Exhausted token)."""
            if not stack:
                return True
            top = stack[-1]
            return isinstance(top, (Event, Exhausted))

        if all(_depleted(s) for s in self.game.monster_grid):
            return "all monsters slain"
        if all(_depleted(s) for s in self.game.domain_grid):
            return "all domains built"
        if int(self.game.exhausted_count) >= len(self.game.player_list) * 2:
            return "exhausted stacks filled"
        return None

    def _build_final_result(self, scores):
        """Summarize win / tie-break / true-tie outcome for clients and logs."""
        if not scores:
            return None
        top_vp = int(scores[0]["total_vp"])
        vp_tied = [s for s in scores if int(s["total_vp"]) == top_vp]
        if len(vp_tied) == 1:
            w = vp_tied[0]
            return {
                "kind": "win",
                "headline": f"{w['name']} wins!",
                "detail": None,
                "winner_player_ids": [w["player_id"]],
            }
        min_tableau = min(int(s["tableau_size"]) for s in vp_tied)
        winners = [s for s in vp_tied if int(s["tableau_size"]) == min_tableau]
        if len(winners) == 1:
            w = winners[0]
            losers = [s for s in vp_tied if s["player_id"] != w["player_id"]]
            loser_bits = ", ".join(
                f"{s['name']} ({int(s['tableau_size'])} cards)" for s in losers
            )
            return {
                "kind": "tiebreak",
                "headline": f"{w['name']} wins on tie-break!",
                "detail": (
                    f"Tied at {top_vp} VP; {w['name']} had the smaller tableau "
                    f"({int(w['tableau_size'])} cards vs {loser_bits})."
                ),
                "winner_player_ids": [w["player_id"]],
            }
        names = ", ".join(s["name"] for s in winners)
        tableau_n = int(winners[0]["tableau_size"])
        return {
            "kind": "tie",
            "headline": "Tie game!",
            "detail": (
                f"{names} tied at {top_vp} VP with {tableau_n} tableau cards each."
            ),
            "winner_player_ids": [s["player_id"] for s in winners],
        }

    def _calculate_final_scores(self):
        """Compute final VP for each player including Duke multipliers. Returns ranked list."""
        self.game.unflip_all_citizens_for_final_scoring()
        scores = []
        for player in self.game.player_list:
            duke_vp = 0
            duke_summary = None
            duke_vp_breakdown = []

            if player.owned_dukes:
                duke = player.owned_dukes[0]
                roles = player.calc_roles()
                monster_attrs = self.game.owned_monster_attributes(player.player_id)

                def _res(score, divisor):
                    d = int(divisor or 0)
                    return int(score) // d if d > 0 else 0

                def _cnt(count, multiplier):
                    return int(count) * int(multiplier or 0)

                def _line(label, vp, detail):
                    v = int(vp)
                    if v:
                        duke_vp_breakdown.append({"label": label, "vp": v, "detail": detail})

                gsc = int(player.gold_score)
                gdiv = int(duke.gold_multiplier or 0)
                gvp = _res(player.gold_score, duke.gold_multiplier)
                _line("Gold", gvp, f"{gsc} gold ÷ {gdiv}" if gdiv > 0 else None)

                ssc = int(player.strength_score)
                sdiv = int(duke.strength_multiplier or 0)
                svp = _res(player.strength_score, duke.strength_multiplier)
                _line("Strength", svp, f"{ssc} strength ÷ {sdiv}" if sdiv > 0 else None)

                msc = int(player.magic_score)
                mdiv = int(duke.magic_multiplier or 0)
                mvp = _res(player.magic_score, duke.magic_multiplier)
                _line("Magic", mvp, f"{msc} magic ÷ {mdiv}" if mdiv > 0 else None)

                shc = int(roles["shadow_count"])
                shm = int(duke.shadow_multiplier or 0)
                shvp = _cnt(shc, duke.shadow_multiplier)
                _line("Shadow role", shvp, f"{shc} × {shm}" if shm else None)

                hoc = int(roles["holy_count"])
                hom = int(duke.holy_multiplier or 0)
                hovp = _cnt(hoc, duke.holy_multiplier)
                _line("Holy role", hovp, f"{hoc} × {hom}" if hom else None)

                soc = int(roles["soldier_count"])
                som = int(duke.soldier_multiplier or 0)
                sovp = _cnt(soc, duke.soldier_multiplier)
                _line("Soldier role", sovp, f"{soc} × {som}" if som else None)

                woc = int(roles["worker_count"])
                wom = int(duke.worker_multiplier or 0)
                wovp = _cnt(woc, duke.worker_multiplier)
                _line("Worker role", wovp, f"{woc} × {wom}" if wom else None)

                nmon = len(player.owned_monsters)
                mm = int(duke.monster_multiplier or 0)
                mmonvp = _cnt(nmon, duke.monster_multiplier)
                _line("Monsters", mmonvp, f"{nmon} × {mm}" if mm else None)

                ncit = len(player.owned_citizens)
                cm = int(duke.citizen_multiplier or 0)
                citvp = _cnt(ncit, duke.citizen_multiplier)
                _line("Citizens", citvp, f"{ncit} × {cm}" if cm else None)

                ndom = len(player.owned_domains)
                dm = int(duke.domain_multiplier or 0)
                domvp = _cnt(ndom, duke.domain_multiplier)
                _line("Domains", domvp, f"{ndom} × {dm}" if dm else None)

                nb = int(monster_attrs.get("Boss", 0))
                bm = int(duke.boss_multiplier or 0)
                bvp = _cnt(nb, duke.boss_multiplier)
                _line("Boss monsters", bvp, f"{nb} × {bm}" if bm else None)

                nmin = int(monster_attrs.get("Minion", 0))
                minm = int(duke.minion_multiplier or 0)
                minvp = _cnt(nmin, duke.minion_multiplier)
                _line("Minion monsters", minvp, f"{nmin} × {minm}" if minm else None)

                nbe = int(monster_attrs.get("Beast", 0))
                bem = int(duke.beast_multiplier or 0)
                bevp = _cnt(nbe, duke.beast_multiplier)
                _line("Beast monsters", bevp, f"{nbe} × {bem}" if bem else None)

                nti = int(monster_attrs.get("Titan", 0))
                tim = int(duke.titan_multiplier or 0)
                tivp = _cnt(nti, duke.titan_multiplier)
                _line("Titan monsters", tivp, f"{nti} × {tim}" if tim else None)

                duke_vp = (
                    gvp + svp + mvp + shvp + hovp + sovp + wovp
                    + mmonvp + citvp + domvp + bvp + minvp + bevp + tivp
                )
                duke_summary = {
                    "duke_id": duke.duke_id,
                    "name": duke.name or "Duke",
                    "card": duke.to_dict(),
                }

            total_vp = int(player.victory_score) + duke_vp
            tableau_size = (
                len(player.owned_starters)
                + len(player.owned_citizens)
                + len(player.owned_domains)
                + len(player.owned_monsters)
                + len(player.owned_dukes)
            )
            scores.append({
                "player_id": player.player_id,
                "name": player.name,
                "base_vp": int(player.victory_score),
                "duke_vp": duke_vp,
                "duke": duke_summary,
                "duke_vp_breakdown": duke_vp_breakdown,
                "total_vp": total_vp,
                "tableau_size": tableau_size,
            })
        scores.sort(key=lambda s: (-s["total_vp"], s["tableau_size"]))
        top_vp = int(scores[0]["total_vp"]) if scores else None
        for rank, s in enumerate(scores):
            s["rank"] = rank + 1
            s["tied_on_vp"] = top_vp is not None and int(s["total_vp"]) == top_vp
        return scores

    def _finalize_game(self):
        """Compute final scores, set phase to game_over, and log the result."""
        self.game.final_scores = self._calculate_final_scores()
        self.game.final_result = self._build_final_result(self.game.final_scores)
        self.game.phase = "game_over"
        if self.game.final_scores:
            for s in self.game.final_scores:
                place = {1: "1st", 2: "2nd", 3: "3rd"}.get(s["rank"], f"{s['rank']}th")
                self.game._log_game_event(
                    f"{place}: {s['name']} — {s['total_vp']} VP "
                    f"({s['base_vp']} base + {s['duke_vp']} Duke)."
                )
            fr = self.game.final_result or {}
            headline = fr.get("headline") or f"Game over! {self.game.final_scores[0]['name']} wins!"
            self.game._log_game_event(headline)
            detail = fr.get("detail")
            if detail:
                self.game._log_game_event(detail)

    def end_check(self):
        if self.game.exhausted_count <= (len(self.game.player_list) * 2):
            return False

    def prompt(self):
        return
