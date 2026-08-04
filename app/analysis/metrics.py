"""Transparent metric calculations and data-completeness checks."""

from __future__ import annotations

from collections.abc import Iterable

from app.models import ContentFormat, DataQuality, Platform, PostMetrics


def _ratio(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return float(numerator) / float(denominator)


def _percent(numerator: float | int | None, denominator: float | int | None) -> float | None:
    ratio = _ratio(numerator, denominator)
    return ratio * 100 if ratio is not None else None


def _sum_known(values: Iterable[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def derive_metrics(metrics: PostMetrics) -> dict[str, float]:
    """Calculate only values supported by the supplied snapshot.

    No absent metric is treated as zero. Rates are returned as percentages. Ratios
    between interaction types describe the composition of this post only; they are not
    universal performance thresholds or the private ranking weights used by a platform.
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
        "circulation_to_likes_pct": _percent(circulation_actions, metrics.likes),
        "comments_to_likes_pct": _percent(metrics.comments, metrics.likes),
        "circulation_to_comments_ratio": _ratio(circulation_actions, metrics.comments),
        "engagement_by_views_pct": _percent(interactions, metrics.views),
        "engagement_by_reach_pct": _percent(interactions, metrics.reach),
        "accounts_engaged_by_reach_pct": _percent(metrics.accounts_engaged, metrics.reach),
        "views_per_follower_pct": _percent(metrics.views, metrics.followers),
        "reach_per_follower_pct": _percent(metrics.reach, metrics.followers),
        "impressions_per_reached_account": _ratio(metrics.impressions, metrics.reach),
        "like_rate_by_views_pct": _percent(metrics.likes, metrics.views),
        "like_rate_by_reach_pct": _percent(metrics.likes, metrics.reach),
        "comment_rate_by_views_pct": _percent(metrics.comments, metrics.views),
        "comment_rate_by_reach_pct": _percent(metrics.comments, metrics.reach),
        "share_rate_by_views_pct": _percent(metrics.shares, metrics.views),
        "share_rate_by_reach_pct": _percent(metrics.shares, metrics.reach),
        "save_rate_by_views_pct": _percent(metrics.saves, metrics.views),
        "save_rate_by_reach_pct": _percent(metrics.saves, metrics.reach),
        "replay_rate_by_views_pct": _percent(metrics.replays, metrics.views),
        "follow_conversion_by_reach_pct": _percent(metrics.follows, metrics.reach),
        "follows_per_1000_reached": (
            _ratio(metrics.follows, metrics.reach) * 1000
            if _ratio(metrics.follows, metrics.reach) is not None
            else None
        ),
        "profile_visit_rate_by_reach_pct": _percent(metrics.profile_visits, metrics.reach),
        "profile_visit_conversion_pct": _percent(metrics.follows, metrics.profile_visits),
        "non_follower_reach_calculated_pct": _percent(
            metrics.non_followers_reach, metrics.reach
        ),
        "followers_reach_calculated_pct": _percent(metrics.followers_reach, metrics.reach),
        "home_impressions_share_pct": _percent(metrics.home_impressions, metrics.impressions),
        "explore_impressions_share_pct": _percent(
            metrics.explore_impressions, metrics.impressions
        ),
        "profile_impressions_share_pct": _percent(
            metrics.profile_impressions, metrics.impressions
        ),
        "hashtag_impressions_share_pct": _percent(
            metrics.hashtag_impressions, metrics.impressions
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
        candidates["average_shares_per_hour_since_publish"] = _ratio(
            metrics.shares, metrics.age_hours
        )

    for key, value in candidates.items():
        if value is not None:
            results[key] = round(float(value), 4)
    return results


def _required_fields(metrics: PostMetrics) -> tuple[list[str], list[str]]:
    common = ["followers", "views", "likes", "comments", "shares", "published_at"]
    depth: list[str]

    if metrics.platform == Platform.INSTAGRAM:
        common += ["reach", "saves"]
        depth = [
            "non_follower_reach_rate",
            "follows",
            "profile_visits",
            "accounts_engaged",
        ]
        if metrics.format in {ContentFormat.REEL, ContentFormat.VIDEO}:
            depth += ["average_watch_time_seconds", "completion_rate"]
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
    if metrics.source == "official_api":
        limitations.append(
            "A API oficial entrega métricas agregadas, mas não os pesos do ranking nem identidades de quem compartilhou, salvou ou curtiu."
        )
    if metrics.source in {"screenshot", "mixed"} and any(
        "captura" in note.lower() for note in metrics.source_notes
    ):
        limitations.append(
            "Contagens lidas de uma captura precisam ser confirmadas nos Insights do proprietário."
        )
    if not any(getattr(metrics, name, None) is not None for name in depth):
        limitations.append(
            "Sem métricas de profundidade, expansão e conversão, a trajetória de distribuição não pode ser reconstruída."
        )
    if metrics.platform == Platform.INSTAGRAM and metrics.non_follower_reach_rate is None:
        limitations.append(
            "Sem alcance de não seguidores, não é possível confirmar a expansão para além da base."
        )

    return DataQuality(
        level=level,
        completeness_score=score,
        present=present,
        missing=missing,
        limitations=limitations,
    )
