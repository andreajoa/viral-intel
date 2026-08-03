import unittest
from datetime import UTC, datetime, timedelta

from app.analysis.metrics import assess_data_quality, derive_metrics
from app.models import PostMetrics


class MetricTests(unittest.TestCase):
    def test_missing_is_not_zero(self):
        metrics = PostMetrics(platform="instagram", format="reel", views=1000, likes=100)
        derived = derive_metrics(metrics)
        self.assertEqual(derived["interactions_known"], 100)
        self.assertEqual(derived["engagement_by_views_pct"], 10)
        self.assertNotIn("share_rate_by_views_pct", derived)
        self.assertNotIn("save_rate_by_views_pct", derived)

    def test_zero_is_a_real_observation(self):
        metrics = PostMetrics(
            platform="instagram", format="reel", views=1000, likes=0, comments=0, shares=0, saves=0
        )
        derived = derive_metrics(metrics)
        self.assertEqual(derived["interactions_known"], 0)
        self.assertEqual(derived["share_rate_by_views_pct"], 0)

    def test_watch_percentage_is_calculated(self):
        metrics = PostMetrics(
            platform="tiktok",
            format="video",
            duration_seconds=20,
            average_watch_time_seconds=15,
        )
        self.assertEqual(derive_metrics(metrics)["average_view_percentage"], 75)

    def test_public_snapshot_without_baseline_has_low_confidence(self):
        metrics = PostMetrics(platform="instagram", format="reel", views=1000, source="public")
        quality = assess_data_quality(metrics, comparable_posts=0)
        self.assertEqual(quality.level, "BAIXA")
        self.assertTrue(any("Dados públicos" in item for item in quality.limitations))

    def test_average_views_per_hour_is_not_called_velocity(self):
        now = datetime.now(UTC)
        metrics = PostMetrics(
            platform="youtube",
            format="short",
            views=2400,
            published_at=now - timedelta(hours=24),
            captured_at=now,
        )
        derived = derive_metrics(metrics)
        self.assertEqual(derived["average_views_per_hour_since_publish"], 100)


if __name__ == "__main__":
    unittest.main()
