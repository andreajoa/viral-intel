from __future__ import annotations

import unittest

from app.analysis.distribution import build_distribution_diagnosis
from app.analysis.metrics import derive_metrics
from app.models import BenchmarkResult, ContentFormat, Platform, PostMetrics


class DistributionDiagnosisTests(unittest.TestCase):
    def test_reconstructs_circulation_and_non_follower_expansion(self):
        metrics = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.IMAGE,
            followers=14000,
            reach=120000,
            views=130000,
            likes=33800,
            comments=132,
            shares=4200,
            reposts=5400,
            saves=3100,
            follows=640,
            profile_visits=4200,
            non_follower_reach_rate=84,
            recommendation_eligibility="eligible",
            is_original=True,
        )
        benchmark = BenchmarkResult(
            status="BREAKOUT",
            label="Breakout no próprio perfil",
            comparable_posts=20,
            primary_metric="reach",
            target_value=120000,
            median_value=18000,
            ratio_to_median=6.6667,
            percentile=100,
        )

        result = build_distribution_diagnosis(
            metrics=metrics,
            derived=derive_metrics(metrics),
            benchmark=benchmark,
            technical={
                "recommendation_eligibility": "eligible",
                "original_content": True,
            },
            comment_summary={
                "available": True,
                "sample_size": 80,
                "mention_rate_pct": 15,
                "intent_distribution": [
                    {"intent": "identificação pessoal", "count": 35},
                    {"intent": "marcação ou envio", "count": 18},
                ],
            },
            data_access_level="official_authorized",
        )

        statuses = {stage["stage"]: stage["status"] for stage in result["stages"]}
        self.assertEqual(statuses["Elegibilidade para recomendação"], "COMPROVADO")
        self.assertEqual(statuses["Expansão para não seguidores"], "COMPROVADO")
        self.assertIn("distribuição majoritária para não seguidores", result["strongest_observed_signals"])
        self.assertTrue(any("ultrapassou a base" in item for item in result["likely_distribution_path"]))
        self.assertTrue(
            any("identidade individual" in item for item in result["cannot_be_known_from_current_data"])
        )

    def test_missing_distribution_data_is_not_converted_to_failure(self):
        metrics = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.IMAGE,
            likes=100,
            comments=5,
        )
        result = build_distribution_diagnosis(
            metrics=metrics,
            derived=derive_metrics(metrics),
            benchmark=BenchmarkResult(),
        )
        statuses = {stage["stage"]: stage["status"] for stage in result["stages"]}
        self.assertEqual(statuses["Expansão para não seguidores"], "NÃO_AVALIÁVEL")
        self.assertIn("alcance total e porcentagem de não seguidores", result["minimum_data_to_improve"])


if __name__ == "__main__":
    unittest.main()
