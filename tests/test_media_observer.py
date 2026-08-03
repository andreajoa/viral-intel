import unittest

from app.ai.media_observer import MediaObservation, observe_media
from app.config import Settings


class MediaObservationTests(unittest.TestCase):
    def test_missing_gemini_key_is_supported_offline_mode(self):
        observation, errors, model = observe_media(
            settings=Settings(google_api_key=""),
            images=[b"not-decoded-without-a-provider"],
            technical={},
            transcription="",
        )

        self.assertIsNone(observation)
        self.assertEqual(errors, [])
        self.assertEqual(model, "")

    def test_probability_style_confidence_is_normalized_to_percent(self):
        observation = MediaObservation.model_validate(
            {
                "format_hint": "carousel",
                "format_confidence": 1,
                "visible_metrics": [
                    {
                        "metric": "comments",
                        "value": 351,
                        "confidence": 0.98,
                    }
                ],
            }
        )
        self.assertEqual(observation.format_confidence, 100)
        self.assertEqual(observation.visible_metrics[0].confidence, 98)

    def test_only_high_confidence_visible_metrics_are_prefilled(self):
        observation = MediaObservation.model_validate(
            {
                "observed": True,
                "asset_type": "social_screenshot",
                "format_hint": "carousel",
                "format_confidence": 98,
                "visible_metrics": [
                    {
                        "metric": "likes",
                        "value": 18100,
                        "displayed_text": "18.1K",
                        "visual_evidence": "número ao lado do coração",
                        "confidence": 98,
                    },
                    {
                        "metric": "shares",
                        "value": 1500,
                        "displayed_text": "1.5K",
                        "visual_evidence": "ícone ambíguo",
                        "confidence": 70,
                    },
                ],
            }
        )
        self.assertEqual(observation.metrics_for_prefill(), {"likes": 18100})

    def test_creative_fields_become_evidence_context(self):
        observation = MediaObservation(
            observed=True,
            asset_type="carousel",
            format_hint="carousel",
            format_confidence=99,
            content_summary="Capa de relacionamento com contraste e tensão.",
            primary_hook="MULHER CASADA NÃO FAZ ISSO",
            hook_mechanisms=["curiosidade", "identidade"],
        )
        context = observation.evidence_context()
        self.assertEqual(context["creative_primary_hook"], "MULHER CASADA NÃO FAZ ISSO")
        self.assertIn("creative_hook_mechanisms", context)


if __name__ == "__main__":
    unittest.main()
