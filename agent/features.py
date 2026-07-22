"""State featurization for the learned value function.

extract(game, viewer_pid) -> fixed-length float vector, viewer-relative
(my side first, opponent second, then differences and global board state).
Uses the engine's own endgame scorer for projected VP and GreedyPolicy's
income model, so the features share semantics with everything else.
2-player only for now.

v2 additions (domain-knowledge features, July 2026):
  - purchase-threshold features: value of the best accessible monster/domain
    each player can afford NOW and can likely reach NEXT TURN given their
    per-resource income EV — board control / denial signals
  - contested citizens (names both players have hired) and who can afford them
  - monster-stack lookahead (public info): per-stack depths and boss (bottom
    card) value within reach — captures "slay one, opponent takes the last 2
    including the boss" parity situations
  - per-stack exhaustion proximity: citizen stacks at depth 1/2, and how many
    purchases would trigger the stack-exhaustion end condition — enables
    "close the game out while ahead" awareness
"""

import numpy as np

from agent.policies import GreedyPolicy, _match_rate

FEATURE_VERSION = 2

_greedy = GreedyPolicy()

MONSTER_TYPES = ("Boss", "Minion", "Beast", "Titan")


def _owned_type_counts(player):
    counts = dict.fromkeys(MONSTER_TYPES, 0)
    for m in player.owned_monsters:
        t = getattr(m, "monster_type", None)
        if t in counts:
            counts[t] += 1
    return counts


def _board_type_counts(game):
    """Monster-type symbols still available to slay (full-stack lookahead —
    public information). Duke-independent 'runway' for type-scoring dukes
    (Mico per-Boss, Marianna per-Minion, ...)."""
    counts = dict.fromkeys(MONSTER_TYPES, 0)
    for stack in game.monster_grid:
        for card in stack:
            t = getattr(card, "monster_type", None)
            if getattr(card, "monster_id", None) is not None and t in counts:
                counts[t] += 1
    return counts


def _income_by_resource(player):
    """Expected per-roll gain of (gold, strength, magic) — resource space, not
    VP space. Specials approximated: exchanges net to their target resource,
    choose/steal assigned to their largest option."""
    ev = {"g": 0.0, "s": 0.0, "m": 0.0}
    cards = list(player.owned_starters) + [
        c for c in player.owned_citizens if not getattr(c, "is_flipped", False)
    ]
    for card in cards:
        p = _match_rate(getattr(card, "roll_match1", -1)) + _match_rate(getattr(card, "roll_match2", -1))
        if p <= 0:
            continue
        for prefix in ("on_turn", "off_turn"):
            weight = p * 0.5
            for res in ("gold", "strength", "magic"):
                ev[res[0]] += weight * int(getattr(card, f"{res}_payout_{prefix}", 0) or 0)
            if int(getattr(card, f"has_special_payout_{prefix}", 0) or 0):
                spec = str(getattr(card, f"special_payout_{prefix}", "") or "")
                for part in spec.split("+"):
                    tokens = part.strip().split()
                    if not tokens:
                        continue
                    verb = tokens[0].lower()
                    pairs = [
                        (tokens[i].lower(), int(tokens[i + 1]))
                        for i in range(1, len(tokens) - 1, 2)
                        if tokens[i].lower() in ("g", "s", "m") and tokens[i + 1].isdigit()
                    ]
                    if not pairs:
                        continue
                    if verb in ("choose", "steal"):
                        res, amount = max(pairs, key=lambda kv: kv[1])
                        ev[res] += weight * amount
                    elif verb == "exchange" and len(pairs) >= 2:
                        cost_res, cost_amt = pairs[0]
                        gain_res, gain_amt = pairs[1]
                        net = gain_amt - cost_amt
                        if net > 0:
                            ev[gain_res] += weight * net
    return ev


def _can_slay(gold, strength, magic, g_cost, s_cost, m_cost):
    """Engine payment rules: gold exact, magic >= m_cost, excess magic wilds
    toward strength (>=1 strength paid when wilding)."""
    if gold < g_cost or magic < m_cost:
        return False
    if strength >= s_cost:
        return True
    return s_cost > 0 and strength >= 1 and (magic - m_cost) >= (s_cost - strength)


def _monster_costs(card):
    return (
        int(getattr(card, "extra_gold_cost", 0) or 0),
        int(getattr(card, "strength_cost", 0) or 0) + int(getattr(card, "extra_strength_cost", 0) or 0),
        int(getattr(card, "magic_cost", 0) or 0) + int(getattr(card, "extra_magic_cost", 0) or 0),
    )


def _monster_value_for(game, player, rates, card):
    return _greedy._monster_value(
        player, rates,
        int(getattr(card, "vp_reward", 0) or 0), getattr(card, "monster_type", ""),
        int(getattr(card, "gold_reward", 0) or 0), int(getattr(card, "strength_reward", 0) or 0),
        int(getattr(card, "magic_reward", 0) or 0),
        (getattr(card, "special_reward", "") or "") if int(getattr(card, "has_special_reward", 0) or 0) else "",
        0, 0, 0,  # value the prize, not net of payment (costs feed affordability)
    )


def _domain_value_for(game, player, rates, card):
    value = float(int(getattr(card, "vp_reward", 0) or 0))
    for role in ("shadow", "holy", "soldier", "worker"):
        value += int(getattr(card, f"{role}_count", 0) or 0) * _greedy._mult(player, f"{role}_multiplier")
    value += _greedy._mult(player, "domain_multiplier")
    value += _greedy._domain_effect_value(game, player, rates, card)
    return value


def _threshold_features(game, player):
    """[best monster value affordable now, best reachable next turn,
        best domain value affordable now, best reachable next turn] (VP-eq /10)."""
    rates = _greedy._rates(player)
    ev = _income_by_resource(player)
    g0, s0, m0 = player.gold_score, player.strength_score, player.magic_score
    g1, s1, m1 = g0 + ev["g"], s0 + ev["s"], m0 + ev["m"]

    best_mon_now = best_mon_next = 0.0
    for stack in game.monster_grid:
        if not stack:
            continue
        top = stack[-1]
        if getattr(top, "monster_id", None) is None or not getattr(top, "is_accessible", False):
            continue
        gc, sc, mc = _monster_costs(top)
        value = _monster_value_for(game, player, rates, top)
        if _can_slay(g0, s0, m0, gc, sc, mc):
            best_mon_now = max(best_mon_now, value)
        if _can_slay(g1, s1, m1, gc, sc, mc):
            best_mon_next = max(best_mon_next, value)

    best_dom_now = best_dom_next = 0.0
    for stack in game.domain_grid:
        if not stack:
            continue
        top = stack[-1]
        if getattr(top, "domain_id", None) is None or not getattr(top, "is_accessible", False) \
                or not getattr(top, "is_visible", True):
            continue
        cost = int(getattr(top, "gold_cost", 0) or 0)
        value = _domain_value_for(game, player, rates, top)
        if g0 + m0 >= cost:  # magic wilds gold
            best_dom_now = max(best_dom_now, value)
        if g1 + m1 >= cost:
            best_dom_next = max(best_dom_next, value)

    return [best_mon_now / 10.0, best_mon_next / 10.0, best_dom_now / 10.0, best_dom_next / 10.0]


def _contested_features(game, me, opp):
    """Citizens whose NAME both players have hired: how contested is the board
    and who can grab the accessible ones right now."""
    mine = {c.name for c in me.owned_citizens}
    theirs = {c.name for c in opp.owned_citizens}
    contested = mine & theirs
    count = affordable_me = affordable_opp = 0
    for stack in game.citizen_grid:
        if not stack:
            continue
        top = stack[-1]
        if getattr(top, "citizen_id", None) is None or not getattr(top, "is_accessible", False):
            continue
        if top.name not in contested:
            continue
        count += 1
        cost = int(getattr(top, "gold_cost", 0) or 0)
        my_cost = cost + sum(1 for c in me.owned_citizens if c.name == top.name and not getattr(c, "is_flipped", False)) \
            + sum(1 for s in me.owned_starters if s.name == top.name)
        opp_cost = cost + sum(1 for c in opp.owned_citizens if c.name == top.name and not getattr(c, "is_flipped", False)) \
            + sum(1 for s in opp.owned_starters if s.name == top.name)
        if me.gold_score + me.magic_score >= my_cost:
            affordable_me += 1
        if opp.gold_score + opp.magic_score >= opp_cost:
            affordable_opp += 1
    return [count / 5.0, affordable_me / 5.0, affordable_opp / 5.0]


def _monster_stack_features(game, me, opp):
    """Public monster-stack lookahead: depth distribution and boss-in-reach.
    Captures parity plays ('slay one, opponent gets the last two + boss')."""
    rates_me = _greedy._rates(me)
    depth1 = depth2 = depth3 = 0
    best_boss_value = 0.0
    best_boss_depth = 0.0
    total_vp_left = 0
    for stack in game.monster_grid:
        monsters = [c for c in stack if getattr(c, "monster_id", None) is not None]
        if not monsters:
            continue
        depth = len(monsters)
        if depth == 1:
            depth1 += 1
        elif depth == 2:
            depth2 += 1
        elif depth == 3:
            depth3 += 1
        total_vp_left += sum(int(getattr(c, "vp_reward", 0) or 0) for c in monsters)
        boss = monsters[0]  # bottom of the stack
        if depth <= 3:
            value = _monster_value_for(game, me, rates_me, boss)
            if value > best_boss_value:
                best_boss_value = value
                best_boss_depth = depth
    return [
        depth1 / 5.0,
        depth2 / 5.0,
        depth3 / 5.0,
        best_boss_value / 10.0,
        best_boss_depth / 3.0,
        total_vp_left / 60.0,
    ]


def _exhaustion_features(game, me):
    """Per-stack end-game proximity: near-empty citizen stacks and how many
    purchases away the stack-exhaustion end condition is."""
    n_players = len(game.player_list)
    citizen_depth1 = citizen_depth2 = 0
    affordable_last = 0
    for stack in game.citizen_grid:
        citizens = [c for c in stack if getattr(c, "citizen_id", None) is not None]
        if len(citizens) == 1:
            citizen_depth1 += 1
            top = stack[-1]
            if getattr(top, "is_accessible", False):
                cost = int(getattr(top, "gold_cost", 0) or 0) \
                    + sum(1 for c in me.owned_citizens if c.name == top.name and not getattr(c, "is_flipped", False)) \
                    + sum(1 for s in me.owned_starters if s.name == top.name)
                if me.gold_score + me.magic_score >= cost:
                    affordable_last += 1
        elif len(citizens) == 2:
            citizen_depth2 += 1
    slots_needed = max(0, 2 * n_players - int(game.exhausted_count or 0))
    gap = max(0, slots_needed - citizen_depth1)
    return [
        citizen_depth1 / 4.0,
        citizen_depth2 / 4.0,
        slots_needed / (2.0 * n_players),
        gap / (2.0 * n_players),          # 0 => the end is buyable via last-citizens
        affordable_last / 4.0,            # ...and I can afford this many of them now
    ]


def _player_features(game, player, projected_vp):
    rates = _greedy._rates(player)
    citizens = [c for c in player.owned_citizens if not getattr(c, "is_flipped", False)]
    income = sum(_greedy._citizen_income_per_roll(c, rates, player) for c in citizens)
    income += sum(
        _greedy._citizen_income_per_roll(s, rates, player) for s in player.owned_starters
    )
    roles = player.calc_roles()
    steering = any(
        str(getattr(d, "passive_effect", "") or "").startswith("roll.")
        for d in player.owned_domains
        if not getattr(d, "is_flipped", False)
    )
    return [
        player.gold_score / 20.0,
        player.strength_score / 20.0,
        player.magic_score / 20.0,
        player.victory_score / 50.0,
        projected_vp / 100.0,
        len(citizens) / 10.0,
        len(player.owned_domains) / 6.0,
        len(player.owned_monsters) / 8.0,
        roles["shadow_count"] / 8.0,
        roles["holy_count"] / 8.0,
        roles["soldier_count"] / 8.0,
        roles["worker_count"] / 8.0,
        income / 3.0,
        1.0 if steering else 0.0,
    ] + [
        _owned_type_counts(player)[t] / 4.0 for t in MONSTER_TYPES
    ]


def extract(game, viewer_pid):
    me = opp = None
    for p in game.player_list:
        if p.player_id == viewer_pid:
            me = p
        else:
            opp = p
    if me is None or opp is None:
        raise ValueError(f"viewer {viewer_pid!r} not found or not a 2-player game")

    try:
        scores = {s["player_id"]: int(s["total_vp"]) for s in game.endgame._calculate_final_scores()}
    except Exception:
        scores = {p.player_id: int(p.victory_score) for p in game.player_list}
    my_proj = scores.get(me.player_id, 0)
    opp_proj = scores.get(opp.player_id, 0)

    features = _player_features(game, me, my_proj)
    features += _player_features(game, opp, opp_proj)

    n_players = len(game.player_list)
    monsters_left = sum(len(s) for s in game.monster_grid)
    domains_left = sum(len(s) for s in game.domain_grid)
    citizen_stacks = [len(s) for s in game.citizen_grid] or [0]
    active = game.player_list[game.turn_index].player_id if game.player_list else None
    features += [
        (my_proj - opp_proj) / 50.0,
        (me.gold_score + me.strength_score + me.magic_score
         - opp.gold_score - opp.strength_score - opp.magic_score) / 40.0,
        int(game.turn_number or 0) / 32.0,
        int(game.exhausted_count or 0) / (2.0 * n_players),
        monsters_left / 34.0,
        domains_left / 15.0,
        min(citizen_stacks) / 5.0,
        sum(citizen_stacks) / 50.0,
        1.0 if active == viewer_pid else 0.0,
        1.0 if getattr(me, "is_first", False) else 0.0,
        1.0 if game.end_game_triggered else 0.0,
    ]

    # v2: purchase thresholds (me, then opp), contested citizens,
    # monster-stack lookahead, per-stack exhaustion proximity
    features += _threshold_features(game, me)
    features += _threshold_features(game, opp)
    features += _contested_features(game, me, opp)
    features += _monster_stack_features(game, me, opp)
    features += _exhaustion_features(game, me)
    # v2: monster-type symbols remaining on the board (runway for
    # type-scoring dukes; owned counts live in the per-player block)
    board_types = _board_type_counts(game)
    features += [board_types[t] / 8.0 for t in MONSTER_TYPES]

    return np.asarray(features, dtype=np.float32)


N_FEATURES = 2 * 18 + 11 + 4 + 4 + 3 + 6 + 5 + 4
