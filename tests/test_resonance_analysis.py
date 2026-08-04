from __future__ import annotations

import unittest

from app.ai.reliable_strategist import ReliableAIStrategist
from app.analysis.evidence import build_evidence
from app.analysis.metrics import assess_data_quality, derive_metrics
from app.models import BenchmarkResult, ContentFormat, Platform, PostMetrics


class ResonanceAnalysisTests(unittest.TestCase):
    def test_inconclusive_baseline_still_explains_resonance(self):
        metrics = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.IMAGE,
            likes=33800,
            comments=132,
            reposts=5400,
            source="screenshot",
            source_notes=["Métricas lidas da captura enviada."],
        )
        derived = derive_metrics(metrics)
        benchmark = BenchmarkResult()
        quality = assess_data_quality(metrics, benchmark.comparable_posts)
        technical = {
            "creative_content_summary": (
                "Frase manuscrita sobre perder alguém insubstituível, apresentada em um caderno."
            ),
            "creative_primary_hook": "Você não perdeu qualquer pessoa...",
            "creative_hook_mechanisms": [
                "contraste",
                "tensão emocional",
                "identificação pessoal",
            ],
            "creative_emotional_triggers": ["saudade", "perda", "exclusividade"],
            "creative_curiosity_or_tension": (
                "A frase começa minimizando a perda e termina tornando a pessoa insubstituível."
            ),
            "creative_style_signals": [
                "escrita à mão",
                "caderno pautado",
                "marcas semelhantes a lágrimas",
            ],
            "creative_visual_structure": ["texto central", "fundo simples", "leitura imediata"],
            "creative_cta_observed": "ausente",
        }
        evidence = build_evidence(metrics, derived, benchmark, quality, technical)

        strategist = ReliableAIStrategist(provider="disabled")
        report, provider, _model, errors = strategist.analyze(
            metrics=metrics,
            benchmark=benchmark,
            quality=quality,
            evidence=evidence,
            technical=technical,
            transcription="",
            niche="frases de relacionamento e superação",
            images=[],
        )

        self.assertEqual(provider, "deterministic")
        self.assertEqual(errors, [])
        self.assertEqual(report.repeat_decision, "DADOS_INSUFICIENTES")
        self.assertIn("Diagnóstico criativo: disponível", report.performance_interpretation)
        self.assertTrue(
            any(
                hypothesis.judgment == "PLAUSÍVEL"
                and "Ressonância emocional" in hypothesis.title
                and "redistribuição" in hypothesis.finding
                and "aparência íntima" in hypothesis.finding
                and "mensagem pronta" in hypothesis.finding
                for hypothesis in report.root_cause_hypotheses
            )
        )
        self.assertTrue(
            any("Padrão de resposta visível" == insight.title for insight in report.audience_insights)
        )
        self.assertTrue(
            any("Arquitetura criativa observada" == insight.title for insight in report.format_insights)
        )
        self.assertIn("Não interrompa a arte", report.next_content.cta)
        self.assertTrue(
            any("sem CTA intrusivo" in item for item in report.next_content.preserve)
        )

    def test_composition_metrics_do_not_require_views_or_reach(self):
        metrics = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.IMAGE,
            likes=33800,
            comments=132,
            reposts=5400,
        )

        derived = derive_metrics(metrics)

        self.assertAlmostEqual(derived["circulation_to_likes_pct"], 15.9763, places=4)
        self.assertAlmostEqual(derived["comments_to_likes_pct"], 0.3905, places=4)
        self.assertAlmostEqual(derived["circulation_to_comments_ratio"], 40.9091, places=4)
        self.assertEqual(derived["circulation_actions_known"], 5400.0)


if __name__ == "__main__":
    unittest.main()
