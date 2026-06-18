"""Pick balanced monster areas for authoring rotating preset boards.

Curated expansion sets ramp slay cost from weak to strong. Weak and strong anchors are
picked first within asymmetric cost bands (board may shift cheap or expensive); three
middle areas fill the span between those anchors. Type mix (slay-weighted ratios and flex
counts) is a soft tiebreaker only — slay cost spread comes first.

Use `scripts/generate_rotating_monster_set.py` to generate `fixed_monster_areas`
for preset JSON files. In-game random dealing uses `pick_random_monster_areas`.
"""

import random
from collections import Counter

MONSTER_AREA_SLOT_COUNT = 5
FLEX_TYPES = ("Minion", "Beast", "Titan")
# Cost-weighted flex mix averaged across the four curated 5-area expansions.
CURATED_WEIGHTED_RATIOS = {"Minion": 0.226, "Beast": 0.449, "Titan": 0.325}
# Per-board flex icon totals averaged across base1, shadowvale, crimsonseas, flamesandfrost.
CURATED_FLEX_COUNTS = {"Minion": 6.2, "Beast": 9.2, "Titan": 4.5}
# Type mix is a light tiebreaker after cost fit (spread is primary).
_TYPE_SOFT_WEIGHT = 0.6
_COUNT_SOFT_WEIGHT = 0.4
_SLOT_COUNT = MONSTER_AREA_SLOT_COUNT
_MIDDLE_FRACTIONS = (0.25, 0.5, 0.75)
# Middle slots: stay near quartile targets (unchanged for now).
_MIDDLE_COST_EXTRA_BAND = 0.75
# Anchor slots: absolute avg-slay-cost limits (board may shift cheap or expensive).
# Weak anchor avg slay cost must be <= this (excludes Desert ~8.0).
_WEAK_ANCHOR_MAX_COST = 7.0
# Strong anchor avg slay cost must be >= this (includes Gnolls ~8.2).
_STRONG_ANCHOR_MIN_COST = 8.1
# Split each anchor band: usual cheap/expensive core vs shifted overlap (Forest, Gnolls).
_WEAK_CORE_MAX_COST = 5.0
_STRONG_CORE_MIN_COST = 11.0
_SHIFTED_ANCHOR_CHANCE = 0.04
_MIN_ANCHOR_COST_GAP = 0.5
# Loose bands: randomize among several good cost candidates; type is a small nudge.
_DRIFT_LOOSE_BAND = 0.2
# How far above the best cost match we still randomize among (anchors / middles).
_ANCHOR_COST_LOOSE_BAND = 1.25
_MIDDLE_COST_LOOSE_BAND = 1.0
_ANCHOR_MIN_POOL = 3
_MIDDLE_MIN_POOL = 2
_MAX_PICK_POOL = 10
_ANCHOR_PICK_WEIGHT_SLOPE = 6.0


def _card_slay_cost(card):
    if isinstance(card, dict):
        strength = card.get("strength_cost") or 0
        magic = card.get("magic_cost") or 0
    else:
        strength = getattr(card, "strength_cost", 0) or 0
        magic = getattr(card, "magic_cost", 0) or 0
    return int(strength) + int(magic)


def _card_monster_type(card):
    if isinstance(card, dict):
        return card.get("monster_type") or ""
    return getattr(card, "monster_type", "") or ""


def area_avg_slay_cost(cards):
    if not cards:
        return 0.0
    return sum(_card_slay_cost(card) for card in cards) / len(cards)


def area_flex_type_counts(cards):
    counts = Counter()
    for card in cards:
        monster_type = _card_monster_type(card)
        if monster_type in FLEX_TYPES:
            counts[monster_type] += 1
    return {t: int(counts.get(t, 0)) for t in FLEX_TYPES}


def area_flex_slay_weight(cards):
    weights = {t: 0.0 for t in FLEX_TYPES}
    for card in cards:
        monster_type = _card_monster_type(card)
        if monster_type in FLEX_TYPES:
            weights[monster_type] += _card_slay_cost(card)
    return weights


def _flex_weight_ratios(weight_totals):
    total = sum(float(weight_totals.get(t, 0) or 0) for t in FLEX_TYPES)
    if total <= 0:
        return {t: 1.0 / len(FLEX_TYPES) for t in FLEX_TYPES}
    return {t: float(weight_totals.get(t, 0) or 0) / total for t in FLEX_TYPES}


def _type_weight_drift(running_weights, area_weights):
    trial = Counter()
    for monster_type in FLEX_TYPES:
        trial[monster_type] = float(running_weights.get(monster_type, 0) or 0)
        trial[monster_type] += float(area_weights.get(monster_type, 0) or 0)
    ratios = _flex_weight_ratios(trial)
    drift = sum(
        (ratios[monster_type] - CURATED_WEIGHTED_RATIOS[monster_type]) ** 2
        for monster_type in FLEX_TYPES
    )
    return drift * _TYPE_SOFT_WEIGHT


def _prorated_count_targets(chosen_count):
    progress = (int(chosen_count) + 1) / float(_SLOT_COUNT)
    return {t: CURATED_FLEX_COUNTS[t] * progress for t in FLEX_TYPES}


def _type_count_drift(running_counts, area_counts, chosen_count):
    trial = Counter()
    for monster_type in FLEX_TYPES:
        trial[monster_type] = int(running_counts.get(monster_type, 0) or 0)
        trial[monster_type] += int(area_counts.get(monster_type, 0) or 0)
    targets = _prorated_count_targets(chosen_count)
    drift = sum(
        (trial[monster_type] - targets[monster_type]) ** 2
        for monster_type in FLEX_TYPES
    )
    scale = sum(targets[monster_type] ** 2 for monster_type in FLEX_TYPES)
    if scale <= 0:
        return drift * _COUNT_SOFT_WEIGHT
    return (drift / scale) * _COUNT_SOFT_WEIGHT


def _type_drift(running_weights, area_weights, running_counts, area_counts, chosen_count):
    return (
        _type_weight_drift(running_weights, area_weights)
        + _type_count_drift(running_counts, area_counts, chosen_count)
    )


def _row_type_drift(row, running_weights, running_counts, chosen_count):
    return _type_drift(running_weights, row[3], running_counts, row[2], chosen_count)


def _score_areas(areas, grouped):
    scored = []
    for area in areas:
        cards = list(grouped.get(area) or [])
        scored.append((
            area,
            area_avg_slay_cost(cards),
            area_flex_type_counts(cards),
            area_flex_slay_weight(cards),
        ))
    return scored


def _pick_from_pool(pool, rng):
    if not pool:
        raise ValueError("No monster areas left to pick.")
    return rng.choice(pool)[0]


def _loose_pick_from_ranked(ranked, score_fn, loose_band, min_pool, max_pool, rng):
    """Weighted random among several top-scoring rows (not just the single best)."""
    if not ranked:
        raise ValueError("No candidates to pick from.")
    best = score_fn(ranked[0])
    pool = [row for row in ranked if score_fn(row) <= best + loose_band]
    if len(pool) < min_pool:
        pool = list(ranked[:min(min_pool, len(ranked))])
    if len(pool) > max_pool:
        pool = pool[:max_pool]
    if len(pool) == 1:
        return pool[0][0]
    scores = [score_fn(row) for row in pool]
    best_score = min(scores)
    weights = [1.0 / (1.0 + max(0.0, score - best_score) * _ANCHOR_PICK_WEIGHT_SLOPE) for score in scores]
    return rng.choices(pool, weights=weights, k=1)[0][0]


def _anchor_subpool(core, shifted, rng):
    """Mostly pick the cost-appropriate core; ~4% pick the shifted overlap band."""
    if shifted and rng.random() < _SHIFTED_ANCHOR_CHANCE:
        return shifted, True
    if core:
        return core, False
    return shifted, True


def _pick_weak_anchor(scored, pool_min, exclude, running_weights, running_counts, rng):
    """Cheapest stack: core cheap areas, occasionally an expensive-in-band stack (e.g. Forest)."""
    chosen_count = len(exclude)
    ceiling = _WEAK_ANCHOR_MAX_COST
    candidates = [
        row for row in scored
        if row[0] not in exclude and row[1] <= ceiling + 0.001
    ]
    if not candidates:
        cheapest = sorted(scored, key=lambda row: row[1])[: max(_ANCHOR_MIN_POOL, 1)]
        candidates = [row for row in cheapest if row[0] not in exclude] or cheapest

    core = [row for row in candidates if row[1] <= _WEAK_CORE_MAX_COST + 0.001]
    shifted = [row for row in candidates if row[1] > _WEAK_CORE_MAX_COST + 0.001]
    pool, is_shifted = _anchor_subpool(core, shifted, rng)

    if is_shifted:
        def _score(row):
            cost_part = float(ceiling - row[1])
            return cost_part + _row_type_drift(row, running_weights, running_counts, chosen_count)
    else:
        def _score(row):
            cost_part = float(row[1] - pool_min)
            return cost_part + _row_type_drift(row, running_weights, running_counts, chosen_count)

    ranked = sorted(pool, key=lambda row: (_score(row), row[1]))
    return _loose_pick_from_ranked(
        ranked,
        _score,
        _ANCHOR_COST_LOOSE_BAND,
        min(_ANCHOR_MIN_POOL, len(pool)),
        min(_MAX_PICK_POOL, len(pool)),
        rng,
    )


def _pick_strong_anchor(scored, pool_max, weak_cost, exclude, running_weights, running_counts, rng):
    """Priciest stack: core expensive areas, occasionally a cheap-in-band stack (e.g. Gnolls)."""
    chosen_count = len(exclude)
    floor = _STRONG_ANCHOR_MIN_COST
    min_cost = float(weak_cost) + _MIN_ANCHOR_COST_GAP
    candidates = [
        row for row in scored
        if row[0] not in exclude and row[1] >= floor - 0.001 and row[1] >= min_cost - 0.001
    ]
    if not candidates:
        remaining = [row for row in scored if row[0] not in exclude and row[1] >= min_cost - 0.001]
        if not remaining:
            remaining = [row for row in scored if row[0] not in exclude]
        candidates = sorted(remaining, key=lambda row: -row[1])[: max(_ANCHOR_MIN_POOL, 1)]

    core = [row for row in candidates if row[1] >= _STRONG_CORE_MIN_COST - 0.001]
    shifted = [row for row in candidates if row[1] < _STRONG_CORE_MIN_COST - 0.001]
    pool, is_shifted = _anchor_subpool(core, shifted, rng)

    if is_shifted:
        def _score(row):
            cost_part = float(row[1] - floor)
            return cost_part + _row_type_drift(row, running_weights, running_counts, chosen_count)
    else:
        def _score(row):
            cost_part = float(pool_max - row[1])
            return cost_part + _row_type_drift(row, running_weights, running_counts, chosen_count)

    ranked = sorted(pool, key=lambda row: (_score(row), -row[1]))
    return _loose_pick_from_ranked(
        ranked,
        _score,
        _ANCHOR_COST_LOOSE_BAND,
        min(_ANCHOR_MIN_POOL, len(pool)),
        min(_MAX_PICK_POOL, len(pool)),
        rng,
    )


def _pick_from_difficulty_band(scored, target_difficulty, band, exclude, running_weights, running_counts, rng, prefer_high):
    """Legacy symmetric band helper (unused by anchor picks; kept for compatibility)."""
    chosen_count = len(exclude)
    candidates = [
        row for row in scored
        if row[0] not in exclude and abs(row[1] - target_difficulty) <= band
    ]
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda row: (
            _row_type_drift(row, running_weights, running_counts, chosen_count),
            -row[1] if prefer_high else row[1],
        ),
    )
    return _loose_pick_from_ranked(
        ranked,
        lambda row: _row_type_drift(row, running_weights, running_counts, chosen_count),
        _DRIFT_LOOSE_BAND,
        min(_ANCHOR_MIN_POOL, len(candidates)),
        min(_MAX_PICK_POOL, len(candidates)),
        rng,
    )


def _pick_near_target(scored, target, exclude, running_weights, running_counts, rng):
    chosen_count = len(exclude)
    candidates = [row for row in scored if row[0] not in exclude]
    if not candidates:
        raise ValueError("No monster areas left to pick.")

    ranked = sorted(
        candidates,
        key=lambda row: abs(row[1] - target),
    )
    best_distance = abs(ranked[0][1] - target)
    cost_band = max(best_distance + _MIDDLE_COST_EXTRA_BAND, 0.75)
    cost_pool = [row for row in ranked if abs(row[1] - target) <= cost_band]
    if len(cost_pool) > _MAX_PICK_POOL:
        cost_pool = cost_pool[:_MAX_PICK_POOL]
    if not cost_pool:
        cost_pool = ranked[: min(_MIDDLE_MIN_POOL, len(ranked))]

    def _score(row):
        return abs(row[1] - target) + _row_type_drift(
            row, running_weights, running_counts, chosen_count,
        )

    cost_pool = sorted(cost_pool, key=_score)
    return _loose_pick_from_ranked(
        cost_pool,
        _score,
        _MIDDLE_COST_LOOSE_BAND,
        min(_MIDDLE_MIN_POOL, len(cost_pool)),
        min(_MAX_PICK_POOL, len(cost_pool)),
        rng,
    )


def pick_balanced_monster_areas(areas, grouped, rng=None, count=_SLOT_COUNT):
    """Return `count` areas with easy-to-hard cost spread and loose type mix."""
    rng = rng or random
    areas = list(areas or [])
    if len(areas) < count:
        raise ValueError(f"Need at least {count} monster areas, got {len(areas)}.")

    scored = _score_areas(areas, grouped)
    running_weights = Counter()
    running_counts = Counter()
    pool_min = min(row[1] for row in scored)
    pool_max = max(row[1] for row in scored)

    if abs(pool_min - pool_max) < 0.001:
        return pick_random_monster_areas(areas, rng=rng, count=count)

    weakest = _pick_weak_anchor(scored, pool_min, set(), running_weights, running_counts, rng)
    chosen = [weakest]
    weakest_row = next(row for row in scored if row[0] == weakest)
    weak_cost = weakest_row[1]
    running_weights.update(weakest_row[3])
    running_counts.update(weakest_row[2])

    strongest = _pick_strong_anchor(
        scored, pool_max, weak_cost, set(chosen), running_weights, running_counts, rng,
    )
    chosen.append(strongest)
    strong_row = next(row for row in scored if row[0] == strongest)
    strong_cost = strong_row[1]
    running_weights.update(strong_row[3])
    running_counts.update(strong_row[2])

    span = strong_cost - weak_cost
    if span < 0.001:
        span = pool_max - pool_min
        weak_cost = pool_min
        strong_cost = pool_max

    for fraction in _MIDDLE_FRACTIONS:
        target = weak_cost + fraction * span
        pick = _pick_near_target(scored, target, set(chosen), running_weights, running_counts, rng)
        chosen.append(pick)
        pick_row = next(row for row in scored if row[0] == pick)
        running_weights.update(pick_row[3])
        running_counts.update(pick_row[2])

    return chosen


def pick_random_monster_areas(areas, rng=None, count=_SLOT_COUNT):
    rng = rng or random
    areas = list(areas or [])
    if len(areas) < count:
        raise ValueError(f"Need at least {count} monster areas, got {len(areas)}.")
    return list(rng.sample(areas, count))


def flex_totals_for_areas(areas, grouped):
    totals = Counter()
    for area in areas:
        totals.update(area_flex_type_counts(grouped.get(area) or []))
    return {t: int(totals.get(t, 0)) for t in FLEX_TYPES}


def flex_weight_totals_for_areas(areas, grouped):
    totals = Counter()
    for area in areas:
        for monster_type, weight in area_flex_slay_weight(grouped.get(area) or []).items():
            totals[monster_type] += weight
    return {t: float(totals.get(t, 0) or 0) for t in FLEX_TYPES}


def flex_weight_ratios_for_areas(areas, grouped):
    return _flex_weight_ratios(flex_weight_totals_for_areas(areas, grouped))
