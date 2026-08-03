import unittest
from datetime import UTC, datetime, timedelta

from app.analysis.profile import build_benchmark, summarize_profile
from app.models import PostMetrics

NOW = datetime.now(UTC)


def post(index: int, views: int, age_hours: int = 24, topic: str = "autismo") -> PostMetrics:
    return PostMetrics(
        platform="instagram",
        format="reel",
        post_id=f"p{index}",
        published_at=NOW - timedelta(hours=age_hours),
        captured_at=NOW,
        followers=1000,
        views=views,
        reach=int(views * 0.8),
        likes=int(views * 0.06),
        comments=10,
        shares=int(views * 0.02),
        saves=int(views * 0.015),
        duration_seconds=20,
        average_watch_time_seconds=12,
        topic=topic,
        hook_type="erro_comum",
        cta_type="compartilhar",
        source="profile_csv",
    )


class ProfileBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.history = [
            post(i, value) for i, value in enumerate([800, 900, 1000, 1100, 1200, 950, 1050, 980, 1020, 1150])
        ]

    def test_breakout_requires_reach_and_quality_support(self):
        target = post(99, 3500)
        target.shares = 120
        target.saves = 90
        result = build_benchmark(target, self.history)
        self.assertEqual(result.status, "BREAKOUT")
        self.assertGreater(result.ratio_to_median or 0, 3)
        self.assertEqual(result.comparable_posts, 10)

    def test_fewer_than_five_is_inconclusive(self):
        result = build_benchmark(post(99, 5000), self.history[:4])
        self.assertEqual(result.status, "INCONCLUSIVO")

    def test_below_typical_is_detected_relative_to_profile(self):
        result = build_benchmark(post(99, 500), self.history)
        self.assertEqual(result.status, "ABAIXO_DO_TÍPICO")
        self.assertLess(result.ratio_to_median or 1, 0.75)

    def test_typical_post_is_not_called_a_failure(self):
        result = build_benchmark(post(99, 1000), self.history)
        self.assertEqual(result.status, "TÍPICO")

    def test_paid_posts_do_not_contaminate_organic_baseline(self):
        paid = [post(50 + index, 50000) for index in range(5)]
        for item in paid:
            item.is_paid = True
        result = build_benchmark(post(99, 1000), self.history + paid)
        self.assertEqual(result.comparable_posts, 10)
        self.assertEqual(result.status, "TÍPICO")

    def test_same_lifecycle_is_preferred(self):
        mixed = self.history + [post(50 + i, 9000, age_hours=240) for i in range(5)]
        result = build_benchmark(post(99, 1000, age_hours=24), mixed)
        self.assertEqual(result.comparable_posts, 10)
        self.assertEqual(result.lifecycle_bucket, "1–3d")

    def test_profile_summary_marks_small_samples(self):
        summary = summarize_profile(self.history)
        self.assertEqual(summary["posts"], 10)
        self.assertEqual(summary["topics"][0]["pattern_confidence"], "usable")
        self.assertIn("average_posts_per_week", summary["cadence"])


if __name__ == "__main__":
    unittest.main()
