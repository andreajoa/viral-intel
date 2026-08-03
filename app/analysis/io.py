"""Input helpers for profile-history CSV files and public/manual metric merging."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from app.models import ContentFormat, Platform, PostMetrics

NUMERIC_FIELDS = {
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
    "total_interactions",
    "duration_seconds",
    "average_watch_time_seconds",
    "completion_rate",
    "retention_3s_rate",
    "average_view_percentage",
    "non_follower_reach_rate",
    "impressions_ctr",
}


def parse_optional_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return value
    text = str(value).strip().replace("%", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        tail = text.rsplit(",", 1)[1]
        text = text.replace(",", ".") if len(tail) <= 2 else text.replace(",", "")
    return float(text) if "." in text else int(text)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def profile_posts_from_csv(raw: bytes | str) -> list[PostMetrics]:
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    posts: list[PostMetrics] = []
    for index, row in enumerate(csv.DictReader(StringIO(text)), start=2):
        if not any(value not in (None, "") for value in row.values()):
            continue
        cleaned: dict[str, Any] = {key.strip(): value for key, value in row.items() if key}
        for field in NUMERIC_FIELDS:
            if field in cleaned:
                cleaned[field] = parse_optional_number(cleaned[field])
        for field in ("published_at", "captured_at"):
            if cleaned.get(field):
                cleaned[field] = _parse_datetime(cleaned[field])
        cleaned["platform"] = str(cleaned.get("platform") or "other").lower()
        cleaned["format"] = str(cleaned.get("format") or "unknown").lower()
        cleaned["source"] = "profile_csv"
        try:
            posts.append(PostMetrics.model_validate(cleaned))
        except Exception as exc:
            raise ValueError(f"Linha {index} do CSV inválida: {exc}") from exc
    return posts


def merge_metric_sources(
    platform: Platform | str,
    content_format: ContentFormat | str,
    manual: dict[str, Any] | PostMetrics | None,
    public: dict[str, Any] | None,
) -> PostMetrics:
    """Merge public metadata with manual Insights; manual values always win."""

    public = public or {}
    base: dict[str, Any] = {
        "platform": platform,
        "format": content_format,
        "post_id": public.get("post_id"),
        "post_url": public.get("webpage_url"),
        "title": public.get("title"),
        "published_at": public.get("published_at"),
        "followers": public.get("followers"),
        "views": public.get("views"),
        "likes": public.get("likes"),
        "comments": public.get("comments_count"),
        "shares": public.get("shares"),
        "reposts": public.get("reposts"),
        "duration_seconds": public.get("duration_seconds"),
        "source": "public" if public else "manual",
        "source_notes": public.get("source_notes") or [],
    }
    if isinstance(manual, PostMetrics):
        manual_data = manual.model_dump(exclude_none=True)
    else:
        manual_data = {
            key: value for key, value in (manual or {}).items() if value is not None and value != ""
        }
    base.update(manual_data)
    base["platform"] = platform
    base["format"] = content_format
    if public and manual_data:
        base["source"] = "mixed"
        base.setdefault("source_notes", []).append(
            "Métricas digitadas manualmente têm prioridade sobre dados públicos."
        )
    return PostMetrics.model_validate(base)
