"""Production-grade Gemini media observation with native-video and frame recovery."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
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
papel. Nunca use zero como substituto de dado ausente.
"""

NATIVE_VIDEO_FOCUS = """

O ARQUIVO ORIGINAL DE VÍDEO ESTÁ DISPONÍVEL. Faça leitura temporal nativa: observe o que
acontece no primeiro segundo, de 1 a 3 segundos, a progressão do corpo e o fechamento.
Use sequence_or_progression para registrar essa evolução em ordem. Compare o áudio, o
texto na tela e as mudanças visuais. Não transforme ritmo aparente em retenção medida.
"""


def _models(settings: Settings) -> list[str]:
    ordered = [settings.gemini_model, *settings.gemini_fallback_models]
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
    text = getattr(response, "text", "") or getattr(response, "output_text", "") or ""
    try:
        return MediaObservation.model_validate_json(text)
    except Exception:
        return MediaObservation.model_validate(_extract_json(text))


def _merge_focused_metrics(original: MediaObservation, focused: MediaObservation) -> MediaObservation:
    updates: dict[str, Any] = {}
    if focused.visible_metrics:
        updates["visible_metrics"] = focused.visible_metrics
    if original.asset_type in {"unknown", "image"} and focused.asset_type == "social_screenshot":
        updates["asset_type"] = "social_screenshot"
    combined_limitations = list(dict.fromkeys([*original.limitations, *focused.limitations]))
    if combined_limitations:
        updates["limitations"] = combined_limitations[:10]
    return original.model_copy(update=updates) if updates else original


def _wait_for_file(client: Any, uploaded: Any, settings: Settings) -> Any:
    deadline = time.monotonic() + settings.native_video_timeout_seconds
    current = uploaded
    while True:
        state = getattr(getattr(current, "state", None), "name", "")
        if state == "ACTIVE" or not state:
            return current
        if state in {"FAILED", "ERROR"}:
            raise RuntimeError(f"processamento do vídeo falhou com estado {state}")
        if time.monotonic() >= deadline:
            raise TimeoutError("processamento nativo do vídeo excedeu o limite configurado")
        time.sleep(settings.native_video_poll_seconds)
        current = client.files.get(name=current.name)


def _observe_native_video(
    *,
    client: Any,
    model: str,
    video_path: Path,
    request_text: str,
    settings: Settings,
    types: Any,
) -> MediaObservation:
    uploaded = None
    try:
        uploaded = client.files.upload(file=str(video_path))
        uploaded = _wait_for_file(client, uploaded, settings)
        response = client.models.generate_content(
            model=model,
            contents=[uploaded, request_text + NATIVE_VIDEO_FOCUS],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=MediaObservation,
                max_output_tokens=min(settings.max_ai_output_tokens, 16000),
            ),
        )
        return _parse_response(response)
    finally:
        if uploaded is not None and getattr(uploaded, "name", None):
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                logger.debug("Could not proactively delete Gemini file %s", uploaded.name)


def observe_media(
    *,
    settings: Settings,
    images: list[bytes],
    technical: dict[str, Any],
    transcription: str,
    video_path: str | Path | None = None,
) -> tuple[MediaObservation | None, list[str], str]:
    """Observe uploaded media without turning creative observations into performance facts.

    For eligible videos, Viral Intel 5 first uses the original video as a native multimodal
    input. FFmpeg frames remain a deterministic cross-check and fallback, so temporal
    understanding is added without discarding auditable local measurements.
    """

    path = Path(video_path).expanduser().resolve() if video_path else None
    native_video_ok = bool(
        path
        and path.is_file()
        and settings.enable_native_video_ai
        and path.stat().st_size <= settings.native_video_max_mb * 1024 * 1024
    )
    if not settings.google_api_key or (not images and not native_video_ok):
        return None, [], ""

    from google import genai
    from google.genai import types

    context = {
        "technical_context": technical,
        "transcription": transcription or "INDISPONÍVEL",
        "frames_available": len(images),
        "native_video_available": native_video_ok,
    }
    request_text = OBSERVATION_PROMPT + "\n\nCONTEXTO TÉCNICO:\n" + json.dumps(
        context, ensure_ascii=False, default=str
    )

    def contents_for(text: str) -> list[Any]:
        contents: list[Any] = [text]
        contents.extend(types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images)
        return contents

    def focused_retry(client: Any, model: str, original: MediaObservation) -> MediaObservation:
        if original.visible_metrics or not images:
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
        if native_video_ok and path is not None:
            for model in _models(settings):
                try:
                    observation = _observe_native_video(
                        client=client,
                        model=model,
                        video_path=path,
                        request_text=request_text,
                        settings=settings,
                        types=types,
                    )
                    try:
                        observation = focused_retry(client, model, observation)
                    except Exception as metric_exc:
                        errors.append(
                            f"cross-check visual {model}: "
                            + _sanitize_error(metric_exc, settings.google_api_key)
                        )
                    return observation, errors, model + "+native-video"
                except Exception as exc:
                    errors.append(
                        f"vídeo nativo {model}: " + _sanitize_error(exc, settings.google_api_key)
                    )

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
                return _parse_response(response), errors, model
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
