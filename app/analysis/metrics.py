"""Transparent metric calculations and data-completeness checks."""

from __future__ import annotations

from collections.abc import Iterable

from app.models import ContentFormat, DataQuality, Platform, PostMetrics


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _sum_known(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def derive_metrics(metrics: PostMetrics) -> dict[str, float]:
    """Calculate only values supported by the supplied snapshot.

    No absent metric is treated as zero. Rates are returned as percentages. Ratios
    between visible interaction types describe the composition of this post only;
    they are not universal performance thresholds.
    """

    interactions = metrics.total_interactions
    if interactions is None:
        interactions = _sum_known(
            [metrics.likes, metrics.comments, metrics.shares, metrics.saves, metrics.reposts]
        )
    circulation_actions = _sum_known([metrics.shares, metrics.reposts])

    results: dict[str, float] = {}
    candidates = {
        "interactions_known": float(interactions) if interactions is not None else None,
        "circulation_actions_known": (
            float(circulation_actions) if circulation_actions is not None else None
        ),
        "circulation_to_likes_pct": (
            _ratio(circulation_actions, metrics.likes) * 100
            if _ratio(circulation_actions, metrics.likes) is not None
            else None
        ),
        "comments_to_likes_pct": (
            _ratio(metrics.comments, metrics.likes) * 100
            if _ratio(metrics.comments, metrics.likes) is not None
            else None
        ),
        "circulation_to_comments_ratio": _ratio(circulation_actions, metrics.comments),
        "engagement_by_views_pct": (
            _ratio(interactions, metrics.views) * 100
            if _ratio(interactions, metrics.views) is not None
            else None
        ),
        "engagement_by_reach_pct": (
            _ratio(interactions, metrics.reach) * 100
            if _ratio(interactions, metrics.reach) is not None
            else None
        ),
        "views_per_follower_pct": (
            _ratio(metrics.views, metrics.followers) * 100
            if _ratio(metrics.views, metrics.followers) is not None
            else None
        ),
        "reach_per_follower_pct": (
            _ratio(metrics.reach, metrics.followers) * 100
            if _ratio(metrics.reach, metrics.followers) is not None
            else None
        ),
        "like_rate_by_views_pct": (
            _ratio(metrics.likes, metrics.views) * 100
            if _ratio(metrics.likes, metrics.views) is not None
            else None
        ),
        "comment_rate_by_views_pct": (
            _ratio(metrics.comments, metrics.views) * 100
            if _ratio(metrics.comments, metrics.views) is not None
            else None
        ),
        "share_rate_by_views_pct": (
            _ratio(metrics.shares, metrics.views) * 100
            if _ratio(metrics.shares, metrics.views) is not None
            else None
        ),
        "save_rate_by_views_pct": (
            _ratio(metrics.saves, metrics.views) * 100
            if _ratio(metrics.saves, metrics.views) is not None
            else None
        ),
        "follow_conversion_by_reach_pct": (
            _ratio(metrics.follows, metrics.reach) * 100
            if _ratio(metrics.follows, metrics.reach) is not None
            else None
        ),
        "profile_visit_conversion_pct": (
            _ratio(metrics.follows, metrics.profile_visits) * 100
            if _ratio(metrics.follows, metrics.profile_visits) is not None
            else None
        ),
    }

    watch_pct = metrics.average_view_percentage
    if watch_pct is None:
        watch_ratio = _ratio(metrics.average_watch_time_seconds, metrics.duration_seconds)
        watch_pct = watch_ratio * 100 if watch_ratio is not None else None
    candidates["average_view_percentage"] = watch_pct

    if metrics.age_hours not in (None, 0):
        candidates["average_views_per_hour_since_publish"] = _ratio(metrics.views, metrics.age_hours)
        candidates["average_reach_per_hour_since_publish"] = _ratio(metrics.reach, metrics.age_hours)

    for key, value in candidates.items():
        if value is not None:
            results[key] = round(float(value), 4)
    return results


def _required_fields(metrics: PostMetrics) -> tuple[list[str], list[str]]:
    common = ["followers", "views", "likes", "comments", "shares", "published_at"]
    depth: list[str]

    if metrics.platform == Platform.INSTAGRAM:
        common += ["reach", "saves"]
        depth = ["average_watch_time_seconds", "completion_rate", "non_follower_reach_rate", "follows"]
    elif metrics.platform == Platform.TIKTOK:
        common += ["saves"]
        depth = ["average_watch_time_seconds", "completion_rate", "retention_3s_rate", "follows"]
    elif metrics.platform == Platform.YOUTUBE:
        common += ["impressions"]
        depth = ["impressions_ctr", "average_watch_time_seconds", "average_view_percentage", "follows"]
    else:
        depth = ["reach", "saves", "average_watch_time_seconds", "follows"]

    if metrics.format in {ContentFormat.IMAGE, ContentFormat.CAROUSEL, ContentFormat.TEXT}:
        depth = [
            name
            for name in depth
            if "watch" not in name and "completion" not in name and "retention" not in name
        ]
    return common, depth


def assess_data_quality(metrics: PostMetrics, comparable_posts: int) -> DataQuality:
    common, depth = _required_fields(metrics)
    fields = common + depth
    present = [name for name in fields if getattr(metrics, name, None) is not None]
    missing = [name for name in fields if getattr(metrics, name, None) is None]

    common_score = sum(getattr(metrics, name, None) is not None for name in common) / max(1, len(common))
    depth_score = sum(getattr(metrics, name, None) is not None for name in depth) / max(1, len(depth))
    benchmark_score = min(1.0, comparable_posts / 10)
    score = round((common_score * 50) + (depth_score * 25) + (benchmark_score * 25))

    if score >= 80 and comparable_posts >= 8:
        level = "ALTA"
    elif score >= 50:
        level = "MÉDIA"
    else:
        level = "BAIXA"

    limitations: list[str] = []
    if comparable_posts < 5:
        limitations.append("Há menos de 5 posts comparáveis do próprio perfil.")
    if metrics.published_at is None:
        limitations.append("Sem data de publicação, não é possível controlar o estágio de vida do post.")
    if metrics.source == "public":
        limitations.append("Dados públicos não incluem todas as métricas privadas de Insights.")
    if metrics.source in {"screenshot", "mixed"} and any(
        "captura" in note.lower() for note in metrics.source_notes
    ):
        limitations.append(
            "Contagens lidas de uma captura precisam ser confirmadas nos Insights do proprietário."
        )
    if not any(getattr(metrics, name, None) is not None for name in depth):
        limitations.append(
            "Sem métricas de profundidade, a retenção ou a qualidade da interação não pode ser confirmada."
        )

    return DataQuality(
        level=level,
        completeness_score=score,
        present=present,
        missing=missing,
        limitations=limitations,
    )
