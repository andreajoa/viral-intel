from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.models import AnalysisEnvelope, BenchmarkResult, DataQuality, PostMetrics
from app.storage import IntelligenceStore


class IntelligenceStoreV5Tests(unittest.TestCase):
    def _report(self, report_id: str, views: int, captured_at: str) -> AnalysisEnvelope:
        return AnalysisEnvelope(
            report_id=report_id,
            metrics=PostMetrics(
                platform="instagram",
                format="reel",
                post_id="post-1",
                captured_at=captured_at,
                views=views,
                likes=10,
            ),
            derived_metrics={},
            benchmark=BenchmarkResult(),
            data_quality=DataQuality(level="BAIXA", completeness_score=10),
            evidence=[],
            content_fingerprint={
                "platform": "instagram",
                "format": "reel",
                "content_tokens": ["autismo", "fala"],
            },
        )

    def test_persists_reports_and_builds_post_timeline(self):
        with tempfile.TemporaryDirectory(prefix="viral-intel-store-") as temp_dir:
            store = IntelligenceStore(Path(temp_dir) / "intel.sqlite3")
            first = self._report("r1", 100, "2026-08-22T10:00:00+00:00")
            second = self._report("r2", 250, "2026-08-22T12:00:00+00:00")
            store.save_report(first, profile_key="instagram:id:1", post_key="post-1")
            store.save_report(second, profile_key="instagram:id:1", post_key="post-1")

            summary = store.longitudinal_summary(profile_key="instagram:id:1", post_key="post-1")
            self.assertTrue(summary["available"])
            self.assertEqual(summary["snapshots"], 2)
            self.assertEqual(summary["deltas"]["views"], 150.0)

    def test_comparable_reports_are_scoped_to_profile_and_format(self):
        with tempfile.TemporaryDirectory(prefix="viral-intel-store-") as temp_dir:
            store = IntelligenceStore(Path(temp_dir) / "intel.sqlite3")
            report = self._report("r1", 1000, "2026-08-22T10:00:00+00:00")
            store.save_report(report, profile_key="instagram:id:1", post_key="post-1")
            rows = store.comparable_reports(
                profile_key="instagram:id:1",
                platform="instagram",
                content_format="reel",
            )
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["metrics"]["views"], 1000)


if __name__ == "__main__":
    unittest.main()
