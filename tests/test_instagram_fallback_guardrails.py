from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.ai.strategist import deterministic_strategy
from app.analysis.evidence import build_evidence
from app.analysis.metrics import assess_data_quality, derive_metrics
from app.analysis.text_content import analyze_text_content
from app.instagram_fallback_guardrails import (
    _reconcile_manual_text_report,
    _replace_empty_blocked_report,
)
from app.models import BenchmarkResult, ContentFormat, Platform, PostMetrics


class InstagramFallbackGuardrailTests(unittest.TestCase):
    def test_text_analysis_extracts_conflict_emotion_and_cta(self):
        analysis = analyze_text_content(
            "Você confiaria novamente depois de descobrir uma traição? "
            "Ela encontrou a verdade, mas decidiu recomeçar. Compartilhe com alguém que precisa ler isso."
        )

        self.assertIn("conflito de relacionamento", analysis["creative_hook_mechanisms"])
        self.assertIn("contraste ou quebra de expectativa", analysis["creative_hook_mechanisms"])
        self.assertIn("traição", analysis["creative_emotional_triggers"])
        self.assertIn("Compartilhe", analysis["creative_cta_observed"])
        self.assertTrue(analysis["creative_primary_hook"].startswith("Você confiaria"))

    def test_manual_text_replaces_empty_creative_summary(self):
        metrics = PostMetrics(platform=Platform.INSTAGRAM, format=ContentFormat.IMAGE)
        benchmark = BenchmarkResult()
        quality = assess_data_quality(metrics, benchmark.comparable_posts)
        technical = {
            "manual_caption": "Uma história de relacionamento com quebra de expectativa.",
            **analyze_text_content(
                "Ele dizia que estava tudo bem, mas escondia a verdade. "
                "A descoberta muda o sentido da história."
            ),
        }
        evidence = build_evidence(metrics, derive_metrics(metrics), benchmark, quality, technical)
        strategy = deterministic_strategy(metrics, benchmark, quality, evidence, technical, "relacionamentos")
        envelope = SimpleNamespace(
            strategy=strategy.model_dump(mode="json"),
            evidence=evidence,
            technical_analysis=technical,
        )

        _reconcile_manual_text_report(envelope)

        self.assertNotIn("não forneceu elementos criativos", envelope.strategy["executive_summary"].lower())
        self.assertTrue(
            any(
                item["title"] == "Fonte utilizada nesta análise"
                for item in envelope.strategy["format_insights"]
            )
        )
        self.assertEqual(envelope.technical_analysis["content_input_status"], "manual_text_available")

    def test_blocked_collection_does_not_generate_generic_content_advice(self):
        metrics = PostMetrics(platform=Platform.INSTAGRAM, format=ContentFormat.IMAGE)
        benchmark = BenchmarkResult()
        quality = assess_data_quality(metrics, benchmark.comparable_posts)
        strategy = deterministic_strategy(metrics, benchmark, quality, [], {}, "relacionamentos")
        envelope = SimpleNamespace(
            strategy=strategy.model_dump(mode="json"),
            metrics=metrics,
            technical_analysis={},
        )

        _replace_empty_blocked_report(envelope)

        self.assertIn("bloqueou", envelope.strategy["executive_summary"].lower())
        self.assertEqual(envelope.strategy["root_cause_hypotheses"], [])
        self.assertIn("Cole a legenda", envelope.strategy["next_content"]["hook_options"][0])
        self.assertEqual(
            envelope.technical_analysis["content_input_status"],
            "instagram_collection_blocked",
        )


if __name__ == "__main__":
    unittest.main()
