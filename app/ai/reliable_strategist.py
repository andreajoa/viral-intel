"""Resilient production strategist for current Gemini APIs."""

from __future__ import annotations

from typing import Any

from app.ai.prompt_expert import SYSTEM_PROMPT
from app.ai.schema import StrategicReport
from app.ai.strategist import AIStrategist, _extract_json, _gemini_json_schema


def _models(primary: str) -> list[str]:
    ordered = [
        primary,
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]
    return list(dict.fromkeys(model for model in ordered if model))


def _report_text(response: Any) -> str:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, StrategicReport):
        return parsed.model_dump_json()
    if isinstance(parsed, dict):
        return StrategicReport.model_validate(parsed).model_dump_json()
    text = getattr(response, "text", "") or getattr(response, "output_text", "") or ""
    report = StrategicReport.model_validate(_extract_json(text))
    return report.model_dump_json()


class ReliableAIStrategist(AIStrategist):
    """Use typed Gemini output first, then progressively safer recovery routes."""

    def _call_gemini(self, prompt: str, images: list[bytes]) -> tuple[str, str]:
        from google import genai
        from google.genai import types

        primary_model = self.model_override or self.settings.gemini_model
        request_text = SYSTEM_PROMPT + "\n\n" + prompt
        contents: list[Any] = [request_text]
        contents.extend(types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images)
        failures: list[str] = []
        client = genai.Client(api_key=self.settings.google_api_key)

        try:
            for model in _models(primary_model):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=StrategicReport,
                            max_output_tokens=min(self.settings.max_ai_output_tokens, 32000),
                        ),
                    )
                    return _report_text(response), model
                except Exception as exc:
                    failures.append(f"typed/{model}={type(exc).__name__}: {str(exc)[:180]}")

                try:
                    interaction = client.interactions.create(
                        model=model,
                        input=request_text,
                        response_format={
                            "type": "text",
                            "mime_type": "application/json",
                            "schema": _gemini_json_schema(),
                        },
                    )
                    return _report_text(interaction), model
                except Exception as exc:
                    failures.append(f"interactions/{model}={type(exc).__name__}: {str(exc)[:180]}")

                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            max_output_tokens=min(self.settings.max_ai_output_tokens, 32000),
                        ),
                    )
                    return _report_text(response), model
                except Exception as exc:
                    failures.append(f"json/{model}={type(exc).__name__}: {str(exc)[:180]}")

            detail = "; ".join(failures)
            if self.settings.google_api_key:
                detail = detail.replace(self.settings.google_api_key, "[CHAVE_OCULTA]")
            raise RuntimeError(detail)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
