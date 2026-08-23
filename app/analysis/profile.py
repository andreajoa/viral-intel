"""Profile-relative benchmarking using robust, lifecycle-aware statistics."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from app.analysis.metrics import derive_metrics
from app.analysis.robust_stats import percentile, robust_expected_range
from app.models import BenchmarkResult, PostMetrics

BENCHMARK_METRICS = (
    "views",
    "reach",
    "interactions_known",
    "share_rate_by_views_pct",
    "save_rate_by_views_pct",
    "average_view_percentage",
    "follow_conversion_by_reach_pct",
)


def lifecycle_bucket(age_hours: float | None) -> str | None:
    if age_hours is None:
        return None
    if age_hours < 6:
        return "0–6h"
    if age_hours < 24:
        return "6–24h"
    if age_hours < 72:
        return "1–3d"
    if age_hours < 168:
        return "3–7d"
    return "7d+"


def _row_values(post: PostMetrics) -> dict[str, float]:
    derived = derive_metrics(post)
    values: dict[str, float] = {}
    if post.views is not None:
        values["views"] = float(post.views)
    if post.reach is not None:
        values["reach"] = float(post.reach)
    values.update({key: value for key, value in derived.items() if key in BENCHMARK_METRICS})
    return values


def comparable_posts(target: PostMetrics, history: list[PostMetrics]) -> tuple[list[PostMetrics], list[str]]:
    warnings: list[str] = []
    candidates = [
        post
        for post in history
        if post.platform == target.platform
        and post.format == target.format
        and post.is_paid == target.is_paid
        and (not target.post_id or post.post_id != target.post_id)
    ]

    target_bucket = lifecycle_bucket(target.age_hours)
    if target_bucket:
        bucketed = [post for post in candidates if lifecycle_bucket(post.age_hours) == target_bucket]
        if len(bucketed) >= 5:
            candidates = bucketed
        elif target_bucket != "7d+":
            warnings.append(
                "Poucos posts no mesmo estágio de vida; a comparação foi mantida ampla e deve ser lida com cautela."
            )
    else:
        warnings.append("O estágio de vida do post não pôde ser controlado.")
    return candidates, warnings


def build_benchmark(target: PostMetrics, history: list[PostMetrics]) -> BenchmarkResult:
    """Build an uncertainty-aware benchmark from the profile's own comparable posts.

    Viral Intel 5 no longer decides performance from universal 0.75x/1.5x/3x thresholds.
    It models the profile's observed dispersion in log space, then uses percentile,
    robust anomaly score and quality metrics together. Ratio-to-median remains visible
    for human readability and backwards compatibility.
    """

    candidates, warnings = comparable_posts(target, history)
    target_values = _row_values(target)
    result = BenchmarkResult(
        comparable_posts=len(candidates),
        lifecycle_bucket=lifecycle_bucket(target.age_hours),
        warnings=warnings,
    )

    if len(candidates) < 5:
        result.warnings.append(
            "São necessários pelo menos 5 posts comparáveis; 10 ou mais aumentam a força da evidência."
        )
        return result

    history_values = [_row_values(post) for post in candidates]
    medians: dict[str, float] = {}
    ratios: dict[str, float] = {}
    for metric in BENCHMARK_METRICS:
        values = [row[metric] for row in history_values if metric in row]
        if len(values) < 5:
            continue
        med = float(median(values))
        medians[metric] = round(med, 4)
        target_value = target_values.get(metric)
        if target_value is not None and med > 0:
            ratios[metric] = round(target_value / med, 4)

    result.metric_medians = medians
    result.metric_ratios = ratios
    primary = "views" if "views" in target_values and "views" in medians else "reach"
    if primary not in target_values or primary not in medians:
        result.warnings.append("Não há uma métrica principal comum suficiente para classificar o desempenho.")
        return result

    target_value = target_values[primary]
    primary_values = [row[primary] for row in history_values if primary in row]
    ratio = target_value / medians[primary] if medians[primary] else None
    stats = robust_expected_range(primary_values, target_value)

    result.primary_metric = primary
    result.target_value = target_value
    result.median_value = medians[primary]
    result.ratio_to_median = round(ratio, 4) if ratio is not None else None
    result.percentile = percentile(primary_values, target_value)
    result.expected_low = stats["expected_low"]
    result.expected_high = stats["expected_high"]
    result.robust_z_score = stats["robust_z_score"]
    result.baseline_dispersion_pct = stats["dispersion_pct"]
    result.evidence_strength = stats["evidence_strength"]  # type: ignore[assignment]

    quality_ratios = [
        ratios[name]
        for name in (
            "share_rate_by_views_pct",
            "save_rate_by_views_pct",
            "average_view_percentage",
            "follow_conversion_by_reach_pct",
        )
        if name in ratios
    ]
    quality_support = median(quality_ratios) if quality_ratios else None
    z_score = result.robust_z_score or 0.0
    pct = result.percentile or 0.0
    high = result.expected_high
    low = result.expected_low

    breakout_shape = (
        len(candidates) >= 8
        and high is not None
        and target_value > high
        and z_score >= 2.5
        and pct >= 90
        and ratio is not None
        and ratio >= 1.5
    )
    if breakout_shape and quality_support is not None and quality_support >= 1.10:
        result.status = "BREAKOUT"
        result.label = (
            "Resultado fora do intervalo esperado do próprio perfil e sustentado por sinal de qualidade"
        )
    elif high is not None and (target_value > high or z_score >= 1.5 or pct >= 85):
        result.status = "ACIMA_DO_TÍPICO"
        result.label = "Acima do intervalo típico estimado para o próprio perfil"
        if breakout_shape and quality_support is None:
            result.warnings.append(
                "O volume está fora da curva, mas faltam métricas de qualidade para classificar breakout."
            )
    elif low is not None and (target_value < low or z_score <= -1.5 or pct <= 15):
        result.status = "ABAIXO_DO_TÍPICO"
        result.label = "Abaixo do intervalo típico estimado para o próprio perfil"
    else:
        result.status = "TÍPICO"
        result.label = "Dentro do intervalo esperado do próprio perfil"

    if len(primary_values) < 8:
        result.evidence_strength = "FRACA"
        result.warnings.append(
            "A classificação usa uma amostra pequena; trate o intervalo esperado como orientação, não como previsão estável."
        )
    return result


def summarize_profile(history: list[PostMetrics]) -> dict[str, object]:
    """Describe the profile history without attributing causality."""

    if not history:
        return {"posts": 0, "warning": "Nenhum histórico do perfil foi fornecido."}

    def grouped(field: str) -> list[dict[str, object]]:
        groups: dict[str, list[PostMetrics]] = defaultdict(list)
        for post in history:
            value = getattr(post, field, None)
            if value:
                groups[str(getattr(value, "value", value))].append(post)
        rows: list[dict[str, object]] = []
        for name, posts in groups.items():
            views = [post.views for post in posts if post.views is not None]
            reach = [post.reach for post in posts if post.reach is not None]
            share_rates: list[float] = []
            for post in posts:
                value = derive_metrics(post).get("share_rate_by_views_pct")
                if value is not None:
                    share_rates.append(value)
            rows.append(
                {
                    "name": name,
                    "posts": len(posts),
                    "median_views": round(float(median(views)), 2) if views else None,
                    "median_reach": round(float(median(reach)), 2) if reach else None,
                    "median_share_rate_pct": round(float(median(share_rates)), 4) if share_rates else None,
                    "pattern_confidence": "usable" if len(posts) >= 5 else "small_sample",
                }
            )
        return sorted(rows, key=lambda row: (row["posts"], row.get("median_views") or 0), reverse=True)

    published = sorted(post.published_at for post in history if post.published_at)
    cadence: dict[str, object] = {"posts_with_date": len(published)}
    if len(published) >= 2:
        span_days = max((published[-1] - published[0]).total_seconds() / 86400, 1)
        cadence.update(
            {
                "date_span_days": round(span_days, 1),
                "average_posts_per_week": round((len(published) / span_days) * 7, 2),
            }
        )

    top = sorted(
        (post for post in history if post.views is not None), key=lambda post: post.views or 0, reverse=True
    )[:5]
    return {
        "posts": len(history),
        "platform_format_groups": [
            {
                "name": f"{row['name']}",
                **{key: value for key, value in row.items() if key != "name"},
            }
            for row in grouped("format")
        ],
        "topics": grouped("topic"),
        "hook_types": grouped("hook_type"),
        "cta_types": grouped("cta_type"),
        "cadence": cadence,
        "top_posts_by_views": [
            {
                "post_id": post.post_id,
                "views": post.views,
                "format": post.format.value,
                "topic": post.topic,
                "hook_type": post.hook_type,
            }
            for post in top
        ],
        "interpretation_rule": (
            "Associações com menos de 5 posts são amostra pequena; diferenças observadas não provam causalidade. "
            "A classificação geral usa intervalo robusto do próprio perfil, não limiares universais de viralização."
        ),
    }
