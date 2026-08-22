"""Authorized Instagram professional-account collection through Meta's official API.

The collector is limited to media owned by the authenticated professional account. It
returns aggregate Insights and available comments and never attempts to discover private
liker, saver or sharer identities.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import requests

COMMON_INSIGHT_METRICS = (
    "views",
    "reach",
    "impressions",
    "likes",
    "comments",
    "shares",
    "saved",
    "total_interactions",
    "follows",
    "profile_visits",
    "profile_activity",
)
VIDEO_INSIGHT_METRICS = (
    "plays",
    "ig_reels_video_view_total_time",
    "ig_reels_avg_watch_time",
    "ig_reels_aggregated_all_plays_count",
    "clips_replays_count",
    "reels_skip_rate",
)
MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,permalink,timestamp,username,"
    "like_count,comments_count,thumbnail_url,media_url"
)
ACCOUNT_FIELDS = (
    "id,username,name,biography,website,followers_count,follows_count,media_count,profile_picture_url"
)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _insight_value(item: dict[str, Any]) -> float | int | None:
    values = item.get("values")
    if isinstance(values, list) and values:
        value = values[-1].get("value")
    else:
        value = item.get("value")
    if isinstance(value, dict):
        numeric = [entry for entry in value.values() if isinstance(entry, (int, float))]
        return sum(numeric) if numeric else None
    return value if isinstance(value, (int, float)) else None


class InstagramGraphCollector:
    """Read-only collector with batching, pagination and bounded retry/backoff."""

    def __init__(
        self,
        access_token: str,
        ig_user_id: str = "",
        api_version: str = "v25.0",
        max_comments: int = 300,
        timeout: int = 30,
        session: requests.Session | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        self.access_token = access_token.strip()
        self.ig_user_id = ig_user_id.strip()
        self.api_version = api_version.strip().lstrip("/") or "v25.0"
        self.max_comments = max(1, max_comments)
        self.timeout = max(5, timeout)
        self.session = session or requests.Session()
        self.max_retries = max(1, max_retries)
        self.backoff_seconds = max(0.1, backoff_seconds)
        self.base_url = f"https://graph.instagram.com/{self.api_version}"

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def _safe_error(self, exc: Exception) -> str:
        text = str(exc)
        if self.access_token:
            text = text.replace(self.access_token, "[TOKEN_OCULTO]")
        return f"{type(exc).__name__}: {text[:400]}"

    def _get_url(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        query["access_token"] = self.access_token
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=query, timeout=self.timeout)
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise RuntimeError(f"Resposta não JSON da Meta ({response.status_code})") from exc

                if response.status_code < 400 and not payload.get("error"):
                    return payload

                error = payload.get("error") or {}
                message = error.get("message") or f"HTTP {response.status_code}"
                code = error.get("code")
                current = RuntimeError(f"Meta API: {message}" + (f" (código {code})" if code else ""))
                last_error = current
                retryable = response.status_code in {429, 500, 502, 503, 504}
                if not retryable or attempt + 1 >= self.max_retries:
                    raise current
                headers = getattr(response, "headers", {}) or {}
                try:
                    retry_after = float(headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    retry_after = 0.0
                delay = max(retry_after, self.backoff_seconds * (2**attempt))
                time.sleep(min(delay, 20.0))
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 >= self.max_retries:
                    raise RuntimeError(f"Falha de rede na Meta API: {exc}") from exc
                time.sleep(min(self.backoff_seconds * (2**attempt), 20.0))
        raise last_error or RuntimeError("Falha desconhecida na Meta API")

    def _get(self, object_path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        clean = object_path.strip("/")
        return self._get_url(f"{self.base_url}/{clean}", params=params)

    def fetch_account(self) -> dict[str, Any]:
        if not self.ig_user_id:
            return {}
        return self._get(self.ig_user_id, {"fields": ACCOUNT_FIELDS})

    def fetch_media(self, media_id: str) -> dict[str, Any]:
        return self._get(media_id, {"fields": MEDIA_FIELDS})

    def fetch_comments(self, media_id: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        fields_options = (
            "id,text,timestamp,like_count,from,hidden,parent_id",
            "id,text,timestamp,from",
        )
        payload: dict[str, Any] | None = None
        last_error: Exception | None = None
        for fields in fields_options:
            try:
                payload = self._get(
                    f"{media_id}/comments",
                    {"fields": fields, "limit": min(self.max_comments, 100)},
                )
                break
            except Exception as exc:  # field availability changes by setup/version
                last_error = exc
        if payload is None:
            if last_error:
                raise last_error
            return comments

        while payload:
            for row in payload.get("data") or []:
                source = row.get("from") or {}
                comments.append(
                    {
                        "id": row.get("id"),
                        "author": source.get("username") if isinstance(source, dict) else None,
                        "author_id": source.get("id") if isinstance(source, dict) else None,
                        "text": row.get("text"),
                        "likes": row.get("like_count"),
                        "timestamp": row.get("timestamp"),
                        "hidden": row.get("hidden"),
                        "parent_id": row.get("parent_id"),
                    }
                )
                if len(comments) >= self.max_comments:
                    return comments
            next_url = ((payload.get("paging") or {}).get("next") or "").strip()
            if not next_url:
                break
            payload = self._get_url(next_url)
        return comments

    @staticmethod
    def _merge_insight_payload(payload: dict[str, Any], values: dict[str, Any]) -> None:
        for item in payload.get("data") or []:
            name = str(item.get("name") or "").strip()
            value = _insight_value(item)
            if name and value is not None:
                values[name] = value

    def _fetch_metric_batch(
        self,
        media_id: str,
        metrics: list[str],
        values: dict[str, Any],
        notes: list[str],
    ) -> None:
        """Query a metric group, bisecting only when the API rejects the group.

        This cuts normal history collection from dozens of requests per post to one or
        two while retaining the previous resilience when a metric is unavailable for a
        particular media type or API configuration.
        """

        if not metrics:
            return
        try:
            payload = self._get(f"{media_id}/insights", {"metric": ",".join(metrics)})
            self._merge_insight_payload(payload, values)
            return
        except Exception as exc:
            if len(metrics) == 1:
                notes.append(f"Métrica {metrics[0]} indisponível: {self._safe_error(exc)}")
                return
            midpoint = len(metrics) // 2
            self._fetch_metric_batch(media_id, metrics[:midpoint], values, notes)
            self._fetch_metric_batch(media_id, metrics[midpoint:], values, notes)

    def fetch_insights(self, media_id: str, media_type: str = "") -> tuple[dict[str, Any], list[str]]:
        metrics = list(COMMON_INSIGHT_METRICS)
        if media_type.upper() in {"VIDEO", "REELS", "REEL"}:
            metrics.extend(VIDEO_INSIGHT_METRICS)
        values: dict[str, Any] = {}
        notes: list[str] = []
        self._fetch_metric_batch(media_id, metrics, values, notes)
        return values, notes

    def list_recent_media(self, limit: int = 25) -> list[dict[str, Any]]:
        if not self.ig_user_id:
            return []
        limit = max(1, min(limit, 100))
        payload = self._get(f"{self.ig_user_id}/media", {"fields": MEDIA_FIELDS, "limit": limit})
        return list(payload.get("data") or [])[:limit]

    def resolve_media_id(self, permalink: str, limit: int = 50) -> str | None:
        target = permalink.strip().rstrip("/")
        if not target or not self.ig_user_id:
            return None
        for media in self.list_recent_media(limit=limit):
            candidate = str(media.get("permalink") or "").strip().rstrip("/")
            if candidate and candidate == target:
                return str(media.get("id") or "") or None
        return None

    def fetch_profile_history(self, limit: int = 20) -> tuple[list[dict[str, Any]], list[str]]:
        history: list[dict[str, Any]] = []
        notes: list[str] = []
        for media in self.list_recent_media(limit=limit):
            media_id = str(media.get("id") or "")
            if not media_id:
                continue
            media_type = str(media.get("media_product_type") or media.get("media_type") or "")
            insights, insight_notes = self.fetch_insights(media_id, media_type)
            notes.extend(f"{media_id}: {note}" for note in insight_notes)
            history.append(
                {
                    "post_id": media_id,
                    "post_url": media.get("permalink"),
                    "title": (media.get("caption") or "")[:160] or None,
                    "published_at": _parse_datetime(media.get("timestamp")),
                    "likes": insights.get("likes", media.get("like_count")),
                    "comments": insights.get("comments", media.get("comments_count")),
                    "shares": insights.get("shares"),
                    "saves": insights.get("saved"),
                    "views": insights.get("views") or insights.get("plays"),
                    "reach": insights.get("reach"),
                    "impressions": insights.get("impressions"),
                    "follows": insights.get("follows"),
                    "profile_visits": insights.get("profile_visits"),
                    "average_watch_time_seconds": (
                        float(insights["ig_reels_avg_watch_time"]) / 1000
                        if insights.get("ig_reels_avg_watch_time") is not None
                        else None
                    ),
                    "media_type": media.get("media_type"),
                    "media_product_type": media.get("media_product_type"),
                }
            )
        return history, notes

    def collect(
        self,
        media_id: str = "",
        permalink: str = "",
        include_history: bool = False,
        history_limit: int = 20,
    ) -> dict[str, Any]:
        if not self.configured:
            return {"source_ok": False, "error": "Token da Instagram API não configurado.", "source_notes": []}
        try:
            resolved_id = media_id.strip() or self.resolve_media_id(permalink) or ""
            if not resolved_id:
                return {
                    "source_ok": False,
                    "error": (
                        "Não foi possível localizar o ID da mídia. Informe o ID oficial ou use um link entre "
                        "as publicações recentes da conta autenticada."
                    ),
                    "source_notes": [],
                }
            media = self.fetch_media(resolved_id)
            media_type = str(media.get("media_product_type") or media.get("media_type") or "")
            insights, insight_notes = self.fetch_insights(resolved_id, media_type)
            comments = self.fetch_comments(resolved_id)
            account = self.fetch_account()
            history: list[dict[str, Any]] = []
            history_notes: list[str] = []
            if include_history:
                history, history_notes = self.fetch_profile_history(limit=history_limit)
            return {
                "source_ok": True,
                "collection_source": "meta/instagram-graph-authorized",
                "post_id": resolved_id,
                "webpage_url": media.get("permalink") or permalink,
                "caption": media.get("caption"),
                "uploader": media.get("username") or account.get("username"),
                "published_at": _parse_datetime(media.get("timestamp")),
                "followers": account.get("followers_count"),
                "likes": insights.get("likes", media.get("like_count")),
                "comments_count": insights.get("comments", media.get("comments_count")),
                "shares": insights.get("shares"),
                "saves": insights.get("saved"),
                "views": insights.get("views") or insights.get("plays"),
                "reach": insights.get("reach"),
                "impressions": insights.get("impressions"),
                "follows": insights.get("follows"),
                "profile_visits": insights.get("profile_visits"),
                "total_interactions": insights.get("total_interactions"),
                "average_watch_time_seconds": (
                    float(insights["ig_reels_avg_watch_time"]) / 1000
                    if insights.get("ig_reels_avg_watch_time") is not None
                    else None
                ),
                "comments_sample": comments,
                "account": account,
                "media": media,
                "insights_raw": insights,
                "profile_history": history,
                "source_notes": [
                    "Dados obtidos da API oficial para uma conta profissional autenticada.",
                    "Insights são consultados em lotes com fallback seletivo para reduzir latência e quota.",
                    "A API fornece contagens agregadas, mas não identifica pessoas que curtiram, salvaram ou compartilharam.",
                    *insight_notes,
                    *history_notes,
                ],
            }
        except Exception as exc:
            return {
                "source_ok": False,
                "error": self._safe_error(exc),
                "source_notes": [
                    "Verifique o token, as permissões, o ID da conta profissional e se a mídia pertence à conta autenticada."
                ],
            }
