"""Build an auditable evidence ledger for the language model and the UI."""

from __future__ import annotations

from typing import Any

from app.models import BenchmarkResult, DataQuality, EvidenceItem, PostMetrics

RAW_LABELS = {
    "followers": ("Seguidores no momento da captura", "contagem"),
    "views": ("Visualizações", "contagem"),
    "reach": ("Alcance", "contagem"),
    "impressions": ("Impressões", "contagem"),
    "likes": ("Curtidas", "contagem"),
    "comments": ("Comentários", "contagem"),
    "shares": ("Compartilhamentos", "contagem"),
    "saves": ("Salvamentos/favoritos", "contagem"),
    "reposts": ("Reposts", "contagem"),
    "follows": ("Novos seguidores atribuídos", "contagem"),
    "profile_visits": ("Visitas ao perfil", "contagem"),
    "duration_seconds": ("Duração", "segundos"),
    "average_watch_time_seconds": ("Tempo médio assistido", "segundos"),
    "completion_rate": ("Taxa de conclusão", "%"),
    "retention_3s_rate": ("Retenção em 3 segundos", "%"),
    "average_view_percentage": ("Percentual médio assistido", "%"),
    "non_follower_reach_rate": ("Alcance de não seguidores", "%"),
    "impressions_ctr": ("CTR de impressões", "%"),
}

DERIVED_LABELS = {
    "interactions_known": ("Interações conhecidas", "contagem", "soma apenas das interações fornecidas"),
    "circulation_actions_known": (
        "Ações de circulação conhecidas",
        "contagem",
        "soma apenas de compartilhamentos e reposts fornecidos",
    ),
    "circulation_to_likes_pct": (
        "Ações de circulação por 100 curtidas",
        "%",
        "ações de circulação conhecidas ÷ curtidas × 100",
    ),
    "comments_to_likes_pct": (
        "Comentários por 100 curtidas",
        "%",
        "comentários ÷ curtidas × 100",
    ),
    "circulation_to_comments_ratio": (
        "Circulação em relação aos comentários",
        "× comentários",
        "ações de circulação conhecidas ÷ comentários",
    ),
    "engagement_by_views_pct": (
        "Engajamento por visualizações",
        "%",
        "interações conhecidas ÷ visualizações × 100",
    ),
    "engagement_by_reach_pct": ("Engajamento por alcance", "%", "interações conhecidas ÷ alcance × 100"),
    "views_per_follower_pct": ("Visualizações por seguidores", "%", "visualizações ÷ seguidores × 100"),
    "reach_per_follower_pct": ("Alcance por seguidores", "%", "alcance ÷ seguidores × 100"),
    "like_rate_by_views_pct": ("Taxa de curtidas", "%", "curtidas ÷ visualizações × 100"),
    "comment_rate_by_views_pct": ("Taxa de comentários", "%", "comentários ÷ visualizações × 100"),
    "share_rate_by_views_pct": ("Taxa de compartilhamento", "%", "compartilhamentos ÷ visualizações × 100"),
    "save_rate_by_views_pct": ("Taxa de salvamento", "%", "salvamentos ÷ visualizações × 100"),
    "follow_conversion_by_reach_pct": ("Conversão em seguidores", "%", "novos seguidores ÷ alcance × 100"),
    "profile_visit_conversion_pct": (
        "Conversão de visita em seguidor",
        "%",
        "novos seguidores ÷ visitas ao perfil × 100",
    ),
    "average_views_per_hour_since_publish": (
        "Média de views por hora desde a publicação",
        "views/h",
        "visualizações ÷ idade do post em horas; não mede aceleração",
    ),
    "average_reach_per_hour_since_publish": (
        "Média de alcance por hora desde a publicação",
        "alcance/h",
        "alcance ÷ idade do post em horas; não mede aceleração",
    ),
}


def build_evidence(
    metrics: PostMetrics,
    derived: dict[str, float],
    benchmark: BenchmarkResult,
    quality: DataQuality,
    technical: dict[str, Any] | None = None,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    observed_index = calculated_index = benchmark_index = technical_index = missing_index = 0

    for field, (label, unit) in RAW_LABELS.items():
        value = getattr(metrics, field, None)
        if value is None:
            continue
        observed_index += 1
        items.append(
            EvidenceItem(
                id=f"O{observed_index}",
                kind="observed",
                label=label,
                value=value,
                unit=unit,
                source=f"métrica {metrics.source}",
            )
        )

    for field, value in derived.items():
        label, unit, formula = DERIVED_LABELS.get(field, (field, None, "cálculo determinístico"))
        calculated_index += 1
        items.append(
            EvidenceItem(
                id=f"C{calculated_index}",
                kind="calculated",
                label=label,
                value=value,
                unit=unit,
                source="calculado pelo Viral Intel",
                formula=formula,
            )
        )

    if benchmark.comparable_posts:
        benchmark_index += 1
        items.append(
            EvidenceItem(
                id=f"B{benchmark_index}",
                kind="benchmark",
                label="Posts comparáveis",
                value=benchmark.comparable_posts,
                unit="posts",
                source="histórico do próprio perfil",
                note=f"Estágio: {benchmark.lifecycle_bucket or 'não controlado'}",
            )
        )
    if benchmark.ratio_to_median is not None:
        benchmark_index += 1
        items.append(
            EvidenceItem(
                id=f"B{benchmark_index}",
                kind="benchmark",
                label=f"Razão vs mediana de {benchmark.primary_metric}",
                value=benchmark.ratio_to_median,
                unit="× mediana",
                source="histórico comparável do próprio perfil",
                formula=f"valor do post ÷ mediana de {benchmark.comparable_posts} posts comparáveis",
                note=f"Percentil {benchmark.percentile}",
            )
        )
    for name, ratio in benchmark.metric_ratios.items():
        if name == benchmark.primary_metric:
            continue
        benchmark_index += 1
        items.append(
            EvidenceItem(
                id=f"B{benchmark_index}",
                kind="benchmark",
                label=f"{name} vs mediana",
                value=ratio,
                unit="× mediana",
                source="histórico comparável do próprio perfil",
            )
        )

    for key, value in (technical or {}).items():
        if value in (None, "", [], {}):
            continue
        if key.startswith("public_"):
            observed_index += 1
            item_id, kind, source = f"O{observed_index}", "observed", "link público"
        elif key == "profile_history_summary":
            benchmark_index += 1
            item_id, kind, source = f"B{benchmark_index}", "benchmark", "histórico enviado do perfil"
        else:
            technical_index += 1
            item_id, kind, source = f"T{technical_index}", "technical", "inspeção local da mídia"
        items.append(
            EvidenceItem(
                id=item_id,
                kind=kind,
                label=key.replace("_", " ").capitalize(),
                value=value,
                source=source,
            )
        )

    for field in quality.missing:
        missing_index += 1
        items.append(
            EvidenceItem(
                id=f"M{missing_index}",
                kind="missing",
                label=field,
                value=None,
                source="não fornecido",
                note="Não pode ser presumido como zero.",
            )
        )
    return items
