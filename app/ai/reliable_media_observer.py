"""Production-grade Gemini media observation with structured-output recovery."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.media_observer import OBSERVATION_PROMPT, MediaObservation
from app.ai.strategist import _extract_json
from app.config import Settings

logger = logging.getLogger(__name__)

METRIC_FOCUS = """

SEGUNDA VERIFICAÇÃO OBRIGATÓRIA DE MÉTRICAS VISÍVEIS:
Examine novamente cada imagem, principalmente a faixa imediatamente abaixo do post.
Procure coração com número, balão com número, setas circulares com número e contagem de
visualizações. Converta K/mil/M para inteiro. Não confunda setas circulares com avião de
papel. Se houver contagens legíveis, visible_metrics não pode ficar vazio.
"""


def _models(settings: Settings) -> list[str]:
    ordered = [
        settings.gemini_model,
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]
    return list(dict.fromkeys(model for model in ordered if model))


def _sanitize_error(exc: Exception, secret: str) -> str:
    detail = str(exc)
    if secret:
        detail = detail.replace(secret, "[CHAVE_OCULTA]")
    return f"{type(exc).__name__}: {detail[:260]}"


def _parse_response(response: Any) -> MediaObservation:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, MediaObservation):
        return parsed
    if isinstance(parsed, dict):
        return MediaObservation.model_validate(parsed)
    text = getattr(response, "text", "") or ""
    try:
        return MediaObservation.model_validate_json(text)
    except Exception:
        return MediaObservation.model_validate(_extract_json(text))


def _merge_focused_metrics(
    original: MediaObservation,
    focused: MediaObservation,
) -> MediaObservation:
    if not focused.visible_metrics:
        return original
    updates: dict[str, Any] = {"visible_metrics": focused.visible_metrics}
    if original.asset_type in {"unknown", "image"} and focused.asset_type == "social_screenshot":
        updates["asset_type"] = "social_screenshot"
    combined_limitations = list(dict.fromkeys([*original.limitations, *focused.limitations]))
    if combined_limitations:
        updates["limitations"] = combined_limitations[:10]
    return original.model_copy(update=updates)


def observe_media(
    *,
    settings: Settings,
    images: list[bytes],
    technical: dict[str, Any],
    transcription: str,
) -> tuple[MediaObservation | None, list[str], str]:
    """Observe uploaded media without turning visual guesses into performance facts."""

    if not images or not settings.google_api_key:
        return None, [], ""

    from google import genai
    from google.genai import types

    context = {
        "technical_context": technical,
        "transcription": transcription or "INDISPONÍVEL",
        "images_sent": len(images),
    }
    request_text = (
        OBSERVATION_PROMPT + "\n\nCONTEXTO TÉCNICO:\n" + json.dumps(context, ensure_ascii=False, default=str)
    )

    def contents_for(text: str) -> list[Any]:
        contents: list[Any] = [text]
        contents.extend(types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images)
        return contents

    def focused_retry(client: Any, model: str, original: MediaObservation) -> MediaObservation:
        if original.visible_metrics:
            return original
        response = client.models.generate_content(
            model=model,
            contents=contents_for(request_text + METRIC_FOCUS),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MediaObservation,
                max_output_tokens=min(settings.max_ai_output_tokens, 12000),
            ),
        )
        return _merge_focused_metrics(original, _parse_response(response))

    errors: list[str] = []
    client = genai.Client(api_key=settings.google_api_key)
    try:
        for model in _models(settings):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents_for(request_text),
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=MediaObservation,
                        max_output_tokens=min(settings.max_ai_output_tokens, 12000),
                    ),
                )
                observation = _parse_response(response)
                try:
                    observation = focused_retry(client, model, observation)
                except Exception as metric_exc:
                    errors.append(
                        f"segunda leitura de métricas {model}: "
                        + _sanitize_error(metric_exc, settings.google_api_key)
                    )
                return observation, errors, model
            except Exception as structured_exc:
                errors.append(
                    f"observação estruturada {model}: "
                    + _sanitize_error(structured_exc, settings.google_api_key)
                )

            try:
                response = client.models.generate_content(
                    model=model,
                    contents=contents_for(request_text),
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        max_output_tokens=min(settings.max_ai_output_tokens, 12000),
                    ),
                )
                observation = _parse_response(response)
                try:
                    observation = focused_retry(client, model, observation)
                except Exception as metric_exc:
                    errors.append(
                        f"segunda leitura de métricas {model}: "
                        + _sanitize_error(metric_exc, settings.google_api_key)
                    )
                return observation, errors, model
            except Exception as json_exc:
                errors.append(
                    f"observação JSON {model}: " + _sanitize_error(json_exc, settings.google_api_key)
                )

        logger.warning("Gemini media observation failed after all recovery routes")
        return None, errors, ""
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
