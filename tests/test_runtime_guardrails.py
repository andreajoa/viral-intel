from __future__ import annotations

import unittest

from app.ai.media_observer import MediaObservation, VisibleMetric
from app.analysis.distribution import build_distribution_diagnosis
from app.models import BenchmarkResult, ContentFormat, Platform, PostMetrics
from app.runtime_guardrails import install_production_guardrails


class RuntimeGuardrailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_production_guardrails()

    def test_unverified_zero_is_not_used(self):
        observation = MediaObservation(
            observed=True,
            asset_type="social_screenshot",
            visible_metrics=[
                VisibleMetric(
                    metric="likes",
                    value=53,
                    displayed_text="53",
                    visual_evidence="53 ao lado do coração",
                    confidence=98,
                ),
                VisibleMetric(
                    metric="comments",
                    value=0,
                    displayed_text="",
                    visual_evidence="balão sem número legível",
                    confidence=90,
                ),
            ],
        )
        self.assertEqual(observation.metrics_for_prefill(), {"likes": 53})

    def test_explicit_zero_is_used(self):
        observation = MediaObservation(
            observed=True,
            asset_type="social_screenshot",
            visible_metrics=[
                VisibleMetric(
                    metric="comments",
                    value=0,
                    displayed_text="0",
                    visual_evidence="0 ao lado do balão de comentários",
                    confidence=98,
                )
            ],
        )
        self.assertEqual(observation.metrics_for_prefill(), {"comments": 0})

    def test_empty_distribution_has_no_probable_path(self):
        metrics = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.IMAGE,
            likes=53,
        )
        diagnosis = build_distribution_diagnosis(
            metrics=metrics,
            derived={},
            benchmark=BenchmarkResult(),
        )
        self.assertFalse(diagnosis["has_distribution_evidence"])
        self.assertEqual(diagnosis["stages"], [])
        self.assertEqual(diagnosis["likely_distribution_path"], [])
        self.assertIn("Ausência de dado não significa baixa entrega", diagnosis["verdict"])


if __name__ == "__main__":
    unittest.main()
