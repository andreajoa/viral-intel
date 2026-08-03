import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import Settings
from app.models import PostMetrics
from app.pipeline.main import analyze_content


class PipelineTests(unittest.TestCase):
    def test_deterministic_end_to_end_and_exports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(data_dir=root / "data", local_media_dir=root / "media")
            settings.ensure_dirs()
            now = datetime.now(UTC)
            history = [
                PostMetrics(
                    platform="instagram",
                    format="reel",
                    post_id=f"h{i}",
                    published_at=now - timedelta(hours=24),
                    captured_at=now,
                    followers=1000,
                    views=views,
                    reach=int(views * 0.8),
                    likes=50,
                    comments=5,
                    shares=20,
                    saves=15,
                    source="profile_csv",
                )
                for i, views in enumerate([800, 900, 1000, 1100, 1200, 950, 1050, 980, 1020, 1150])
            ]
            report = analyze_content(
                platform="instagram",
                content_format="reel",
                manual_metrics={
                    "post_id": "target",
                    "published_at": now - timedelta(hours=24),
                    "captured_at": now,
                    "followers": 1000,
                    "views": 1800,
                    "reach": 1500,
                    "likes": 100,
                    "comments": 10,
                    "shares": 35,
                    "saves": 30,
                },
                profile_history=history,
                use_ai=False,
                settings=settings,
            )
            self.assertEqual(report.schema_version, "2.0")
            self.assertEqual(report.provider, "deterministic")
            self.assertTrue((settings.exports_dir / f"{report.report_id}.json").is_file())
            self.assertTrue((settings.exports_dir / f"{report.report_id}.md").is_file())
            self.assertTrue(any(item.kind == "benchmark" for item in report.evidence))

    def test_below_profile_baseline_recommends_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(data_dir=root / "data", local_media_dir=root / "media")
            settings.ensure_dirs()
            now = datetime.now(UTC)
            history = [
                PostMetrics(
                    platform="instagram",
                    format="reel",
                    post_id=f"h{i}",
                    published_at=now - timedelta(hours=48),
                    captured_at=now,
                    followers=1000,
                    views=views,
                    reach=int(views * 0.8),
                    likes=80,
                    comments=10,
                    shares=20,
                    saves=15,
                    source="profile_csv",
                )
                for i, views in enumerate([900, 950, 1000, 1050, 1100, 980, 1020, 970, 1080, 1030])
            ]
            report = analyze_content(
                platform="instagram",
                content_format="reel",
                manual_metrics={
                    "post_id": "target-low",
                    "published_at": now - timedelta(hours=48),
                    "captured_at": now,
                    "followers": 1000,
                    "views": 400,
                    "reach": 320,
                    "likes": 25,
                    "comments": 2,
                    "shares": 3,
                    "saves": 2,
                },
                profile_history=history,
                use_ai=False,
                settings=settings,
            )

            self.assertEqual(report.benchmark.status, "ABAIXO_DO_TÍPICO")
            self.assertEqual(report.strategy["repeat_decision"], "MUDAR")


if __name__ == "__main__":
    unittest.main()
