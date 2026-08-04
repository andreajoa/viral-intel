from __future__ import annotations

import json
import sys
import tempfile
import types as python_types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.media_observer import MediaObservation
from app.ai.reliable_media_observer import observe_media
from app.ai.reliable_strategist import ReliableAIStrategist
from app.ai.schema import StrategicReport
from app.config import Settings


class _Part:
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
            "format": "image",
            "objective": "Testar o gancho observado.",
            "hook_options": ["Gancho A", "Gancho B"],
            "structure": ["Abertura", "Desenvolvimento", "CTA"],
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

VALID_OBSERVATION = json.dumps(
    {
        "observed": True,
        "asset_type": "social_screenshot",
        "format_hint": "image",
        "format_confidence": 96,
        "content_summary": "Uma publicação com texto principal legível.",
        "primary_hook": "Uma pergunta direta.",
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


class ReliableGeminiTests(unittest.TestCase):
    def _settings(self, root: Path) -> Settings:
        settings = Settings(
            data_dir=root / "data",
            local_media_dir=root / "media",
            google_api_key="configured-test-key",
            gemini_model="gemini-3.6-flash",
        )
        settings.ensure_dirs()
        return settings

    def test_media_observer_uses_typed_schema(self):
        captured = {}

        class Models:
            @staticmethod
            def generate_content(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(text=VALID_OBSERVATION, parsed=None)

        client = SimpleNamespace(models=Models(), close=lambda: None)
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            sys.modules, _fake_modules(client), clear=False
        ):
            observation, errors, model = observe_media(
                settings=self._settings(Path(temp)),
                images=[b"image"],
                technical={"width": 1080, "height": 1350},
                transcription="",
            )

        self.assertIsInstance(observation, MediaObservation)
        self.assertEqual(model, "gemini-3.6-flash")
        self.assertEqual(errors, [])
        self.assertIs(captured["config"]["response_schema"], MediaObservation)
        self.assertEqual(captured["contents"][1]["type"], "image")

    def test_strategist_uses_typed_schema_and_validates_report(self):
        captured = {}

        class Models:
            @staticmethod
            def generate_content(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(text=VALID_REPORT, parsed=None)

        client = SimpleNamespace(models=Models(), close=lambda: None)
        with tempfile.TemporaryDirectory() as temp, patch.dict(
            sys.modules, _fake_modules(client), clear=False
        ):
            raw, model = ReliableAIStrategist(
                settings=self._settings(Path(temp))
            )._call_gemini("prompt", [b"image"])

        report = StrategicReport.model_validate_json(raw)
        self.assertEqual(report.repeat_decision, "DADOS_INSUFICIENTES")
        self.assertEqual(model, "gemini-3.6-flash")
        self.assertIs(captured["config"]["response_schema"], StrategicReport)
        self.assertEqual(captured["contents"][1]["type"], "image")


if __name__ == "__main__":
    unittest.main()
