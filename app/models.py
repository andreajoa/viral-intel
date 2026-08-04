"""Typed domain models used across Viral Intel.

The project deliberately distinguishes observed values, deterministic calculations,
and hypotheses. A missing metric is represented by ``None``; it is never silently
converted to zero.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Platform(StrEnum):
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    THREADS = "threads"
    OTHER = "other"


class ContentFormat(StrEnum):
    REEL = "reel"
    SHORT = "short"
    VIDEO = "video"
    CAROUSEL = "carousel"
    IMAGE = "image"
    TEXT = "text"
    UNKNOWN = "unknown"


PERCENT_FIELDS = {
    "completion_rate",
    "retention_3s_rate",
    "average_view_percentage",
    "non_follower_reach_rate",
    "engaged_non_follower_rate",
    "impressions_ctr",
    "skip_rate",
}

COUNT_FIELDS = {
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
    "replays",
}


class PostMetrics(BaseModel):
    """A single measurement snapshot for one post.

    Percentages use the human scale (``42.5`` means 42.5%), which matches the
    values shown by creator dashboards.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    platform: Platform = Platform.OTHER
    format: ContentFormat = ContentFormat.UNKNOWN
    post_id: str | None = None
    post_url: str | None = None
    title: str | None = None
    topic: str | None = None
    hook_type: str | None = None
    cta_type: str | None = None
    published_at: datetime | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_paid: bool = False
    is_original: bool | None = None
    recommendation_eligibility: Literal["eligible", "not_eligible", "unknown"] = "unknown"

    followers: int | None = None
    views: int | None = None
    reach: int | None = None
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    reposts: int | None = None
    follows: int | None = None
    profile_visits: int | None = None
    profile_activity: int | None = None
    total_interactions: int | None = None
    accounts_engaged: int | None = None

    followers_reach: int | None = None
    non_followers_reach: int | None = None
    home_impressions: int | None = None
    explore_impressions: int | None = None
    profile_impressions: int | None = None
    hashtag_impressions: int | None = None

    duration_seconds: float | None = None
    average_watch_time_seconds: float | None = None
    completion_rate: float | None = None
    retention_3s_rate: float | None = None
    average_view_percentage: float | None = None
    non_follower_reach_rate: float | None = None
    engaged_non_follower_rate: float | None = None
    impressions_ctr: float | None = None
    replays: int | None = None
    skip_rate: float | None = None

    source: Literal[
        "manual",
        "public",
        "official_api",
        "mixed",
        "profile_csv",
        "screenshot",
    ] = "manual"
    source_notes: list[str] = Field(default_factory=list)

    @field_validator(*sorted(COUNT_FIELDS))
    @classmethod
    def counts_must_be_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("contagens não podem ser negativas")
        return value

    @field_validator("duration_seconds", "average_watch_time_seconds")
    @classmethod
    def durations_must_be_non_negative(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("durações não podem ser negativas")
        return value

    @field_validator(*sorted(PERCENT_FIELDS))
    @classmethod
    def percentages_must_be_human_scale(cls, value: float | None) -> float | None:
        if value is not None and not 0 <= value <= 100:
            raise ValueError("percentuais devem ficar entre 0 e 100")
        return value

    @field_validator("captured_at", "published_at")
    @classmethod
    def make_datetime_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @property
    def age_hours(self) -> float | None:
        if not self.published_at:
            return None
        return max(0.0, (self.captured_at - self.published_at).total_seconds() / 3600)


class EvidenceItem(BaseModel):
    id: str
    kind: Literal["observed", "calculated", "benchmark", "technical", "missing"]
    label: str
    value: Any = None
    unit: str | None = None
    source: str
    formula: str | None = None
    note: str | None = None


class DataQuality(BaseModel):
    level: Literal["ALTA", "MÉDIA", "BAIXA"]
    completeness_score: int = Field(ge=0, le=100)
    present: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class BenchmarkResult(BaseModel):
    status: Literal[
        "BREAKOUT",
        "ACIMA_DO_TÍPICO",
        "TÍPICO",
        "ABAIXO_DO_TÍPICO",
        "INCONCLUSIVO",
    ] = "INCONCLUSIVO"
    label: str = "Dados insuficientes para comparar com o perfil"
    comparable_posts: int = 0
    lifecycle_bucket: str | None = None
    primary_metric: str | None = None
    target_value: float | None = None
    median_value: float | None = None
    ratio_to_median: float | None = None
    percentile: float | None = None
    metric_medians: dict[str, float] = Field(default_factory=dict)
    metric_ratios: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class AnalysisEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str = "3.0"
    report_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metrics: PostMetrics
    derived_metrics: dict[str, float]
    benchmark: BenchmarkResult
    data_quality: DataQuality
    evidence: list[EvidenceItem]
    technical_analysis: dict[str, Any] = Field(default_factory=dict)
    transcription: str = ""
    strategy: dict[str, Any] = Field(default_factory=dict)
    provider: str = "deterministic"
    model: str = "evidence-engine-v3"
    provider_errors: list[str] = Field(default_factory=list)
