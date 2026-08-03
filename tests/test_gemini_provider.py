import json
import sys
import tempfile
import types as python_types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.strategist import AIStrategist, _gemini_json_schema
from app.config import Settings
from app.models import BenchmarkResult, DataQuality, PostMetrics


class _Part:
    @staticmethod
    def from_text(*, text):
        return {"type": "text", "text": text}

    @staticmethod
    def from_bytes(*, data, mime_type):
        return {"type": "image", "data": data, "mime_type": mime_type}


class _GenerateContentConfig(dict):
    def __init__(self, **kwargs):
        super().__init__(kwargs)


VALID_REPORT = json.dumps(
    {
        "executive_summary": "Leitura baseada nas evidências disponíveis.",
        "performance_interpretation": "O desempenho ainda não pode ser classificado.",
        "repeat_decision": "DADOS_INSUFICIENTES",
        "root_cause_hypotheses": [],
        "format_insights": [],
        "profile_insights": [],
        "audience_insights": [],
        "next_content": {
            "format": "carousel",
            "objective": "Testar o gancho observado.",
            "hook_options": ["Gancho A", "Gancho B"],
            "structure": ["Capa", "Desenvolvimento", "CTA"],
            "caption_direction": "Contextualize sem inventar dados.",
            "cta": "Salve para rever.",
            "preserve": [],
            "change": [],
            "based_on_refs": [],
        },
        "experiments": [
            {
                "hypothesis": "O gancho melhora a abertura.",
                "change_one_thing": "Gancho",
                "keep_constant": ["tema"],
                "primary_metric": "alcance",
                "comparison_rule": "Mesmo estágio de vida.",
                "minimum_sample": "3 posts",
                "based_on_refs": [],
            }
        ],
        "caveats": [],
    },
    ensure_ascii=False,
)


def _fake_modules(client):
    google_module = python_types.ModuleType("google")
    genai_module = python_types.ModuleType("google.genai")
    genai_module.Client = lambda **_kwargs: client
    genai_module.types = SimpleNamespace(
        Part=_Part,
        GenerateContentConfig=_GenerateContentConfig,
    )
    google_module.genai = genai_module
    return {"google": google_module, "google.genai": genai_module}


class GeminiProviderTests(unittest.TestCase):
    def _strategist(self, root: Path) -> AIStrategist:
        settings = Settings(
            data_dir=root / "data",
            local_media_dir=root / "media",
            google_api_key="configured-test-key",
            gemini_model="gemini-3.6-flash",
        )
        settings.ensure_dirs()
        return AIStrategist(settings=settings)

    def test_gemini_schema_drops_unsupported_pydantic_keywords(self):
        serialized = str(_gemini_json_schema())
        self.assertNotIn("'default'", serialized)
        self.assertNotIn("'maxLength'", serialized)
        self.assertIn("'additionalProperties': False", serialized)

    def test_plain_generate_content_sends_system_prompt_and_image(self):
        captured = {}

        class Models:
            @staticmethod
            def generate_content(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(text=VALID_REPORT)

        client = SimpleNamespace(models=Models(), close=lambda: None)
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(sys.modules, _fake_modules(client), clear=False),
        ):
            raw, model = self._strategist(Path(temp))._call_gemini("prompt", [b"image"])

        self.assertEqual(raw, VALID_REPORT)
        self.assertEqual(model, "gemini-3.6-flash")
        self.assertIn("orientado por evidências", captured["contents"][0]["text"])
        self.assertEqual(captured["contents"][1]["type"], "image")

    def test_generate_content_recovers_with_fallback_model(self):
        models_called = []

        class Models:
            @staticmethod
            def generate_content(**kwargs):
                models_called.append(kwargs["model"])
                if kwargs["model"] == "gemini-3.6-flash":
                    raise RuntimeError("temporary failure")
                return SimpleNamespace(text=VALID_REPORT)

        client = SimpleNamespace(models=Models(), close=lambda: None)
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(sys.modules, _fake_modules(client), clear=False),
        ):
            raw, _ = self._strategist(Path(temp))._call_gemini("prompt", [])

        self.assertEqual(raw, VALID_REPORT)
        self.assertEqual(models_called, ["gemini-3.6-flash", "gemini-3.5-flash"])

    def test_openai_adapter_uses_responses_structured_output(self):
        captured = {}

        class Responses:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(output_text=VALID_REPORT)

        client = SimpleNamespace(responses=Responses())
        with tempfile.TemporaryDirectory() as temp, patch("openai.OpenAI", return_value=client):
            root = Path(temp)
            settings = Settings(
                data_dir=root / "data",
                local_media_dir=root / "media",
                openai_api_key="configured-test-key",
            )
            raw, model = AIStrategist(settings=settings)._call_openai("prompt", [b"image"])

        self.assertEqual(raw, VALID_REPORT)
        self.assertEqual(model, settings.openai_model)
        self.assertFalse(captured["store"])
        self.assertEqual(captured["text"]["format"]["type"], "json_schema")
        self.assertEqual(captured["input"][0]["content"][1]["type"], "input_image")

    def test_anthropic_adapter_uses_structured_output(self):
        captured = {}

        class Messages:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=VALID_REPORT)])

        client = SimpleNamespace(messages=Messages())
        with tempfile.TemporaryDirectory() as temp, patch("anthropic.Anthropic", return_value=client):
            root = Path(temp)
            settings = Settings(
                data_dir=root / "data",
                local_media_dir=root / "media",
                anthropic_api_key="configured-test-key",
            )
            raw, model = AIStrategist(settings=settings)._call_anthropic("prompt", [b"image"])

        self.assertEqual(raw, VALID_REPORT)
        self.assertEqual(model, settings.anthropic_model)
        self.assertEqual(captured["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(captured["messages"][0]["content"][0]["type"], "image")

    def test_provider_failure_falls_through_to_next_configured_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            settings = Settings(
                data_dir=root / "data",
                local_media_dir=root / "media",
                google_api_key="gemini-test-key",
                openai_api_key="openai-test-key",
                provider_order=("gemini", "openai"),
            )
            strategist = AIStrategist(settings=settings)
            with (
                patch.object(strategist, "_call_gemini", side_effect=RuntimeError("temporary")),
                patch.object(strategist, "_call_openai", return_value=(VALID_REPORT, "test-model")),
            ):
                report, provider, model, errors = strategist.analyze(
                    metrics=PostMetrics(platform="instagram", format="image"),
                    benchmark=BenchmarkResult(),
                    quality=DataQuality(level="BAIXA", completeness_score=0),
                    evidence=[],
                    technical={},
                    transcription="",
                )

        self.assertEqual(report.repeat_decision, "DADOS_INSUFICIENTES")
        self.assertEqual(provider, "openai")
        self.assertEqual(model, "test-model")
        self.assertEqual(len(errors), 1)
        self.assertIn("gemini", errors[0])


if __name__ == "__main__":
    unittest.main()
