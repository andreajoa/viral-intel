"""Deterministic reverse engineering for public viral posts.

The module separates public observation from inference. It measures whether a third-
party post is a breakout relative to the creator's recent public baseline and converts
observable creative mechanics into an original-adaptation brief. Private Insights are
never invented.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from statistics import median
from typing import Any

from app.models import ContentFormat, Platform, PostMetrics


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != -1), None)


def _as_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (ValueError, OSError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _format_from_public(row: dict[str, Any]) -> ContentFormat:
    product = str(
        _first_present(
            row.get("media_product_type"),
            row.get("productType"),
            row.get("mediaProductType"),
        )
        or ""
    ).upper()
    media_type = str(_first_present(row.get("media_type"), row.get("type")) or "").upper()
    url = str(_first_present(row.get("url"), row.get("post_url")) or "").lower()
    if "REEL" in product or "/reel/" in url:
        return ContentFormat.REEL
    if "SHORT" in product or "/shorts/" in url:
        return ContentFormat.SHORT
    if "CAROUSEL" in product or media_type in {"SIDECAR", "CAROUSEL_ALBUM", "CAROUSEL"}:
        return ContentFormat.CAROUSEL
    if media_type in {"VIDEO", "GRAPHVIDEO"} or row.get("videoUrl"):
        return ContentFormat.VIDEO
    if media_type in {"IMAGE", "PHOTO", "GRAPHIMAGE"} or row.get("displayUrl"):
        return ContentFormat.IMAGE
    return ContentFormat.UNKNOWN


def public_history_to_posts(
    rows: Iterable[dict[str, Any]],
    *,
    platform: Platform,
    followers: int | None,
) -> list[PostMetrics]:
    """Normalize public creator-history rows into evidence-safe PostMetrics."""

    posts: list[PostMetrics] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = {
            "platform": platform,
            "format": _format_from_public(row),
            "post_id": str(
                _first_present(row.get("post_id"), row.get("id"), row.get("shortCode")) or ""
            )
            or None,
            "post_url": _first_present(row.get("post_url"), row.get("url"), row.get("inputUrl")),
            "title": _first_present(row.get("caption"), row.get("title")),
            "published_at": _as_datetime(
                _first_present(
                    row.get("published_at"),
                    row.get("timestamp"),
                    row.get("takenAt"),
                    row.get("createdAt"),
                )
            ),
            "followers": followers,
            "views": _first_present(
                row.get("views"),
                row.get("videoPlayCount"),
                row.get("videoViewCount"),
                row.get("playCount"),
                row.get("viewCount"),
                row.get("viewsCount"),
            ),
            "likes": _first_present(row.get("likes"), row.get("likesCount"), row.get("likeCount")),
            "comments": _first_present(
                row.get("comments"), row.get("commentsCount"), row.get("commentCount")
            ),
            "shares": _first_present(
                row.get("shares"),
                row.get("sharesCount"),
                row.get("shareCount"),
                row.get("reshareCount"),
            ),
            "reposts": _first_present(
                row.get("reposts"), row.get("repostsCount"), row.get("repostCount")
            ),
            "duration_seconds": _first_present(row.get("duration_seconds"), row.get("videoDuration")),
            "source": "public",
            "source_notes": [
                "Histórico público do criador; métricas privadas e evolução histórica do número de seguidores não estão disponíveis."
            ],
        }
        try:
            posts.append(PostMetrics.model_validate(candidate))
        except Exception:
            continue
    return posts


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _public_engagement(post: PostMetrics) -> float | None:
    if not post.views:
        return None
    total = sum(
        float(value)
        for value in (post.likes, post.comments, post.shares, post.reposts)
        if value is not None
    )
    return total / float(post.views) * 100


def _label_breakout(ratio: float | None, percentile: float | None) -> str:
    if ratio is None:
        return "INCONCLUSIVO"
    if ratio >= 5 or (percentile is not None and percentile >= 97 and ratio >= 2.5):
        return "BREAKOUT_FORTE"
    if ratio >= 2.5 or (percentile is not None and percentile >= 90 and ratio >= 1.75):
        return "BREAKOUT"
    if ratio >= 1.5:
        return "ACIMA_DO_PADRÃO"
    if ratio >= 0.67:
        return "DENTRO_DO_PADRÃO"
    return "ABAIXO_DO_PADRÃO"


def build_public_creator_baseline(
    target: PostMetrics,
    history: list[PostMetrics],
) -> dict[str, Any]:
    """Measure breakout against the same creator using only public metrics."""

    candidates = [
        post
        for post in history
        if post.platform == target.platform
        and (not target.post_id or post.post_id != target.post_id)
        and (not target.post_url or post.post_url != target.post_url)
    ]
    same_format = [post for post in candidates if post.format == target.format]
    comparable = same_format if len(same_format) >= 5 else candidates
    metric = "views" if target.views is not None else "likes" if target.likes is not None else "comments"
    target_value = getattr(target, metric, None)
    values = [
        float(value)
        for post in comparable
        if (value := getattr(post, metric, None)) is not None
    ]
    result: dict[str, Any] = {
        "available": bool(target_value is not None and values),
        "source": "public_creator_history",
        "sample_size": len(values),
        "same_format_sample_size": len(
            [post for post in same_format if getattr(post, metric, None) is not None]
        ),
        "metric": metric,
        "target_value": target_value,
        "median_value": None,
        "breakout_multiple": None,
        "percentile": None,
        "status": "INCONCLUSIVO",
        "confidence": 0,
        "views_per_follower": _ratio(target.views, target.followers),
        "public_engagement_rate_pct": _public_engagement(target),
        "limitations": [
            "Este baseline usa apenas números públicos observáveis do criador.",
            "Não inclui salvamentos, alcance, retenção, não seguidores, seguidores ganhos nem pesos privados de ranking.",
        ],
    }
    if target_value is None or not values:
        result["limitations"].append(
            "Não havia amostra pública suficiente para provar o breakout relativo ao próprio criador."
        )
        return result

    med = float(median(values))
    ratio = _ratio(float(target_value), med)
    percentile = round(sum(value <= float(target_value) for value in values) / len(values) * 100, 1)
    confidence = min(95, 35 + min(len(values), 30) * 2)
    if len(same_format) >= 5:
        confidence = min(98, confidence + 8)
    if target.views is not None and target.followers:
        confidence = min(98, confidence + 5)

    engagement_values = [
        value for post in comparable if (value := _public_engagement(post)) is not None
    ]
    median_engagement = float(median(engagement_values)) if engagement_values else None
    engagement_lift = None
    if result["public_engagement_rate_pct"] is not None and median_engagement:
        engagement_lift = _ratio(result["public_engagement_rate_pct"], median_engagement)

    result.update(
        {
            "available": True,
            "median_value": round(med, 4),
            "breakout_multiple": round(ratio, 3) if ratio is not None else None,
            "percentile": percentile,
            "status": _label_breakout(ratio, percentile),
            "confidence": confidence,
            "median_public_engagement_rate_pct": round(median_engagement, 3)
            if median_engagement is not None
            else None,
            "engagement_lift_multiple": round(engagement_lift, 3)
            if engagement_lift is not None
            else None,
        }
    )
    return result


def build_viral_dna(
    *,
    metrics: PostMetrics,
    technical: dict[str, Any],
    creator_baseline: dict[str, Any],
    comments: dict[str, Any],
) -> dict[str, Any]:
    """Build an evidence-first explanation of observable viral mechanics."""

    mechanics: list[dict[str, Any]] = []
    hook = str(technical.get("creative_primary_hook") or "").strip()
    hook_mechanisms = list(technical.get("creative_hook_mechanisms") or [])
    if hook or hook_mechanisms:
        mechanics.append(
            {
                "mechanism": "Gancho",
                "observed": hook or "; ".join(str(item) for item in hook_mechanisms),
                "why_it_can_help": (
                    "Reduz a chance de abandono inicial ao criar uma razão observável para continuar assistindo."
                ),
                "causality": "hipótese plausível, não prova causal",
            }
        )

    progression = list(technical.get("creative_sequence_or_progression") or [])
    if progression:
        mechanics.append(
            {
                "mechanism": "Progressão",
                "observed": progression,
                "why_it_can_help": "Mantém mudança de estado, informação ou imagem ao longo da peça.",
                "causality": "mecanismo criativo observável",
            }
        )

    emotional = list(technical.get("creative_emotional_triggers") or [])
    if emotional:
        mechanics.append(
            {
                "mechanism": "Gatilhos emocionais",
                "observed": emotional,
                "why_it_can_help": "Pode aumentar identificação, memória e vontade de comentar/compartilhar.",
                "causality": "hipótese baseada na peça",
            }
        )

    style = list(technical.get("creative_style_signals") or [])
    if style:
        mechanics.append(
            {
                "mechanism": "Formato e estilo",
                "observed": style,
                "why_it_can_help": "Descreve escolhas de apresentação que podem ser testadas em novas versões.",
                "causality": "observação",
            }
        )

    cta = str(technical.get("creative_cta_observed") or "").strip()
    if cta:
        mechanics.append(
            {
                "mechanism": "CTA",
                "observed": cta,
                "why_it_can_help": "Explicita ou sugere a próxima ação do público.",
                "causality": "observação",
            }
        )

    comment_signals: list[str] = []
    if comments.get("available"):
        mention_rate = comments.get("mention_rate_pct")
        question_rate = comments.get("question_rate_pct")
        if isinstance(mention_rate, (int, float)):
            comment_signals.append(f"{mention_rate:.1f}% da amostra contém marcações")
        if isinstance(question_rate, (int, float)):
            comment_signals.append(f"{question_rate:.1f}% da amostra contém perguntas")
        for item in (comments.get("intent_distribution") or [])[:3]:
            label = item.get("intent")
            share = item.get("share_of_sample_pct")
            if label and isinstance(share, (int, float)):
                comment_signals.append(f"{share:.1f}%: {label}")
    if comment_signals:
        mechanics.append(
            {
                "mechanism": "Reação social observada nos comentários",
                "observed": comment_signals,
                "why_it_can_help": (
                    "Marcações, identificação e perguntas são sinais públicos de que a peça provoca conversa ou transmissão social."
                ),
                "causality": "amostra de comentários, não representa todos os espectadores",
            }
        )

    proof: list[str] = []
    if creator_baseline.get("available"):
        multiple = creator_baseline.get("breakout_multiple")
        percentile = creator_baseline.get("percentile")
        metric = creator_baseline.get("metric")
        if isinstance(multiple, (int, float)):
            proof.append(f"{metric}: {multiple:.2f}× a mediana recente do próprio criador")
        if isinstance(percentile, (int, float)):
            proof.append(f"percentil público aproximado: {percentile:.1f}")
    if metrics.views is not None and metrics.followers:
        proof.append(f"views/seguidores atuais: {metrics.views / metrics.followers:.2f}×")
    if metrics.likes is not None and metrics.views:
        proof.append(f"likes/views públicos: {metrics.likes / metrics.views * 100:.2f}%")
    if metrics.comments is not None and metrics.views:
        proof.append(f"comentários/views públicos: {metrics.comments / metrics.views * 100:.3f}%")

    confidence_inputs = [
        bool(creator_baseline.get("available")),
        bool(technical.get("creative_content_summary")),
        bool(progression),
        bool(comments.get("available")),
        metrics.views is not None,
    ]
    return {
        "status": creator_baseline.get("status") or "INCONCLUSIVO",
        "confidence": min(95, 25 + sum(confidence_inputs) * 14),
        "public_proof": proof,
        "mechanics": mechanics,
        "what_is_known": (
            "O sistema mede o breakout com números públicos e descreve mecanismos visuais, textuais, temporais e sociais observáveis."
        ),
        "what_is_not_known": (
            "Não é possível provar o peso causal de cada mecanismo nem acessar retenção, saves, alcance ou distribuição privada de terceiros."
        ),
    }


def build_replication_blueprint(
    *,
    strategy: Any,
    technical: dict[str, Any],
    creator_baseline: dict[str, Any],
    niche: str,
) -> dict[str, Any]:
    """Turn the diagnosis into an original-adaptation brief for another AI."""

    plan = strategy.next_content
    preserve = list(dict.fromkeys(str(item) for item in plan.preserve if str(item).strip()))
    if not preserve:
        preserve = [str(item) for item in technical.get("creative_hook_mechanisms") or []][:5]
    avoid_copying = [
        "Não copiar frases completas, legenda, identidade visual, personagens ou cenas exclusivas do original.",
        "Não afirmar garantia de viralização; reproduzir apenas mecanismos testáveis.",
        "Adaptar exemplos, linguagem e prova para o seu próprio público e contexto.",
    ]
    target_context = niche.strip() or "meu nicho e meu público"
    evidence_summary = "; ".join(creator_baseline.get("limitations") or [])
    preserve_lines = "\n- ".join(preserve or ["estrutura do gancho e progressão observadas"])
    hook_lines = "\n- ".join(plan.hook_options)
    structure_lines = "\n".join(
        f"{index}. {item}" for index, item in enumerate(plan.structure, 1)
    )
    change_lines = "\n- ".join(plan.change or ["tema, exemplos, texto e elementos visuais"])
    originality_lines = "\n- ".join(avoid_copying)
    limitation = evidence_summary or (
        "A análise usa sinais públicos e observáveis; métricas privadas do criador não estão disponíveis."
    )

    prompt = f"""Você é um estrategista de conteúdo. Crie uma peça ORIGINAL para {target_context} usando apenas a arquitetura de atenção e engajamento abaixo como referência.

OBJETIVO
{plan.objective}

FORMATO
{plan.format}

MECÂNICAS A PRESERVAR
- {preserve_lines}

GANCHOS PARA ADAPTAR
- {hook_lines}

ESTRUTURA RECOMENDADA
{structure_lines}

DIREÇÃO DA LEGENDA
{plan.caption_direction}

CTA
{plan.cta}

ALTERAR EM RELAÇÃO AO ORIGINAL
- {change_lines}

REGRAS DE ORIGINALIDADE
- {originality_lines}

LIMITE DOS DADOS
{limitation}

ENTREGUE
1. conceito da nova peça;
2. roteiro completo;
3. texto na tela por cena;
4. indicação de cortes/ritmo;
5. legenda;
6. CTA;
7. três variações de gancho;
8. o que foi preservado como mecanismo e o que foi alterado para manter originalidade.
"""
    return {
        "objective": plan.objective,
        "format": plan.format,
        "preserve": preserve,
        "change": list(plan.change),
        "hook_options": list(plan.hook_options),
        "structure": list(plan.structure),
        "caption_direction": plan.caption_direction,
        "cta": plan.cta,
        "originality_rules": avoid_copying,
        "ai_prompt": prompt.strip(),
    }
