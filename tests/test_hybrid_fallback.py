import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ai.media_observer import MediaObservation
from app.ai.strategist import deterministic_strategy
from app.config import Settings
from app.models import BenchmarkResult, DataQuality, EvidenceItem, PostMetrics
from app.pipeline.main import analyze_content


class FakeInspector:
    def inspect(self, paths, output_dir):
        return {
            "kind": "carousel",
            "technical": {"slide_count": 2},
            "frames": [b"slide-one", b"slide-two"],
            "transcription": "",
            "transcription_segments": [],
            "warnings": [],
        }


def creative_observation() -> MediaObservation:
    return MediaObservation(
        observed=True,
        asset_type="carousel",
        format_hint="carousel",
        format_confidence=100,
        content_summary="Carrossel que cria tensão sobre confiança em um relacionamento.",
        primary_hook="O que vai ser necessário para você confiar em mim novamente?",
        hook_mechanisms=["tensão", "curiosidade", "identidade"],
        sequence_or_progression=["pergunta conflitante", "resposta que aumenta a tensão"],
        audience_promise="Reconhecer um conflito emocional e acompanhar sua resolução.",
        curiosity_or_tension="A resposta do casal não é revelada na capa.",
        cta_observed="Não identificado",
        emotional_triggers=["identificação", "frustração"],
    )


class HybridFallbackTests(unittest.TestCase):
    def test_deterministic_recovery_uses_creative_observation(self):
        metrics = PostMetrics(platform="instagram", format="carousel")
        evidence = [
            EvidenceItem(
                id="T1",
                kind="technical",
                label="Creative content summary",
                value="Conflito de confiança.",
                source="inspeção local da mídia",
            ),
            EvidenceItem(
                id="T2",
                kind="technical",
                label="Creative primary hook",
                value="Você confia em mim?",
                source="inspeção local da mídia",
            ),
        ]
        report = deterministic_strategy(
            metrics=metrics,
            benchmark=BenchmarkResult(),
            quality=DataQuality(level="BAIXA", completeness_score=0),
            evidence=evidence,
            technical=creative_observation().evidence_context(),
            niche="relacionamentos",
        )

        self.assertEqual(report.repeat_decision, "DADOS_INSUFICIENTES")
        self.assertTrue(any("gancho" in item.title.lower() for item in report.format_insights))
        self.assertTrue(any("O que vai" in hook for hook in report.next_content.hook_options))
        self.assertIn("T1", report.next_content.based_on_refs)
        self.assertTrue(any("CTA explícito" in item for item in report.next_content.change))

    def test_pipeline_reports_hybrid_when_visual_pass_succeeds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(data_dir=root / "data", local_media_dir=root / "media")
            settings.ensure_dirs()

            def strategic_failure(**kwargs):
                recovered = deterministic_strategy(
                    metrics=kwargs["metrics"],
                    benchmark=kwargs["benchmark"],
                    quality=kwargs["quality"],
                    evidence=kwargs["evidence"],
                    technical=kwargs["technical"],
                    niche=kwargs["niche"],
                )
                return (
                    recovered,
                    "deterministic",
                    "evidence-engine-v2",
                    ["gemini: resposta estratégica inválida"],
                )

            with (
                patch(
                    "app.pipeline.main.observe_media",
                    return_value=(creative_observation(), [], "gemini-3.6-flash"),
                ),
                patch(
                    "app.pipeline.main.AIStrategist.analyze",
                    side_effect=strategic_failure,
                ),
            ):
                report = analyze_content(
                    media_paths=[root / "slide.png"],
                    platform="instagram",
                    content_format="carousel",
                    use_ai=True,
                    settings=settings,
                    inspector=FakeInspector(),
                )

            self.assertEqual(report.provider, "hybrid")
            self.assertIn("gemini-3.6-flash", report.model)
            self.assertEqual(report.strategy["repeat_decision"], "DADOS_INSUFICIENTES")
            self.assertTrue(report.provider_errors)
            self.assertIn("tensão", report.strategy["next_content"]["hook_options"][0].lower())


if __name__ == "__main__":
    unittest.main()
