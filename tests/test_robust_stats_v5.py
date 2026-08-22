from __future__ import annotations

import unittest

from app.analysis.robust_stats import percentile, robust_expected_range


class RobustStatsV5Tests(unittest.TestCase):
    def test_profile_specific_interval_detects_large_positive_anomaly(self):
        values = [800, 900, 950, 980, 1000, 1020, 1050, 1100, 1150, 1200]
        result = robust_expected_range(values, 3500)
        self.assertIsNotNone(result["expected_high"])
        self.assertGreater(result["robust_z_score"] or 0, 2.5)
        self.assertGreater(3500, result["expected_high"] or 0)
        self.assertEqual(result["evidence_strength"], "MODERADA")

    def test_interval_is_not_a_fixed_multiple_rule(self):
        tight = robust_expected_range([990, 995, 1000, 1005, 1010, 1002, 998, 1001], 1200)
        wide = robust_expected_range([500, 700, 900, 1100, 1300, 1500, 1700, 1900], 1200)
        self.assertLess(tight["expected_high"] or 0, wide["expected_high"] or 0)

    def test_percentile_uses_midrank_for_ties(self):
        self.assertEqual(percentile([10, 20, 20, 30], 20), 50.0)


if __name__ == "__main__":
    unittest.main()
