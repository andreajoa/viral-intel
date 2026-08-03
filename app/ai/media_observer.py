"""Multimodal observation before performance interpretation.

This stage converts visible/audible creative features into auditable evidence. It
never decides whether the content viralized and never treats OCR as private Insights.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.ai.strategist import _extract_json
from app.config import Settings

logger = logging.getLogger(__name__)


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

    def metrics_for_prefill(self, minimum_confidence: int = 90) -> dict[str, int]:
        values: dict[str, int] = {}
        for item in self.visible_metrics:
            if item.metric == "unknown" or item.value is None or item.confidence < minimum_confidence:
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
    """Accept both 0..1 probabilities and explicit 0..100 percentages."""

    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if 0 < number <= 1:
        number *= 100
    return round(number)


OBSERVATION_PROMPT = """Você é a etapa de observação visual do Viral Intel.

Descreva somente o que está realmente visível nos arquivos enviados ou presente na
transcrição/contexto técnico. Não avalie se viralizou e não invente alcance, retenção,
salvamentos, intenção do autor ou reação do público.

Regras importantes:
- Transcreva os textos principais exatamente como aparecem.
- Identifique o mecanismo do gancho: curiosidade, tensão, identidade, ameaça, promessa,
  contraste, especificidade, controvérsia etc. Isso é descrição criativa, não causa provada.
- Se houver bolinhas de paginação, seta lateral ou “passe para o lado”, reconheça o
  conteúdo como carrossel, ainda que só exista uma captura.
- Métricas só podem ser extraídas quando número e ícone/rótulo estiverem legíveis.
- No Instagram, coração=likes, balão=comments, setas circulares=reposts. O avião de papel
  sem número não autoriza inferir shares. Use unknown quando o ícone for ambíguo.
- Para cada métrica visível, informe a evidência visual e a confiança. Nunca converta
  ausência em zero.
- Toda confiança deve ser um número inteiro de 0 a 100; use 100 para certeza visual,
  nunca 1 como abreviação de 100%.
- Escreva os campos textuais e todas as listas em português natural.
- Se apenas a capa do carrossel estiver disponível, declare que os demais slides não
  foram inspecionados.

Retorne somente JSON válido neste contrato:
{
  "observed": true,
  "asset_type": "video|carousel|image|social_screenshot|unknown",
  "format_hint": "reel|short|video|carousel|image|text|unknown",
  "format_confidence": 0,
  "content_summary": "",
  "visible_text": [],
  "primary_hook": "",
  "hook_mechanisms": [],
  "visual_subject": "",
  "visual_structure": [],
  "sequence_or_progression": [],
  "emotional_triggers": [],
  "audience_promise": "",
  "curiosity_or_tension": "",
  "cta_observed": "",
  "style_signals": [],
  "visible_metrics": [
    {"metric":"likes|comments|shares|saves|reposts|views|followers|unknown",
     "value":null,"displayed_text":"","visual_evidence":"","confidence":0}
  ],
  "risks_or_ambiguities": [],
  "limitations": []
}
"""


def observe_media(
    *,
    settings: Settings,
    images: list[bytes],
    technical: dict[str, Any],
    transcription: str,
) -> tuple[MediaObservation | None, list[str], str]:
    if not images:
        return None, [], ""
    if not settings.google_api_key:
        # Ausência de chave é um modo suportado, não uma falha do provedor.
        return None, [], ""

    from google import genai
    from google.genai import types

    models = [settings.gemini_model]
    if settings.gemini_model != "gemini-3.5-flash":
        models.append("gemini-3.5-flash")

    context = {
        "technical_context": technical,
        "transcription": transcription or "INDISPONÍVEL",
        "images_sent": len(images),
    }
    request_text = (
        OBSERVATION_PROMPT + "\n\nCONTEXTO:\n" + json.dumps(context, ensure_ascii=False, default=str)
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
        client.close()
