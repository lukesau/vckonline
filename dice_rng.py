"""Canonical dice RNG primitives plus distribution-analysis helpers.

``roll_die`` and ``roll_dice_pair`` are the single source of truth for how the
engine turns the RNG into dice values. ``engines.lifecycle`` calls
``roll_dice_pair`` from ``roll_phase`` and ``roll_die`` from the re-roll
passives, so the audit/simulation code here exercises the exact same code path
as production instead of a hand-copied mirror.

Randomness note: like the rest of the engine these default to the process-global
``random`` module so ``engines.headless.seed_everything`` keeps working. Pass an
explicit ``random.Random`` instance for isolated, reproducible simulations.
"""

import math
import random

from game_setup import DEBUG_DIE_ONE_VALUES, DEBUG_DIE_TWO_VALUES

# Standard two-d6 sum counts out of 36 equally likely outcomes.
SUM_OUTCOME_COUNTS = {s: 0 for s in range(2, 13)}
for _d1 in range(1, 7):
    for _d2 in range(1, 7):
        SUM_OUTCOME_COUNTS[_d1 + _d2] += 1

DIE_FACE_COUNT = 6
TOTAL_OUTCOMES = 36


def roll_die(rng=None):
    """Draw one die exactly as the engine's re-roll passives do."""
    if rng is None:
        rng = random
    return rng.randint(1, 6)


def roll_dice_pair(debug_mode=False, rng=None):
    """Draw ``(die_one, die_two)`` exactly as ``roll_phase`` does.

    In debug mode the value sets are constrained (see ``DEBUG_DIE_ONE_VALUES`` /
    ``DEBUG_DIE_TWO_VALUES``) so granted roll-modifier domains can steer either
    die; otherwise both dice are fair ``randint(1, 6)`` draws.
    """
    if rng is None:
        rng = random
    if debug_mode:
        return rng.choice(DEBUG_DIE_ONE_VALUES), rng.choice(DEBUG_DIE_TWO_VALUES)
    return rng.randint(1, 6), rng.randint(1, 6)


def roll_matches_signature(d1, d2, roll_match1, roll_match2=0):
    """True when a roll hits the citizen/starter harvest signature.

    Matches the boolean half of ``HarvestEngine._roll_match_count``.
    """
    ds = d1 + d2
    try:
        rm2 = int(roll_match2) if roll_match2 is not None else 0
    except (TypeError, ValueError):
        rm2 = 0
    return (
        roll_match1 == d1
        or roll_match1 == d2
        or roll_match1 == ds
        or rm2 == ds
    )


def analytical_roll_match_probability(roll_match1, roll_match2=0):
    """Exact probability over fair independent d6 pairs."""
    hits = 0
    for d1 in range(1, 7):
        for d2 in range(1, 7):
            if roll_matches_signature(d1, d2, roll_match1, roll_match2):
                hits += 1
    return hits / TOTAL_OUTCOMES


def simulate_rolls(n, rng=None, debug_mode=False):
    """Simulate ``n`` rolls through the canonical ``roll_dice_pair`` primitive."""
    if rng is None:
        rng = random.Random()

    die_counts = {face: 0 for face in range(1, 7)}
    sum_counts = {s: 0 for s in range(2, 13)}
    pairs = []

    for _ in range(n):
        d1, d2 = roll_dice_pair(debug_mode=debug_mode, rng=rng)
        die_counts[d1] += 1
        die_counts[d2] += 1
        s = d1 + d2
        sum_counts[s] = sum_counts.get(s, 0) + 1
        pairs.append((d1, d2))

    return {
        "n_rolls": n,
        "die_counts": die_counts,
        "sum_counts": sum_counts,
        "pairs": pairs,
    }


def chi_square_from_counts(observed_counts, expected_probs, total):
    """Pearson chi-square vs expected category probabilities."""
    chi2 = 0.0
    for key in observed_counts:
        observed = observed_counts[key]
        expected = float(expected_probs[key]) * total
        if expected <= 0:
            continue
        diff = observed - expected
        chi2 += (diff * diff) / expected
    return chi2


def chi_square_critical_value(df, alpha=0.001):
    """Upper-tail chi-square critical value (no scipy dependency)."""
    # Wilson-Hilferty approximation; accurate enough for test thresholds.
    if df <= 0:
        return 0.0
    z = {
        0.10: 1.281551565545,
        0.05: 1.644853626951,
        0.01: 2.326347874041,
        0.001: 3.090232306168,
    }[alpha]
    term = 2.0 / (9.0 * df)
    core = 1.0 - term + z * math.sqrt(term)
    return df * (core ** 3)


def count_roll_signature_hits(pairs, roll_match1, roll_match2=0):
    hits = 0
    for d1, d2 in pairs:
        if roll_matches_signature(d1, d2, roll_match1, roll_match2):
            hits += 1
    return hits


def format_distribution_report(n_rolls=120_000, seed=0):
    """Human-readable distribution report for manual RNG audits."""
    rng = random.Random(seed)
    sim = simulate_rolls(n_rolls, rng=rng)
    die_total = n_rolls * 2
    die_expected = 1.0 / DIE_FACE_COUNT
    die_probs = {face: die_expected for face in range(1, 7)}
    die_chi2 = chi_square_from_counts(sim["die_counts"], die_probs, die_total)

    sum_probs = {s: SUM_OUTCOME_COUNTS[s] / TOTAL_OUTCOMES for s in range(2, 13)}
    sum_chi2 = chi_square_from_counts(sim["sum_counts"], sum_probs, n_rolls)

    lines = [
        f"Dice RNG distribution report ({n_rolls:,} rolls, seed={seed})",
        "",
        "Per-die face counts (two dice per roll):",
    ]
    for face in range(1, 7):
        c = sim["die_counts"][face]
        pct = 100.0 * c / die_total
        lines.append(f"  {face}: {c:7d}  ({pct:5.2f}%, expected 16.67%)")
    lines.append(f"  chi-square (df=5): {die_chi2:.2f}")
    lines.append("")
    lines.append("Dice-sum counts:")
    for s in range(2, 13):
        c = sim["sum_counts"][s]
        exp_pct = 100.0 * sum_probs[s]
        pct = 100.0 * c / n_rolls
        lines.append(f"  sum {s:2d}: {c:6d}  ({pct:5.2f}%, expected {exp_pct:5.2f}%)")
    lines.append(f"  chi-square (df=10): {sum_chi2:.2f}")
    lines.append("")
    lines.append("Citizen roll-match hit rates (harvest signatures):")

    signatures = [
        (1, 0, "1"),
        (3, 0, "3"),
        (6, 0, "6"),
        (7, 8, "7/8"),
        (9, 10, "9/10"),
        (11, 0, "11"),
        (12, 0, "12"),
    ]
    for rm1, rm2, label in signatures:
        expected = analytical_roll_match_probability(rm1, rm2)
        hits = count_roll_signature_hits(sim["pairs"], rm1, rm2)
        pct = 100.0 * hits / n_rolls
        lines.append(
            f"  {label:>4}: {hits:6d} / {n_rolls} = {pct:5.2f}% "
            f"(expected {100.0 * expected:5.2f}%)"
        )

    lines.append("")
    lines.append("Reference: 9/10 citizens (Paladin, Priestess, Templar, ...) match when")
    lines.append("the dice sum is 9 or 10 -> 7/36 ~= 19.44% per roll.")
    return "\n".join(lines)
