from __future__ import annotations

import unittest

from app.ai.reliable_strategist import ReliableAIStrategist
from app.analysis.evidence import build_evidence
from app.analysis.metrics import assess_data_quality, derive_metrics
from app.analysis.text_content import analyze_text_content
from app.models import BenchmarkResult, ContentFormat, Platform, PostMetrics


class PublicCaptionCoreTests(unittest.TestCase):
    def test_public_caption_is_analyzed_without_runtime_monkey_patch(self):
        caption = (
            "Você confiaria novamente depois de uma quebra de expectativa? "
            "A história muda quando a verdade aparece. Compartilhe com alguém que precisa ler isso."
        )
        metrics = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.IMAGE,
            likes=53,
            source="public",
        )
        benchmark = BenchmarkResult()
        quality = assess_data_quality(metrics, benchmark.comparable_posts)
        technical = {
            "public_caption": caption,
            **analyze_text_content(caption),
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
        self.assertNotIn("não forneceu elementos criativos", report.executive_summary.lower())
        self.assertTrue(
            any(item.title == "Leitura do gancho e da estrutura" for item in report.format_insights)
        )
        self.assertTrue(
            any(
                item.title == "Mecanismo criativo candidato a explicar o resultado"
                for item in report.root_cause_hypotheses
            )
        )


if __name__ == "__main__":
    unittest.main()
