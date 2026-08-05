from __future__ import annotations

import unittest

from app.ai.reliable_strategist import ReliableAIStrategist
from app.analysis.evidence import build_evidence
from app.analysis.metrics import assess_data_quality, derive_metrics
from app.link_content_guardrails import install_link_content_guardrails
from app.models import BenchmarkResult, ContentFormat, Platform, PostMetrics
from app.runtime_guardrails import install_production_guardrails


class LinkContentGuardrailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        install_production_guardrails()
        install_link_content_guardrails()

    def test_public_caption_is_not_reported_as_missing_creative_content(self):
        metrics = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.IMAGE,
            likes=53,
            source="public",
        )
        benchmark = BenchmarkResult()
        quality = assess_data_quality(metrics, benchmark.comparable_posts)
        technical = {
            "public_caption": (
                "Uma legenda curta apresenta um conflito de relacionamento e cria uma quebra de expectativa."
            ),
            "distribution_diagnosis": {
                "has_distribution_evidence": False,
                "stages": [],
                "likely_distribution_path": [],
            },
        }
        evidence = build_evidence(metrics, derive_metrics(metrics), benchmark, quality, technical)

        strategist = ReliableAIStrategist(provider="disabled")
        report, provider, _model, errors = strategist.analyze(
            metrics=metrics,
            benchmark=benchmark,
            quality=quality,
            evidence=evidence,
            technical=technical,
            transcription="",
            niche="relacionamentos",
            images=[],
        )

        self.assertEqual(provider, "deterministic")
        self.assertEqual(errors, [])
        self.assertIn("legenda pública foi analisada", report.executive_summary.lower())
        self.assertIn("Diagnóstico textual: disponível", report.performance_interpretation)
        self.assertNotIn("não forneceu elementos criativos", report.executive_summary.lower())
        self.assertTrue(any(item.title == "Síntese da leitura textual" for item in report.format_insights))
        self.assertTrue(any(item.title == "Alcance real desta análise" for item in report.format_insights))
        self.assertTrue(
            any(
                item.title == "Mecanismo textual provável de ressonância" and item.judgment == "PLAUSÍVEL"
                for item in report.root_cause_hypotheses
            )
        )


if __name__ == "__main__":
    unittest.main()
