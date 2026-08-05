"""Multimodal extraction of owner-provided Insights and comment screenshots.

This module reads only values and text visibly present in screenshots. It does not
scrape Instagram, infer hidden metrics, or identify people who liked, saved, or
shared a publication.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.ai.strategist import _extract_json
from app.config import Settings

InsightMetricName = Literal[
    "followers",
    "views",
    "reach",
    "impressions",
    "likes",
    "comments",
    "shares",
    "saves",
    "reposts",
    "follows",
    "profile_visits",
    "profile_activity",
    "total_interactions",
    "accounts_engaged",
    "followers_reach",
    "non_followers_reach",
    "home_impressions",
    "explore_impressions",
    "profile_impressions",
    "hashtag_impressions",
    "average_watch_time_seconds",
    "completion_rate",
    "retention_3s_rate",
    "average_view_percentage",
    "non_follower_reach_rate",
    "engaged_non_follower_rate",
    "impressions_ctr",
    "replays",
    "skip_rate",
    "unknown",
]

_PERCENT_METRICS = {
    "completion_rate",
    "retention_3s_rate",
    "average_view_percentage",
    "non_follower_reach_rate",
    "engaged_non_follower_rate",
    "impressions_ctr",
    "skip_rate",
}
_ZERO_RE = re.compile(r"(?<!\d)0(?:[.,]0+)?\s*%?(?!\d)")


@dataclass(slots=True)
class ScreenshotAsset:
    data: bytes
    mime_type: str = "image/jpeg"
    name: str = "screenshot"


class ExtractedInsightMetric(BaseModel):
    metric: InsightMetricName
    value: float | int | None = Field(default=None, ge=0)
    displayed_text: str = ""
    visual_evidence: str = ""
    confidence: int = Field(default=0, ge=0, le=100)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> int:
        return _confidence(value)


class InsightScreenshotObservation(BaseModel):
    observed: bool = False
    metrics: list[ExtractedInsightMetric] = Field(default_factory=list, max_length=40)
    visible_period: str = ""
    visible_post_identifier: str = ""
    source_screenshots: int = 0
    limitations: list[str] = Field(default_factory=list, max_length=12)

    def metrics_for_merge(self, minimum_confidence: int = 80) -> dict[str, float | int]:
        values: dict[str, float | int] = {}
        for item in self.metrics:
            if item.metric == "unknown" or item.value is None or item.confidence < minimum_confidence:
                continue
            if item.value == 0:
                evidence = f"{item.displayed_text} {item.visual_evidence}".lower()
                if not _ZERO_RE.search(evidence):
                    continue
            value: float | int = item.value
            if item.metric not in _PERCENT_METRICS and item.metric != "average_watch_time_seconds":
                value = int(round(float(value)))
            values.setdefault(item.metric, value)
        return values


class ExtractedComment(BaseModel):
    author: str = ""
    text: str
    likes: int | None = Field(default=None, ge=0)
    timestamp: str = ""
    visual_evidence: str = ""
    confidence: int = Field(default=0, ge=0, le=100)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> int:
        return _confidence(value)


class CommentScreenshotObservation(BaseModel):
    observed: bool = False
    comments: list[ExtractedComment] = Field(default_factory=list, max_length=300)
    source_screenshots: int = 0
    limitations: list[str] = Field(default_factory=list, max_length=12)

    def comments_for_merge(self, minimum_confidence: int = 75) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in self.comments:
            author = item.author.strip()
            text = item.text.strip()
            if not text or item.confidence < minimum_confidence:
                continue
            key = (author.lower(), text.lower())
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "author": author or None,
                    "text": text,
                    "likes": item.likes,
                    "timestamp": item.timestamp or None,
                    "source": "comment_screenshot",
                }
            )
        return rows


def _confidence(value: Any) -> int:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if 0 < number <= 1:
        number *= 100
    return max(0, min(100, round(number)))


INSIGHTS_PROMPT = """Você extrai dados de capturas do Instagram Insights fornecidas pelo proprietário da conta.

Leia apenas números, percentuais, períodos e rótulos realmente visíveis. Não complete campos ausentes,
não transforme ausência em zero e não confunda métricas diferentes.

Regras:
- Preserve o texto exibido em displayed_text e converta abreviações: 33,8 mil=33800, 5.4K=5400.
- Percentuais permanecem na escala humana: 64% vira 64, não 0.64.
- Tempo médio assistido deve ser informado em segundos quando a unidade estiver visível.
- Diferencie alcance, visualizações, impressões, contas alcançadas e contas engajadas.
- Diferencie compartilhamentos/envios de reposts.
- Diferencie seguidores alcançados de não seguidores alcançados.
- Um zero só pode ser extraído quando o dígito 0 e o rótulo correspondente estiverem visíveis.
- Se a captura for de outra tela ou o rótulo estiver cortado, use metric=unknown ou omita.
- Não invente identidade de quem curtiu, salvou ou compartilhou.
- Confiança deve ser 0 a 100.

Retorne somente JSON válido:
{
  "observed": true,
  "metrics": [
    {
      "metric": "followers|views|reach|impressions|likes|comments|shares|saves|reposts|follows|profile_visits|profile_activity|total_interactions|accounts_engaged|followers_reach|non_followers_reach|home_impressions|explore_impressions|profile_impressions|hashtag_impressions|average_watch_time_seconds|completion_rate|retention_3s_rate|average_view_percentage|non_follower_reach_rate|engaged_non_follower_rate|impressions_ctr|replays|skip_rate|unknown",
      "value": null,
      "displayed_text": "",
      "visual_evidence": "",
      "confidence": 0
    }
  ],
  "visible_period": "",
  "visible_post_identifier": "",
  "source_screenshots": 0,
  "limitations": []
}
"""

COMMENTS_PROMPT = """Você extrai comentários visíveis de capturas fornecidas pela pessoa usuária.

Transcreva somente comentários realmente legíveis. Preserve username, texto, curtidas visíveis e data/hora
quando aparecerem. Não adivinhe texto cortado, não infira características pessoais e não inclua elementos
da interface que não sejam comentários.

Regras:
- Um comentário por item.
- Se o username estiver oculto ou ilegível, deixe author vazio.
- Se a contagem de curtidas não estiver visível, use null, nunca zero.
- Remova duplicatas que aparecem em capturas sobrepostas.
- Confiança deve ser 0 a 100.

Retorne somente JSON válido:
{
  "observed": true,
  "comments": [
    {
      "author": "",
      "text": "",
      "likes": null,
      "timestamp": "",
      "visual_evidence": "",
      "confidence": 0
    }
  ],
  "source_screenshots": 0,
  "limitations": []
}
"""


def _observe(
    *,
    settings: Settings,
    assets: list[ScreenshotAsset],
    prompt: str,
    schema: type[BaseModel],
) -> tuple[BaseModel | None, list[str], str]:
    if not assets:
        return None, [], ""
    if not settings.google_api_key:
        return None, ["Capturas fornecidas, mas a Gemini não está configurada para lê-las."], ""

    from google import genai
    from google.genai import types

    models = [settings.gemini_model]
    if settings.gemini_model != "gemini-3.5-flash":
        models.append("gemini-3.5-flash")

    request_text = prompt + "\n\nQuantidade de capturas: " + str(len(assets))
    client = genai.Client(api_key=settings.google_api_key)
    errors: list[str] = []
    try:
        for model in models:
            try:
                parts = [types.Part.from_text(text=request_text)]
                parts.extend(
                    types.Part.from_bytes(data=asset.data, mime_type=asset.mime_type or "image/jpeg")
                    for asset in assets[:20]
                )
                response = client.models.generate_content(model=model, contents=parts)
                payload = _extract_json(response.text or "")
                payload["source_screenshots"] = len(assets)
                return schema.model_validate(payload), errors, model
            except Exception as exc:
                detail = str(exc).replace(settings.google_api_key, "[CHAVE_OCULTA]")
                errors.append(f"leitura de evidências {model}: {type(exc).__name__}: {detail[:300]}")
        return None, errors, ""
    finally:
        client.close()


def observe_insight_screenshots(
    settings: Settings,
    assets: list[ScreenshotAsset],
) -> tuple[InsightScreenshotObservation | None, list[str], str]:
    observation, errors, model = _observe(
        settings=settings,
        assets=assets,
        prompt=INSIGHTS_PROMPT,
        schema=InsightScreenshotObservation,
    )
    return (
        observation if isinstance(observation, InsightScreenshotObservation) else None,
        errors,
        model,
    )


def observe_comment_screenshots(
    settings: Settings,
    assets: list[ScreenshotAsset],
) -> tuple[CommentScreenshotObservation | None, list[str], str]:
    observation, errors, model = _observe(
        settings=settings,
        assets=assets,
        prompt=COMMENTS_PROMPT,
        schema=CommentScreenshotObservation,
    )
    return (
        observation if isinstance(observation, CommentScreenshotObservation) else None,
        errors,
        model,
    )


def observation_json(value: BaseModel | None) -> dict[str, Any]:
    return value.model_dump(mode="json") if value is not None else {}


def compact_observation(value: BaseModel | None) -> str:
    return json.dumps(observation_json(value), ensure_ascii=False, separators=(",", ":"))
