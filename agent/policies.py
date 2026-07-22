"""Decision policies: biased-random baseline and the greedy VP-maximizing optimizer.

GreedyPolicy scores every candidate move in end-game VP-equivalents:

    value = immediate VP gained
          + duke-scoring delta (role icons, per-card and per-monster-type multipliers)
          - resources spent * that player's duke resource rate
          + resources gained * rate
          + expected future harvest income of an acquired citizen
            (P(activation per roll) * payout * expected remaining rolls, at rate)

The resource->VP rate is the player's own duke's end-game conversion
(1 VP per `gold_multiplier` gold etc.), i.e. the guaranteed floor value of a
hoarded resource — per-project decision, see vcko-agent-project notes.
"""

import random

RES_KEYS = {"g": "gold", "s": "strength", "m": "magic"}

# Probability a citizen with this roll_match value activates on one roll.
# 1-6 match individual dice (expected activation count 2/6, doubles fire twice);
# 7-12 match the dice sum.
_SUM_P = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 7: 6, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}


def _match_rate(roll_match):
    try:
        v = int(roll_match)
    except (TypeError, ValueError):
        return 0.0
    if 1 <= v <= 6:
        return 2.0 / 6.0
    if 7 <= v <= 12:
        return _SUM_P[v] / 36.0
    return 0.0


class GreedyConfig:
    expected_total_turns = 32   # observed biased-random games run 27-45 turns
    min_remaining_turns = 3     # never value future income at zero mid-game
    unparsed_effect_value = 1.0 # VP-equivalent guess for effects we can't parse
    # Liquidity premiums: most dukes convert g/s/m at the same end-game rate,
    # which would leave take_resource choices tied. But magic is a wild for
    # both gold costs (hire/build) and strength costs (slay), and gold pays
    # for the most things outright, so a marginal magic > gold > strength.
    magic_flex_premium = 1.12
    gold_flex_premium = 1.05
    # assumed end-game tableau for duke selection at game start
    est_citizens = 8
    est_domains = 5
    est_monsters = 6
    est_role_each = 3
    est_monster_type_each = 1.5
    est_resources_each = 25


class RandomPolicy:
    """Uniform-random with a bias toward stack-depleting moves (see play_random)."""

    name = "random"

    def __init__(self, builder_bias=0.75):
        self.builder_bias = builder_bias

    def choose(self, game, view, player_id, moves):
        builders = [
            m for m in moves
            if m.get("action_type") in ("hire_citizen", "build_domain", "slay_monster")
        ]
        pool = builders if builders and random.random() < self.builder_bias else moves
        return random.choice(pool)


class GreedyPolicy:
    name = "greedy"

    def __init__(self, config=None):
        self.cfg = config or GreedyConfig()
        self.last_decision = None

    # ---- resource rates ------------------------------------------------

    def _rates(self, player):
        duke = (getattr(player, "owned_dukes", None) or [None])[0]

        def rate(mult):
            m = int(getattr(duke, mult, 0) or 0) if duke is not None else 0
            return 1.0 / m if m > 0 else 0.25

        return {
            "g": rate("gold_multiplier") * self.cfg.gold_flex_premium,
            "s": rate("strength_multiplier"),
            "m": rate("magic_multiplier") * self.cfg.magic_flex_premium,
            "v": 1.0,
            "p": 0.3,  # maps (Crimson Seas); irrelevant in base1
        }

    def _mult(self, player, attr):
        duke = (getattr(player, "owned_dukes", None) or [None])[0]
        return int(getattr(duke, attr, 0) or 0) if duke is not None else 0

    # ---- effect-string rough valuation ---------------------------------

    def _pairs_value(self, tokens, rates, mode="sum"):
        """Value alternating '<res> <n>' tokens. mode: sum | max | min."""
        values = []
        i = 0
        while i + 1 < len(tokens) + 1 and i < len(tokens):
            res = tokens[i].lower()
            amount = 0
            if i + 1 < len(tokens):
                try:
                    amount = int(tokens[i + 1])
                except ValueError:
                    break
            if res == "wild":
                r = max(rates["g"], rates["s"], rates["m"]) if mode != "min" else min(
                    rates["g"], rates["s"], rates["m"]
                )
            else:
                r = rates.get(res)
            if r is None:
                break
            values.append(r * amount)
            i += 2
        if not values:
            return 0.0
        if mode == "max":
            return max(values)
        if mode == "min":
            return min(values)
        return sum(values)

    def _payout_value(self, spec, rates, player=None):
        """VP-equivalent of one special-payout activation. Rough by design."""
        spec = (spec or "").strip()
        if not spec:
            return 0.0
        total = 0.0
        for part in spec.split("+"):
            tokens = part.strip().split()
            if not tokens:
                continue
            verb = tokens[0].lower()
            if verb == "choose":
                total += self._pairs_value(tokens[1:], rates, mode="max")
            elif verb == "exchange":
                cost = self._pairs_value(tokens[1:3], rates, mode="min")
                gain = self._pairs_value(tokens[3:], rates, mode="max")
                total += max(gain - cost, 0.0)
            elif verb == "steal":
                total += self._pairs_value(tokens[1:], rates, mode="max")
            elif verb == "count":
                # count owned_<role|kind>[_name X] <res> <n>
                count = 2.0
                if player is not None and len(tokens) >= 2:
                    what = tokens[1]
                    if what.startswith("owned_") and hasattr(player, "calc_roles"):
                        roles = player.calc_roles()
                        key = what.replace("owned_", "") + "_count"
                        if key in roles:
                            count = roles[key]
                        elif what == "owned_citizen":
                            count = len(player.owned_citizens)
                        elif what == "owned_domains":
                            count = len(player.owned_domains)
                total += count * self._pairs_value(tokens[-2:], rates, mode="sum")
            elif verb in rates:
                total += self._pairs_value(tokens, rates, mode="sum")
            else:
                total += self.cfg.unparsed_effect_value
        return total

    # ---- future income model -------------------------------------------

    def _remaining_rolls(self, game):
        remaining = self.cfg.expected_total_turns - int(game.turn_number or 0)
        return max(remaining, self.cfg.min_remaining_turns)

    def _activation_value(self, card, prefix, rates, player):
        """VP-equivalent of one on_turn/off_turn activation of a card."""
        value = 0.0
        for res in ("gold", "strength", "magic"):
            value += rates[res[0]] * int(getattr(card, f"{res}_payout_{prefix}", 0) or 0)
        value += float(int(getattr(card, f"vp_payout_{prefix}", 0) or 0))
        if int(getattr(card, f"has_special_payout_{prefix}", 0) or 0):
            value += self._payout_value(
                getattr(card, f"special_payout_{prefix}", "") or "", rates, player
            )
        return value

    def _citizen_income_per_roll(self, card, rates, player):
        p = _match_rate(getattr(card, "roll_match1", -1)) + _match_rate(getattr(card, "roll_match2", -1))
        return p * 0.5 * (
            self._activation_value(card, "on_turn", rates, player)
            + self._activation_value(card, "off_turn", rates, player)
        )

    def _income_for_dice(self, player, rates, d1, d2):
        """Own on-turn harvest income if the finalized dice land on (d1, d2)."""
        total = 0.0
        cards = list(getattr(player, "owned_starters", []) or [])
        cards += [c for c in getattr(player, "owned_citizens", []) or [] if not getattr(c, "is_flipped", False)]
        for card in cards:
            activations = 0
            for attr in ("roll_match1", "roll_match2"):
                rm = int(getattr(card, attr, -1) or -1)
                if 1 <= rm <= 6:
                    activations += (d1 == rm) + (d2 == rm)
                elif 7 <= rm <= 12:
                    activations += int(d1 + d2 == rm)
            if activations:
                total += activations * self._activation_value(card, "on_turn", rates, player)
            elif d1 == d2 and "doubles" in str(getattr(card, "activation_trigger", "") or ""):
                total += self._activation_value(card, "on_turn", rates, player)
        return total

    def _roll_modifier_future_value(self, game, player, rates, card):
        """Future value of a roll.set_one_die domain (Foxgrove Palisade etc.):
        average best steering gain over all 36 natural rolls against the
        CURRENT tableau, times expected remaining own-turn rolls. As the
        tableau grows (e.g. Butchers paying on 11/12) this re-prices upward;
        anticipating that growth is the search's job, not the heuristic's."""
        effect = str(getattr(card, "passive_effect", "") or "").strip()
        if not effect.startswith("roll.set_one_die"):
            return 0.0
        kv = dict(tok.split("=", 1) for tok in effect.split()[1:] if "=" in tok)
        cost = 0
        spec = (kv.get("cost") or "").strip()
        if spec.startswith("g:"):
            cost = int(spec[2:])
        elif spec.startswith("g_per_owned_role:"):
            role = spec.split(":", 1)[1].replace("_citizen", "")
            roles = player.calc_roles() if hasattr(player, "calc_roles") else {}
            cost = int(roles.get(f"{role}_count", 0) or 0)
        total_gain = 0.0
        for r1 in range(1, 7):
            for r2 in range(1, 7):
                base = self._income_for_dice(player, rates, r1, r2)
                best = 0.0
                for rolled, other, swapped in ((r1, r2, False), (r2, r1, True)):
                    if "target" in kv:
                        fd = int(kv["target"])
                    elif "subtract" in kv:
                        fd = rolled - int(kv["subtract"])
                    else:
                        continue
                    if not (1 <= fd <= 6) or fd == rolled:
                        continue
                    pair = (other, fd) if swapped else (fd, other)
                    gain = self._income_for_dice(player, rates, *pair) - base - cost * rates["g"]
                    if gain > best:
                        best = gain
                total_gain += best
        # steering only applies on the player's own roll phase (half the turns)
        return (total_gain / 36.0) * self._remaining_rolls(game) * 0.5

    # ---- move valuation ------------------------------------------------

    def _find_top(self, grid, id_attr, card_id):
        for stack in grid or []:
            if stack and getattr(stack[-1], id_attr, None) == card_id:
                return stack[-1]
        return None

    def _monster_value(self, player, rates, vp, mtype, g_rew, s_rew, m_rew, special, g_cost, s_cost, m_cost):
        value = float(vp or 0)
        value += self._mult(player, "monster_multiplier")
        type_attr = {"Boss": "boss_multiplier", "Minion": "minion_multiplier",
                     "Beast": "beast_multiplier", "Titan": "titan_multiplier"}.get(mtype or "")
        if type_attr:
            value += self._mult(player, type_attr)
        value += rates["g"] * (g_rew or 0) + rates["s"] * (s_rew or 0) + rates["m"] * (m_rew or 0)
        if special:
            value += self._payout_value(special, rates, player)
        value -= rates["g"] * (g_cost or 0) + rates["s"] * (s_cost or 0) + rates["m"] * (m_cost or 0)
        return value

    def _value_standard(self, game, player, rates, move):
        at = move.get("action_type")
        pay = move.get("payment") or {}
        spent = sum(rates[r[0]] * int(pay.get(r) or 0) for r in ("gold", "strength", "magic"))

        if at == "take_resource":
            return rates.get((move.get("resource") or "g")[0], 0.0)

        if at == "hire_citizen":
            card = self._find_top(game.citizen_grid, "citizen_id", move.get("citizen_id"))
            if card is None:
                return -spent
            value = -spent
            for role in ("shadow", "holy", "soldier", "worker"):
                value += int(getattr(card, f"{role}_count", 0) or 0) * self._mult(player, f"{role}_multiplier")
            value += self._mult(player, "citizen_multiplier")
            value += self._citizen_income_per_roll(card, rates, player) * self._remaining_rolls(game)
            return value

        if at == "build_domain":
            card = self._find_top(game.domain_grid, "domain_id", move.get("domain_id"))
            if card is None:
                return -spent
            value = -spent + float(int(getattr(card, "vp_reward", 0) or 0))
            for role in ("shadow", "holy", "soldier", "worker"):
                value += int(getattr(card, f"{role}_count", 0) or 0) * self._mult(player, f"{role}_multiplier")
            value += self._mult(player, "domain_multiplier")
            steering = self._roll_modifier_future_value(game, player, rates, card)
            if steering > 0:
                value += steering
            elif int(getattr(card, "has_activation_effect", 0) or 0) or int(getattr(card, "has_passive_effect", 0) or 0):
                value += self.cfg.unparsed_effect_value
            return value

        if at == "slay_monster":
            card = self._find_top(game.monster_grid, "monster_id", move.get("monster_id"))
            if card is None and move.get("event_id") is not None:
                return 1.0  # events: slaying reveals/clears; mild positive default
            if card is None:
                return -spent
            return self._monster_value(
                player, rates,
                int(getattr(card, "vp_reward", 0) or 0), getattr(card, "monster_type", ""),
                int(getattr(card, "gold_reward", 0) or 0), int(getattr(card, "strength_reward", 0) or 0),
                int(getattr(card, "magic_reward", 0) or 0),
                getattr(card, "special_reward", "") if int(getattr(card, "has_special_reward", 0) or 0) else "",
                int(pay.get("gold") or 0), int(pay.get("strength") or 0), int(pay.get("magic") or 0),
            )

        return 0.0

    # ---- prompt valuation ----------------------------------------------

    def _duke_projection(self, duke):
        cfg = self.cfg

        def m(attr):
            return int(getattr(duke, attr, 0) or 0)

        score = 0.0
        for role in ("shadow", "holy", "soldier", "worker"):
            score += cfg.est_role_each * m(f"{role}_multiplier")
        score += cfg.est_monsters * m("monster_multiplier")
        score += cfg.est_citizens * m("citizen_multiplier")
        score += cfg.est_domains * m("domain_multiplier")
        for t in ("boss", "minion", "beast", "titan"):
            score += cfg.est_monster_type_each * m(f"{t}_multiplier")
        for res in ("gold", "strength", "magic"):
            mult = m(f"{res}_multiplier")
            if mult > 0:
                score += cfg.est_resources_each / mult
        return score

    def _value_prompt(self, game, player, rates, move, prc):
        action = (move.get("action") or move.get("response") or "").strip()
        body = action.split("|", 1)[1] if "|" in action else action
        kind = (prc.get("kind") or "").strip() if isinstance(prc, dict) else ""

        if move.get("action_type") == "submit_concurrent_action" and move.get("kind") == "choose_duke":
            for duke in getattr(player, "owned_dukes", None) or []:
                if str(getattr(duke, "duke_id", "")) == body:
                    return self._duke_projection(duke)
            return 0.0

        if body.startswith("wild_gain_resource"):
            res = body.split()[-1]
            gain = int(prc.get("gain_amount") or 2)
            cost_res = (prc.get("cost_resource") or "g")
            cost = int(prc.get("cost_amount") or 0)
            return rates.get(res, 0) * gain - rates.get(cost_res, 0) * cost
        if body.startswith("wild_cost_resource"):
            res = body.split()[-1]
            return -rates.get(res, 0)
        if body in ("skip_harvest_exchange", "skip"):
            return 0.0
        if body == "confirm_harvest_exchange":
            command = (prc.get("command") or "").strip()
            if command:
                return self._payout_value(command, rates, player)
            return 0.1
        if body in ("gold", "strength", "magic"):
            return rates[body[0]]
        if kind == "domain_choose_resource" and body.startswith("choose "):
            choices = prc.get("choices") or []
            idx = int(body.split()[1]) - 1
            if 0 <= idx < len(choices):
                res, amount = choices[idx][0], int(choices[idx][1])
                return rates.get(res, 0) * amount
        if body.startswith("choose_monster_slay ") or (kind == "immediate_slay" and body.startswith("slay_pay")):
            options = prc.get("options") or []
            if body.startswith("choose_monster_slay "):
                idx = int(body.split()[1]) - 1
                opt = options[idx] if 0 <= idx < len(options) else None
            else:
                mid = prc.get("monster_id")
                opt = next((o for o in options if o.get("monster_id") == mid), None) or prc
            if opt:
                card = self._find_top(game.monster_grid, "monster_id", opt.get("monster_id"))
                return self._monster_value(
                    player, rates,
                    int(getattr(card, "vp_reward", 0) or 0) if card else 2,
                    getattr(card, "monster_type", "") if card else "",
                    int(getattr(card, "gold_reward", 0) or 0) if card else 0,
                    int(getattr(card, "strength_reward", 0) or 0) if card else 0,
                    int(getattr(card, "magic_reward", 0) or 0) if card else 0,
                    (getattr(card, "special_reward", "") or "") if card else "",
                    int(opt.get("gold_cost") or 0), int(opt.get("strength_cost") or 0),
                    int(opt.get("magic_cost") or 0),
                )
        if body == "confirm_self_convert":
            kv = prc.get("kv") or {}
            pay = (kv.get("pay") or "").replace(":", " ")
            gain = (kv.get("gain") or "").replace(":", " ")
            return (self._pairs_value(gain.split(), rates)
                    - self._pairs_value(pay.split(), rates, mode="min"))
        return None  # unknown: caller falls back to random

    # ---- entry points --------------------------------------------------

    def move_values(self, game, player_id, moves):
        """VP-equivalent value per move, aligned with `moves`; None when this
        decision kind is unknown to the evaluator."""
        player = next((p for p in game.player_list if p.player_id == player_id), None)
        if player is None or not moves:
            return None
        rates = self._rates(player)
        req = getattr(game, "action_required", None) or {}
        is_standard = (
            (req.get("action") or "").strip() == "standard_action"
            and moves[0].get("action_type") != "act_on_required_action"
            and moves[0].get("action_type") != "submit_concurrent_action"
        )
        prc = getattr(game, "pending_required_choice", None) or {}
        if not prc:
            ca = getattr(game, "concurrent_action", None) or {}
            prompts = (ca.get("data") or {}).get("prompts") or {}
            mine = prompts.get(player_id) or []
            if mine and isinstance(mine[0], dict):
                prc = mine[0].get("pending_required_choice") or mine[0]

        if moves[0].get("action_type") == "finalize_roll":
            pr = getattr(game, "pending_roll", None) or {}
            r1 = int(pr.get("rolled_die_one") or 0)
            r2 = int(pr.get("rolled_die_two") or 0)
            if not (1 <= r1 <= 6 and 1 <= r2 <= 6):
                return [0.0] * len(moves)
            base = self._income_for_dice(player, rates, r1, r2)
            values = []
            for move in moves:
                fd1 = int(move.get("die_one") or r1)
                fd2 = int(move.get("die_two") or r2)
                cost = int(move.get("_mod_cost_gold") or 0)
                values.append(
                    self._income_for_dice(player, rates, fd1, fd2) - base - cost * rates["g"]
                )
            return values

        values = []
        for move in moves:
            if is_standard:
                values.append(self._value_standard(game, player, rates, move))
            else:
                value = self._value_prompt(game, player, rates, move, prc)
                if value is None:
                    return None
                values.append(value)
        return values

    def analyze(self, game, player_id, moves):
        """Rank moves by VP-equivalent value; sets ``last_decision``."""
        from agent.move_summary import move_key

        if not moves:
            self.last_decision = {"policy": "greedy", "chosen": None, "candidates": []}
            return self.last_decision
        if len(moves) == 1:
            self.last_decision = {
                "policy": "greedy",
                "chosen": moves[0],
                "candidates": [],
                "trivial": True,
            }
            return self.last_decision

        values = self.move_values(game, player_id, moves)
        if values is None:
            chosen = random.choice(moves)
            self.last_decision = {
                "policy": "greedy",
                "chosen": chosen,
                "candidates": [],
                "unscored": True,
            }
            return self.last_decision

        ranked = sorted(zip(moves, values), key=lambda kv: -kv[1])
        best_value = ranked[0][1]
        best = [m for m, v in ranked if v >= best_value - 1e-9]
        chosen = random.choice(best)
        candidates = []
        for move, value in ranked:
            candidates.append({
                "move": move,
                "key": move_key(move),
                "vp_equiv": value,
                "delta_from_best": value - best_value,
            })
        self.last_decision = {
            "policy": "greedy",
            "chosen": chosen,
            "candidates": candidates,
            "best_vp_equiv": best_value,
        }
        return self.last_decision

    def choose(self, game, view, player_id, moves):
        return self.analyze(game, player_id, moves)["chosen"]
