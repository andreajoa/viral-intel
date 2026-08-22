"""Authorized YouTube Data + Analytics API collector."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests

ANALYTICS_METRICS = (
    "views,likes,comments,shares,averageViewDuration,averageViewPercentage,subscribersGained"
)
REACH_METRICS = "videoThumbnailImpressions,videoThumbnailImpressionsClickRate"
_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>[\d.]+)S)?)?$"
)


def _iso_duration_seconds(value: str | None) -> float | None:
    match = _DURATION_RE.match(str(value or ""))
    if not match:
        return None
    parts = {key: float(number or 0) for key, number in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class YouTubeAnalyticsCollector:
    def __init__(self, access_token: str, timeout: int = 30, session: requests.Session | None = None):
        self.access_token = access_token.strip()
        self.timeout = max(5, timeout)
        self.session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    def _safe_error(self, exc: Exception) -> str:
        detail = str(exc).replace(self.access_token, "[TOKEN_OCULTO]") if self.access_token else str(exc)
        return f"{type(exc).__name__}: {detail[:320]}"

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(url, params=params, headers=self._headers(), timeout=self.timeout)
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"YouTube retornou HTTP {response.status_code} sem JSON") from exc
        if response.status_code >= 400 or data.get("error"):
            error = data.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise RuntimeError(f"YouTube API: {message or f'HTTP {response.status_code}'}")
        return data

    def fetch_channel(self) -> dict[str, Any]:
        data = self._get(
            "https://www.googleapis.com/youtube/v3/channels",
            {"part": "snippet,statistics", "mine": "true"},
        )
        items = data.get("items") or []
        if not items:
            return {}
        item = items[0]
        snippet = item.get("snippet") or {}
        stats = item.get("statistics") or {}
        return {
            "id": item.get("id"),
            "username": snippet.get("customUrl") or snippet.get("title"),
            "display_name": snippet.get("title"),
            "follower_count": int(stats["subscriberCount"]) if str(stats.get("subscriberCount") or "").isdigit() else None,
            "video_count": int(stats["videoCount"]) if str(stats.get("videoCount") or "").isdigit() else None,
        }

    def fetch_videos(self, video_ids: list[str]) -> dict[str, dict[str, Any]]:
        clean = [video_id for video_id in dict.fromkeys(video_ids) if video_id][:50]
        if not clean:
            return {}
        data = self._get(
            "https://www.googleapis.com/youtube/v3/videos",
            {"part": "snippet,contentDetails,statistics", "id": ",".join(clean)},
        )
        return {str(item.get("id")): item for item in data.get("items") or [] if item.get("id")}

    @staticmethod
    def _analytics_map(data: dict[str, Any]) -> dict[str, Any]:
        headers = [str(item.get("name") or "") for item in data.get("columnHeaders") or []]
        rows = data.get("rows") or []
        if not rows:
            return {}
        return dict(zip(headers, rows[0], strict=False))

    def fetch_video_analytics(self, video_id: str, start_date: date, end_date: date) -> tuple[dict[str, Any], list[str]]:
        base = {
            "ids": "channel==MINE",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "filters": f"video=={video_id}",
        }
        notes: list[str] = []
        core = self._get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            {**base, "metrics": ANALYTICS_METRICS},
        )
        values = self._analytics_map(core)
        try:
            reach = self._get(
                "https://youtubeanalytics.googleapis.com/v2/reports",
                {**base, "metrics": REACH_METRICS},
            )
            values.update(self._analytics_map(reach))
        except Exception as exc:
            notes.append(f"Métricas de impressão/CTR indisponíveis: {self._safe_error(exc)}")
        return values, notes

    def fetch_history(self, limit: int = 25, days: int = 120) -> list[dict[str, Any]]:
        end = datetime.now(UTC).date()
        start = end - timedelta(days=max(30, days))
        data = self._get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            {
                "ids": "channel==MINE",
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "metrics": ANALYTICS_METRICS,
                "dimensions": "video",
                "sort": "-views",
                "maxResults": max(1, min(limit, 50)),
            },
        )
        headers = [str(item.get("name") or "") for item in data.get("columnHeaders") or []]
        rows = [dict(zip(headers, row, strict=False)) for row in data.get("rows") or []]
        ids = [str(row.get("video") or "") for row in rows if row.get("video")]
        metadata = self.fetch_videos(ids)
        history: list[dict[str, Any]] = []
        for row in rows:
            video_id = str(row.get("video") or "")
            item = metadata.get(video_id) or {}
            snippet = item.get("snippet") or {}
            details = item.get("contentDetails") or {}
            history.append(
                {
                    "post_id": video_id,
                    "post_url": f"https://www.youtube.com/watch?v={video_id}",
                    "title": snippet.get("title"),
                    "published_at": _parse_datetime(snippet.get("publishedAt")),
                    "views": row.get("views"),
                    "likes": row.get("likes"),
                    "comments": row.get("comments"),
                    "shares": row.get("shares"),
                    "follows": row.get("subscribersGained"),
                    "average_watch_time_seconds": row.get("averageViewDuration"),
                    "average_view_percentage": row.get("averageViewPercentage"),
                    "duration_seconds": _iso_duration_seconds(details.get("duration")),
                    "media_type": "VIDEO",
                    "media_product_type": "YOUTUBE",
                }
            )
        return history

    def collect(self, *, video_id: str, include_history: bool = False, history_limit: int = 25) -> dict[str, Any]:
        if not self.configured:
            return {"source_ok": False, "error": "Token OAuth do YouTube não configurado.", "source_notes": []}
        if not video_id.strip():
            return {"source_ok": False, "error": "Informe o ID do vídeo do YouTube para coleta autorizada.", "source_notes": []}
        try:
            metadata = self.fetch_videos([video_id.strip()]).get(video_id.strip()) or {}
            snippet = metadata.get("snippet") or {}
            details = metadata.get("contentDetails") or {}
            published = _parse_datetime(snippet.get("publishedAt"))
            start = published.date() if published else date(2005, 2, 14)
            end = datetime.now(UTC).date()
            analytics, notes = self.fetch_video_analytics(video_id.strip(), start, end)
            try:
                account = self.fetch_channel()
            except Exception as exc:
                account = {}
                notes.append(f"Metadados do canal indisponíveis: {self._safe_error(exc)}")
            history = self.fetch_history(history_limit) if include_history else []
            return {
                "source_ok": True,
                "collection_source": "youtube-data-and-analytics-authorized",
                "post_id": video_id.strip(),
                "webpage_url": f"https://www.youtube.com/watch?v={video_id.strip()}",
                "caption": snippet.get("description") or snippet.get("title"),
                "uploader": snippet.get("channelTitle") or account.get("display_name"),
                "published_at": published,
                "followers": account.get("follower_count"),
                "views": analytics.get("views"),
                "likes": analytics.get("likes"),
                "comments_count": analytics.get("comments"),
                "shares": analytics.get("shares"),
                "follows": analytics.get("subscribersGained"),
                "average_watch_time_seconds": analytics.get("averageViewDuration"),
                "average_view_percentage": analytics.get("averageViewPercentage"),
                "impressions": analytics.get("videoThumbnailImpressions"),
                "impressions_ctr": analytics.get("videoThumbnailImpressionsClickRate"),
                "duration_seconds": _iso_duration_seconds(details.get("duration")),
                "account": account,
                "media": metadata,
                "insights_raw": analytics,
                "profile_history": history,
                "source_notes": [
                    "Dados obtidos das APIs oficiais YouTube Data e YouTube Analytics com OAuth do proprietário.",
                    "Average view duration e average view percentage são métricas oficiais quando retornadas pelo relatório autorizado.",
                    *notes,
                ],
            }
        except Exception as exc:
            return {
                "source_ok": False,
                "error": self._safe_error(exc),
                "source_notes": [
                    "Confirme o token OAuth e os escopos de leitura do YouTube Data e YouTube Analytics."
                ],
            }
