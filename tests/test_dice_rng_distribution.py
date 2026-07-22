import random
import unittest

from cards import Citizen
from dice_rng import (
    TOTAL_OUTCOMES,
    analytical_roll_match_probability,
    chi_square_critical_value,
    chi_square_from_counts,
    count_roll_signature_hits,
    format_distribution_report,
    roll_dice_pair,
    roll_die,
    roll_matches_signature,
    simulate_rolls,
    SUM_OUTCOME_COUNTS,
)
from game import Game
from game_models import Player
from game_setup import DEBUG_DIE_ONE_VALUES, DEBUG_DIE_TWO_VALUES


class CanonicalPrimitiveTests(unittest.TestCase):
    """The engine and the audit code must share one roll primitive."""

    def test_roll_dice_pair_reproduces_raw_randint_sequence(self):
        # roll_dice_pair (non-debug) must be byte-for-byte the two randint(1,6)
        # draws that roll_phase historically inlined.
        rng_a = random.Random(0)
        rng_b = random.Random(0)
        expected = (rng_b.randint(1, 6), rng_b.randint(1, 6))
        self.assertEqual(roll_dice_pair(debug_mode=False, rng=rng_a), expected)

    def test_roll_die_reproduces_raw_randint(self):
        rng_a = random.Random(3)
        rng_b = random.Random(3)
        self.assertEqual(roll_die(rng=rng_a), rng_b.randint(1, 6))

    def test_roll_dice_pair_debug_mode_uses_constrained_sets(self):
        rng = random.Random(11)
        for _ in range(500):
            d1, d2 = roll_dice_pair(debug_mode=True, rng=rng)
            self.assertIn(d1, DEBUG_DIE_ONE_VALUES)
            self.assertIn(d2, DEBUG_DIE_TWO_VALUES)


class RollMatchAnalyticalTests(unittest.TestCase):
    def test_nine_ten_signature_is_sum_nine_or_ten_only(self):
        # Dice faces are 1..6, so rm1=9 only matches via sum; rm2=10 matches sum 10.
        self.assertEqual(analytical_roll_match_probability(9, 10), 7 / 36)

        matching = []
        for d1 in range(1, 7):
            for d2 in range(1, 7):
                if roll_matches_signature(d1, d2, 9, 10):
                    matching.append((d1, d2))
        self.assertEqual(len(matching), 7)
        self.assertEqual({d1 + d2 for d1, d2 in matching}, {9, 10})

    def test_signature_helper_matches_engine_harvest_count(self):
        # dice_rng.roll_matches_signature must agree with the engine's own
        # HarvestEngine._roll_match_count across every possible roll.
        game, _ = _minimal_game()
        harvest = game.harvest
        for d1 in range(1, 7):
            for d2 in range(1, 7):
                game.die_one = d1
                game.die_two = d2
                game.die_sum = d1 + d2
                card = Citizen(
                    1, "Probe", 2, 9, 10,
                    0, 0, 0, 0,
                    0, 0, 0, 0, 0, 0,
                    0, 0,
                    False, False, "", "",
                    False, "test",
                )
                ok, _count = harvest._roll_match_count(card)
                self.assertEqual(ok, roll_matches_signature(d1, d2, 9, 10))


class DiceRngDistributionTests(unittest.TestCase):
    SAMPLE_ROLLS = 120_000
    ALPHA = 0.001

    def test_production_die_faces_are_uniform(self):
        rng = random.Random(42)
        sim = simulate_rolls(self.SAMPLE_ROLLS, rng=rng)
        die_total = self.SAMPLE_ROLLS * 2
        expected = {face: 1.0 / 6 for face in range(1, 7)}
        chi2 = chi_square_from_counts(sim["die_counts"], expected, die_total)
        critical = chi_square_critical_value(df=5, alpha=self.ALPHA)
        self.assertLess(
            chi2,
            critical,
            f"Die-face chi-square {chi2:.2f} exceeds critical {critical:.2f}",
        )

    def test_production_sum_distribution_matches_two_d6(self):
        rng = random.Random(99)
        sim = simulate_rolls(self.SAMPLE_ROLLS, rng=rng)
        expected = {s: SUM_OUTCOME_COUNTS[s] / TOTAL_OUTCOMES for s in range(2, 13)}
        chi2 = chi_square_from_counts(sim["sum_counts"], expected, self.SAMPLE_ROLLS)
        critical = chi_square_critical_value(df=10, alpha=self.ALPHA)
        self.assertLess(
            chi2,
            critical,
            f"Sum chi-square {chi2:.2f} exceeds critical {critical:.2f}",
        )

    def test_nine_ten_empirical_rate_near_analytical(self):
        rng = random.Random(7)
        sim = simulate_rolls(self.SAMPLE_ROLLS, rng=rng)
        expected = analytical_roll_match_probability(9, 10)
        hits = count_roll_signature_hits(sim["pairs"], 9, 10)
        rate = hits / self.SAMPLE_ROLLS
        # Wilson interval half-width ~0.3% at n=120k; allow 1.5% absolute slack.
        self.assertAlmostEqual(rate, expected, delta=0.015)

    def test_common_signatures_track_analytical_rates(self):
        rng = random.Random(12345)
        sim = simulate_rolls(self.SAMPLE_ROLLS, rng=rng)
        signatures = [(1, 0), (3, 0), (6, 0), (7, 8), (9, 10), (11, 0), (12, 0)]
        for rm1, rm2 in signatures:
            expected = analytical_roll_match_probability(rm1, rm2)
            hits = count_roll_signature_hits(sim["pairs"], rm1, rm2)
            rate = hits / self.SAMPLE_ROLLS
            self.assertAlmostEqual(
                rate,
                expected,
                delta=0.015,
                msg=f"roll_match {rm1}/{rm2}: observed {rate:.4f}, expected {expected:.4f}",
            )


class EngineRollPathTests(unittest.TestCase):
    """Drive the real roll_phase to prove it goes through the shared primitive."""

    def test_roll_phase_draws_from_full_d6_range_in_production(self):
        game = _minimal_roll_game(debug_mode=False)
        seen_one = set()
        seen_two = set()
        for seed in range(200):
            random.seed(seed)
            game.phase = "roll"
            game.lifecycle.roll_phase()
            seen_one.add(game.rolled_die_one)
            seen_two.add(game.rolled_die_two)
        self.assertEqual(seen_one, {1, 2, 3, 4, 5, 6})
        self.assertEqual(seen_two, {1, 2, 3, 4, 5, 6})

    def test_roll_phase_matches_roll_dice_pair_under_same_seed(self):
        # Because roll_phase now delegates to roll_dice_pair on the global RNG,
        # seeding the module RNG must yield identical dice from both paths.
        game = _minimal_roll_game(debug_mode=False)
        random.seed(2024)
        game.phase = "roll"
        game.lifecycle.roll_phase()
        engine_pair = (game.rolled_die_one, game.rolled_die_two)

        random.seed(2024)
        self.assertEqual(roll_dice_pair(debug_mode=False), engine_pair)

    def test_debug_mode_constrains_natural_roll_values(self):
        game = _minimal_roll_game(debug_mode=True)
        for seed in range(200):
            random.seed(seed)
            game.phase = "roll"
            game.lifecycle.roll_phase()
            self.assertIn(game.rolled_die_one, DEBUG_DIE_ONE_VALUES)
            self.assertIn(game.rolled_die_two, DEBUG_DIE_TWO_VALUES)


def _minimal_game():
    p1 = Player("p1", "Player 1")
    game = Game({
        "game_id": "dice-rng-test",
        "player_list": [p1],
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "dice-rng-test", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "harvest",
    })
    return game, [p1]


def _minimal_roll_game(debug_mode=False):
    p1 = Player("p1", "Player 1")
    return Game({
        "game_id": "dice-rng-roll-test",
        "player_list": [p1],
        "monster_grid": [],
        "citizen_grid": [],
        "domain_grid": [],
        "die_one": 1,
        "die_two": 2,
        "die_sum": 3,
        "exhausted_count": 0,
        "exhausted_stack": [],
        "effects": {},
        "action_required": {"id": "dice-rng-roll-test", "action": ""},
        "game_log": [],
        "turn_index": 0,
        "phase": "roll",
        "debug_mode": debug_mode,
    })


class ReportSmokeTest(unittest.TestCase):
    def test_format_distribution_report_runs(self):
        report = format_distribution_report(n_rolls=6_000, seed=1)
        self.assertIn("9/10", report)
        self.assertIn("19.44%", report)


if __name__ == "__main__":
    unittest.main()
