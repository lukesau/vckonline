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

        # Crimson Seas adds three end conditions: the game ends if a Goods,
        # Tome, or Noble slot row needed replenishing but the supply ran out, so
        # the three face-up slots can no longer all be filled. After a take, an
        # unfillable slot is left empty (None), so a falsy entry in a slot row
        # means a required replenish couldn't complete. These slot lists are
        # empty outside Crimson Seas, so this is a no-op in every other mode.
        if self.game.crimson_seas_enabled():
            def _cannot_refill(slots, slot_count):
                return sum(1 for s in (slots or []) if s) < slot_count

            from game_setup import (
                GOODS_SLOT_COUNT,
                TOME_SLOT_COUNT,
                NOBLE_SLOT_COUNT,
            )
            if _cannot_refill(self.game.goods_slots, GOODS_SLOT_COUNT):
                return "goods supply exhausted"
            if _cannot_refill(self.game.tome_slots, TOME_SLOT_COUNT):
                return "tome supply exhausted"
            if _cannot_refill(self.game.noble_slots, NOBLE_SLOT_COUNT):
                return "noble supply exhausted"
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
        max_tableau = max(int(s["tableau_size"]) for s in vp_tied)
        winners = [s for s in vp_tied if int(s["tableau_size"]) == max_tableau]
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
                    f"Tied at {top_vp} VP; {w['name']} had the larger tableau "
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

    def _compute_duke_breakdown(self, player, duke, roles=None, monster_attrs=None):
        """Single source of truth for "how many VP does this duke score for this player".

        Returns (duke_vp_total, breakdown_lines) where breakdown_lines is a list of
        {label, vp, detail} dicts (only non-zero lines are included). Reused by both
        the end-of-game tally (`_calculate_final_scores`) and the real-time
        projection surfaced in the duke inspect modal mid-game.
        """
        if roles is None:
            roles = player.calc_roles()
        if monster_attrs is None:
            monster_attrs = self.game.owned_monster_attributes(player.player_id)

        lines = []

        def _res(score, divisor):
            d = int(divisor or 0)
            return int(score) // d if d > 0 else 0

        def _cnt(count, multiplier):
            return int(count) * int(multiplier or 0)

        def _line(label, vp, detail):
            v = int(vp)
            if v:
                lines.append({"label": label, "vp": v, "detail": detail})

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
        return duke_vp, lines

    def compute_duke_projection_for_player(self, player_id):
        """Return a real-time projection of a player's end-game VP, or None
        if the player doesn't yet have a duke. Surfaced via the per-player
        serializer so the duke inspect modal can show a live tally."""
        player = None
        for p in self.game.player_list:
            if getattr(p, "player_id", None) == player_id:
                player = p
                break
        if player is None or not player.owned_dukes:
            return None
        duke = player.owned_dukes[0]
        duke_vp, breakdown = self._compute_duke_breakdown(player, duke)
        return {
            "base_vp": int(player.victory_score),
            "duke_vp": int(duke_vp),
            "total_vp": int(player.victory_score) + int(duke_vp),
            "duke_vp_breakdown": breakdown,
        }

    def compute_duke_vp_table_for_player(self, player_id):
        """Project, for EVERY duke in the public catalog, the end-game VP this
        player would score with that duke given their current tableau.

        Returns a list (sorted by total VP, descending) of
        {duke_id, name, base_vp, duke_vp, total_vp, duke_vp_breakdown}. Used by
        the duke inspect modal: when looking at an opponent's hidden duke we can
        list each catalog duke's projected VP without revealing which one they
        actually own (every duke is projected identically). Returns [] when no
        catalog is available (e.g. legacy saves)."""
        player = None
        for p in self.game.player_list:
            if getattr(p, "player_id", None) == player_id:
                player = p
                break
        catalog = list(getattr(self.game, "all_dukes", None) or [])
        if player is None or not catalog:
            return []
        # Roles / monster attributes only depend on the player, so compute them
        # once and reuse across every duke projection.
        roles = player.calc_roles()
        monster_attrs = self.game.owned_monster_attributes(player.player_id)
        base_vp = int(player.victory_score)
        table = []
        for duke in catalog:
            duke_vp, breakdown = self._compute_duke_breakdown(
                player, duke, roles=roles, monster_attrs=monster_attrs
            )
            table.append({
                "duke_id": duke.duke_id,
                "name": duke.name or "Duke",
                "base_vp": base_vp,
                "duke_vp": int(duke_vp),
                "total_vp": base_vp + int(duke_vp),
                "duke_vp_breakdown": breakdown,
            })
        table.sort(key=lambda e: (-e["total_vp"], str(e["name"])))
        return table

    # Goods VP by how many of a single type you hold (Araby). Index == count;
    # tokens cap at 6 per type so 6 is the top tier. Scored in four independent
    # "waves", one per Goods type (see `_compute_crimson_scoring`).
    GOODS_VP_BY_COUNT = (0, 2, 4, 7, 12, 18, 25)

    @classmethod
    def _goods_tier_vp(cls, count):
        c = max(0, int(count or 0))
        if c >= len(cls.GOODS_VP_BY_COUNT):
            c = len(cls.GOODS_VP_BY_COUNT) - 1
        return cls.GOODS_VP_BY_COUNT[c]

    def _noble_special_payout_vp(self, player, spec):
        """Resolve a Noble's `special_duke_payout` scoring string to VP.

        Supported grammars (Crimson Seas Nobles):
          floor_div <gold|strength|magic> <divisor> <vp>
              -> (resource // divisor) * vp   (e.g. Mikal: 1 VP per 3 gold)
          wild_choose <divisor> <vp>
              -> choose your single best resource type; (best // divisor) * vp
                 (e.g. Dray: 1 VP per 2 of one chosen resource)
        Returns (vp, detail) where detail is a human-readable breakdown string,
        or (0, None) when the spec is empty/unrecognized.
        """
        toks = (spec or "").strip().lower().split()
        if not toks:
            return 0, None
        verb = toks[0]
        if verb == "floor_div" and len(toks) >= 4:
            res = toks[1]
            try:
                divisor, vp = int(toks[2]), int(toks[3])
            except ValueError:
                return 0, None
            attr = {"gold": "gold_score", "strength": "strength_score", "magic": "magic_score"}.get(res)
            if attr and divisor > 0:
                amt = int(getattr(player, attr, 0) or 0)
                return (amt // divisor) * vp, f"{amt} {res} \u00f7 {divisor} \u00d7 {vp}"
        if verb == "wild_choose" and len(toks) >= 3:
            try:
                divisor, vp = int(toks[1]), int(toks[2])
            except ValueError:
                return 0, None
            if divisor > 0:
                pool = {
                    "gold": int(player.gold_score or 0),
                    "strength": int(player.strength_score or 0),
                    "magic": int(player.magic_score or 0),
                }
                best_res = max(pool, key=lambda k: pool[k])
                best = pool[best_res]
                return (best // divisor) * vp, f"{best} {best_res} \u00f7 {divisor} \u00d7 {vp}"
        return 0, None

    def _compute_noble_breakdown(self, player, noble, roles, monster_attrs):
        """How many VP a single owned Noble scores, plus a detail string.

        A Noble scores like a Duke: a single multiplier or a `special_duke_payout`.
        Role-icon multipliers count icons across Citizens + Domains + Nobles
        (already folded into `roles` by `Player.calc_roles`).
        """
        components = []  # (vp, description)

        for attr, key, label in (
            ("shadow_multiplier", "shadow_count", "Shadow"),
            ("holy_multiplier", "holy_count", "Holy"),
            ("soldier_multiplier", "soldier_count", "Soldier"),
            ("worker_multiplier", "worker_count", "Worker"),
        ):
            m = int(getattr(noble, attr, 0) or 0)
            if m:
                cnt = int(roles[key])
                components.append((cnt * m, f"{cnt} {label} icon{'s' if cnt != 1 else ''} \u00d7 {m}"))

        for attr, cnt, label in (
            ("monster_multiplier", roles["owned_monsters"], "monsters"),
            ("citizen_multiplier", roles["owned_citizens"], "citizens"),
            ("domain_multiplier", roles["owned_domains"], "domains"),
        ):
            m = int(getattr(noble, attr, 0) or 0)
            if m:
                components.append((int(cnt) * m, f"{int(cnt)} {label} \u00d7 {m}"))

        for attr, mkey, label in (
            ("boss_multiplier", "Boss", "Bosses"),
            ("minion_multiplier", "Minion", "Minions"),
            ("beast_multiplier", "Beast", "Beasts"),
            ("titan_multiplier", "Titan", "Titans"),
        ):
            m = int(getattr(noble, attr, 0) or 0)
            if m:
                cnt = int(monster_attrs.get(mkey, 0))
                components.append((cnt * m, f"{cnt} {label} slain \u00d7 {m}"))

        gm = int(getattr(noble, "goods_multiplier", 0) or 0)
        if gm:
            ng = len(getattr(player, "owned_goods", []) or [])
            components.append((ng * gm, f"{ng} goods \u00d7 {gm}"))

        if getattr(noble, "has_special_duke_payout", 0) and getattr(noble, "special_duke_payout", ""):
            sp_vp, sp_desc = self._noble_special_payout_vp(player, noble.special_duke_payout)
            if sp_desc:
                components.append((sp_vp, sp_desc))

        total = sum(vp for vp, _ in components)
        detail = "; ".join(d for _, d in components) if components else None
        return total, detail

    def _compute_crimson_scoring(self, player, roles, monster_attrs):
        """Crimson Seas end-game scoring: Tomes, Goods, and Nobles.

        Returns (tome_vp, goods_vp, noble_vp, breakdown_lines) where each line is
        a {label, vp, detail} dict for the scoring-details UI.
        """
        from game_setup import GOODS_TYPES

        lines = []

        ntome = len(getattr(player, "owned_tomes", []) or [])
        tome_vp = ntome  # 1 VP per Tome
        if ntome:
            lines.append({
                "label": "Tomes",
                "vp": tome_vp,
                "detail": f"{ntome} tome{'s' if ntome != 1 else ''} \u00d7 1",
            })

        goods = [str(g).strip().lower() for g in (getattr(player, "owned_goods", []) or [])]
        goods_vp = 0
        for gtype in GOODS_TYPES:
            cnt = sum(1 for g in goods if g == gtype)
            if cnt:
                v = self._goods_tier_vp(cnt)
                goods_vp += v
                lines.append({
                    "label": f"Goods: {gtype.capitalize()}",
                    "vp": v,
                    "detail": f"{cnt} {gtype} = {v} VP",
                })

        noble_vp = 0
        for noble in (getattr(player, "owned_nobles", []) or []):
            v, detail = self._compute_noble_breakdown(player, noble, roles, monster_attrs)
            noble_vp += v
            lines.append({
                "label": f"Noble: {getattr(noble, 'name', 'Noble')}",
                "vp": v,
                "detail": detail,
            })

        return tome_vp, goods_vp, noble_vp, lines

    def _calculate_final_scores(self):
        """Compute final VP for each player including Duke multipliers. Returns ranked list."""
        self.game.unflip_all_citizens_for_final_scoring()
        crimson = self.game.crimson_seas_enabled()
        scores = []
        for player in self.game.player_list:
            roles = player.calc_roles()
            monster_attrs = self.game.owned_monster_attributes(player.player_id)
            duke_vp = 0
            duke_summary = None
            duke_vp_breakdown = []

            if player.owned_dukes:
                duke = player.owned_dukes[0]
                duke_vp, duke_vp_breakdown = self._compute_duke_breakdown(
                    player, duke, roles=roles, monster_attrs=monster_attrs
                )
                duke_summary = {
                    "duke_id": duke.duke_id,
                    "name": duke.name or "Duke",
                    "card": duke.to_dict(),
                }

            tome_vp = goods_vp = noble_vp = 0
            crimson_vp_breakdown = []
            if crimson:
                tome_vp, goods_vp, noble_vp, crimson_vp_breakdown = \
                    self._compute_crimson_scoring(player, roles, monster_attrs)

            total_vp = int(player.victory_score) + duke_vp + tome_vp + goods_vp + noble_vp
            tableau_size = (
                len(player.owned_starters)
                + len(player.owned_citizens)
                + len(player.owned_domains)
                + len(player.owned_monsters)
                + len(player.owned_dukes)
                + len(getattr(player, "owned_nobles", []) or [])
            )
            scores.append({
                "player_id": player.player_id,
                "name": player.name,
                "base_vp": int(player.victory_score),
                "duke_vp": duke_vp,
                "duke": duke_summary,
                "duke_vp_breakdown": duke_vp_breakdown,
                "tome_vp": tome_vp,
                "goods_vp": goods_vp,
                "noble_vp": noble_vp,
                "crimson_vp_breakdown": crimson_vp_breakdown,
                "total_vp": total_vp,
                "tableau_size": tableau_size,
            })
        scores.sort(key=lambda s: (-s["total_vp"], -s["tableau_size"]))
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
                parts = [f"{s['base_vp']} base"]
                if int(s.get("duke_vp", 0) or 0):
                    parts.append(f"{s['duke_vp']} Duke")
                if int(s.get("tome_vp", 0) or 0):
                    parts.append(f"{s['tome_vp']} Tomes")
                if int(s.get("goods_vp", 0) or 0):
                    parts.append(f"{s['goods_vp']} Goods")
                if int(s.get("noble_vp", 0) or 0):
                    parts.append(f"{s['noble_vp']} Nobles")
                self.game._log_game_event(
                    f"{place}: {s['name']} — {s['total_vp']} VP "
                    f"({' + '.join(parts)})."
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
