from __future__ import annotations

import json
import sys
import tempfile
import types as python_types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.strategist import AIStrategist
from app.config import Settings

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


class GeminiInteractionTests(unittest.TestCase):
    def _strategist(self, root: Path) -> AIStrategist:
        settings = Settings(
            data_dir=root / "data",
            local_media_dir=root / "media",
            google_api_key="configured-test-key",
            gemini_model="gemini-3.6-flash",
        )
        settings.ensure_dirs()
        return AIStrategist(settings=settings)

    def test_uses_official_interactions_structured_output(self):
        captured = {}

        class Interactions:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(output_text=VALID_REPORT)

        class Models:
            @staticmethod
            def generate_content(**_kwargs):
                raise AssertionError("fallback should not run")

        client = SimpleNamespace(interactions=Interactions(), models=Models(), close=lambda: None)
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(sys.modules, _fake_modules(client), clear=False),
        ):
            raw, model = self._strategist(Path(temp))._call_gemini("prompt", [b"image"])

        self.assertEqual(raw, VALID_REPORT)
        self.assertEqual(model, "gemini-3.6-flash")
        self.assertEqual(captured["response_format"]["mime_type"], "application/json")
        self.assertIn("schema", captured["response_format"])

    def test_recovers_with_generate_content_json_mode(self):
        captured = {}

        class Interactions:
            @staticmethod
            def create(**_kwargs):
                raise RuntimeError("schema rejected")

        class Models:
            @staticmethod
            def generate_content(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(text=VALID_REPORT)

        client = SimpleNamespace(interactions=Interactions(), models=Models(), close=lambda: None)
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(sys.modules, _fake_modules(client), clear=False),
        ):
            raw, model = self._strategist(Path(temp))._call_gemini("prompt", [b"image"])

        self.assertEqual(raw, VALID_REPORT)
        self.assertEqual(model, "gemini-3.6-flash")
        self.assertEqual(captured["config"]["response_mime_type"], "application/json")
        self.assertEqual(len(captured["contents"]), 2)


if __name__ == "__main__":
    unittest.main()
