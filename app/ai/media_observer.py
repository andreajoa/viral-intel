"""Multimodal observation before performance interpretation.

This stage converts visible/audible creative features into auditable evidence. It
never decides whether content viralized and never treats OCR as private Insights.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.ai.strategist import _extract_json
from app.config import Settings

logger = logging.getLogger(__name__)
_ZERO_RE = re.compile(r"(?<!\d)0(?:[.,]0+)?(?!\d)")


class VisibleMetric(BaseModel):
    metric: Literal[
        "likes",
        "comments",
        "shares",
        "saves",
        "reposts",
        "views",
        "followers",
        "unknown",
    ]
    value: int | None = Field(default=None, ge=0)
    displayed_text: str = ""
    visual_evidence: str = ""
    confidence: int = Field(default=0, ge=0, le=100)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> int:
        return _confidence_percent(value)


class MediaObservation(BaseModel):
    observed: bool = False
    asset_type: Literal["video", "carousel", "image", "social_screenshot", "unknown"] = "unknown"
    format_hint: Literal["reel", "short", "video", "carousel", "image", "text", "unknown"] = "unknown"
    format_confidence: int = Field(default=0, ge=0, le=100)
    content_summary: str = ""
    visible_text: list[str] = Field(default_factory=list, max_length=30)
    primary_hook: str = ""
    hook_mechanisms: list[str] = Field(default_factory=list, max_length=8)
    visual_subject: str = ""
    visual_structure: list[str] = Field(default_factory=list, max_length=10)
    sequence_or_progression: list[str] = Field(default_factory=list, max_length=12)
    emotional_triggers: list[str] = Field(default_factory=list, max_length=8)
    audience_promise: str = ""
    curiosity_or_tension: str = ""
    cta_observed: str = ""
    style_signals: list[str] = Field(default_factory=list, max_length=10)
    visible_metrics: list[VisibleMetric] = Field(default_factory=list, max_length=12)
    risks_or_ambiguities: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("format_confidence", mode="before")
    @classmethod
    def normalize_format_confidence(cls, value: Any) -> int:
        return _confidence_percent(value)

    def metrics_for_prefill(self, minimum_confidence: int = 75) -> dict[str, int]:
        """Return only visually supported counts.

        A zero is especially risky because vision models sometimes use 0 as a missing
        value. Viral Intel 5 accepts zero only when the digit is explicitly visible in
        the metric's evidence next to a compatible icon/label.
        """

        values: dict[str, int] = {}
        for item in self.visible_metrics:
            if item.metric == "unknown" or item.value is None or item.confidence < minimum_confidence:
                continue
            if item.value == 0 and not _explicit_zero(item):
                continue
            values.setdefault(item.metric, item.value)
        return values

    def evidence_context(self) -> dict[str, Any]:
        fields = {
            "creative_asset_type": self.asset_type,
            "creative_format_hint": {
                "format": self.format_hint,
                "confidence": self.format_confidence,
            },
            "creative_content_summary": self.content_summary,
            "creative_visible_text": self.visible_text,
            "creative_primary_hook": self.primary_hook,
            "creative_hook_mechanisms": self.hook_mechanisms,
            "creative_visual_subject": self.visual_subject,
            "creative_visual_structure": self.visual_structure,
            "creative_sequence_or_progression": self.sequence_or_progression,
            "creative_emotional_triggers": self.emotional_triggers,
            "creative_audience_promise": self.audience_promise,
            "creative_curiosity_or_tension": self.curiosity_or_tension,
            "creative_cta_observed": self.cta_observed,
            "creative_style_signals": self.style_signals,
            "creative_visible_metric_observations": [
                item.model_dump(mode="json") for item in self.visible_metrics
            ],
            "creative_risks_or_ambiguities": self.risks_or_ambiguities,
            "creative_observation_limitations": self.limitations,
        }
        return {key: value for key, value in fields.items() if value not in (None, "", [], {})}


def _confidence_percent(value: Any) -> int:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if 0 < number <= 1:
        number *= 100
    return round(number)


def _explicit_zero(metric: VisibleMetric) -> bool:
    if metric.value != 0:
        return True
    evidence = f"{metric.displayed_text} {metric.visual_evidence}".lower()
    if not _ZERO_RE.search(evidence):
        return False
    context_markers = {
        "likes": ("coração", "curtida", "like"),
        "comments": ("balão", "comentário", "comment"),
        "reposts": ("setas", "repost"),
        "shares": ("avião", "compartilh", "envio"),
        "views": ("visualiza", "view", "play"),
        "saves": ("salv", "favorito", "bookmark"),
        "followers": ("seguidor", "follower"),
    }
    markers = context_markers.get(metric.metric, ())
    return not markers or any(marker in evidence for marker in markers)


OBSERVATION_PROMPT = """Você é a etapa de observação multimodal do Viral Intel 5.

Descreva somente o que está realmente visível/audível nos arquivos enviados ou presente
na transcrição/contexto técnico. Não avalie se viralizou e não invente alcance, retenção,
salvamentos, intenção do autor ou reação do público.

Regras importantes:
- Em vídeo nativo, examine a progressão temporal, especialmente 0–1s, 1–3s, corpo e fechamento.
- Em frames, examine a imagem inteira, inclusive cabeçalho, rodapé e faixa de ícones.
- Diferencie arte isolada de captura de rede social. Se houver interface, username,
  ícones ou contagens, use asset_type="social_screenshot".
- Transcreva somente textos realmente legíveis.
- Identifique mecanismos observáveis do gancho: curiosidade, tensão, identidade, ameaça,
  promessa, contraste, especificidade, controvérsia etc. Isso é descrição, não causalidade.
- Se houver paginação ou indicação de deslizar, reconheça carrossel mesmo com uma captura.
- Métricas só podem ser extraídas quando número e ícone/rótulo estiverem legíveis.
- No Instagram, coração=likes, balão=comments, setas circulares=reposts. Avião de papel
  sem número não autoriza inferir shares.
- Converta abreviações: 33.8K/33,8 mil=33800; 1.2M=1200000. Preserve displayed_text.
- Nunca use zero como substituto de métrica ausente. Zero só é válido se estiver
  explicitamente visível junto ao ícone/rótulo correto.
- Para cada métrica visível, informe evidência visual e confiança de 0 a 100.
- Escreva campos textuais e listas em português natural.
- Se apenas a capa de carrossel estiver disponível, declare que os demais slides não foram inspecionados.

Retorne somente JSON válido no schema fornecido.
"""


def observe_media(
    *,
    settings: Settings,
    images: list[bytes],
    technical: dict[str, Any],
    transcription: str,
) -> tuple[MediaObservation | None, list[str], str]:
    """Legacy frame-based observer retained as a deterministic-compatible fallback."""

    if not images or not settings.google_api_key:
        return None, [], ""

    from google import genai
    from google.genai import types

    models = [settings.gemini_model, *settings.gemini_fallback_models]
    models = list(dict.fromkeys(model for model in models if model))
    context = {
        "technical_context": technical,
        "transcription": transcription or "INDISPONÍVEL",
        "images_sent": len(images),
    }
    request_text = OBSERVATION_PROMPT + "\n\nCONTEXTO:\n" + json.dumps(
        context, ensure_ascii=False, default=str
    )
    errors: list[str] = []
    client = genai.Client(api_key=settings.google_api_key)
    try:
        for model in models:
            try:
                parts = [types.Part.from_text(text=request_text)]
                parts.extend(types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images)
                response = client.models.generate_content(model=model, contents=parts)
                observation = MediaObservation.model_validate(_extract_json(response.text or ""))
                return observation, errors, model
            except Exception as exc:
                detail = str(exc).replace(settings.google_api_key, "[CHAVE_OCULTA]")
                errors.append(f"observação multimodal {model}: {type(exc).__name__}: {detail[:240]}")
        return None, errors, ""
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
