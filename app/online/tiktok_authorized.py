"""Authorized TikTok Display API collector.

The Display API exposes creator-authorized public-video metadata and aggregate public
counts. It does not expose private ranking weights or deep retention/watch-time data,
so unavailable fields remain absent rather than being estimated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import requests

VIDEO_FIELDS = (
    "id,create_time,share_url,video_description,duration,height,width,title,"
    "like_count,comment_count,share_count,view_count"
)
USER_FIELDS = "open_id,username,display_name,follower_count,following_count,likes_count,video_count"


class TikTokAuthorizedCollector:
    def __init__(self, access_token: str, timeout: int = 30, session: requests.Session | None = None):
        self.access_token = access_token.strip()
        self.timeout = max(5, timeout)
        self.session = session or requests.Session()
        self.base_url = "https://open.tiktokapis.com/v2"

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _safe_error(self, exc: Exception) -> str:
        detail = str(exc).replace(self.access_token, "[TOKEN_OCULTO]") if self.access_token else str(exc)
        return f"{type(exc).__name__}: {detail[:320]}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        fields: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            params={"fields": fields},
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"TikTok retornou HTTP {response.status_code} sem JSON") from exc
        error = data.get("error") or {}
        code = error.get("code")
        if response.status_code >= 400 or code not in (None, 0, "ok"):
            message = error.get("message") or f"HTTP {response.status_code}"
            raise RuntimeError(f"TikTok API: {message}")
        return data

    def fetch_user(self) -> dict[str, Any]:
        try:
            data = self._request("GET", "/user/info/", fields=USER_FIELDS)
            user = (data.get("data") or {}).get("user") or {}
            return user if isinstance(user, dict) else {}
        except Exception:
            return {}

    def query_video(self, video_id: str) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/video/query/",
            fields=VIDEO_FIELDS,
            payload={"filters": {"video_ids": [video_id]}},
        )
        videos = (data.get("data") or {}).get("videos") or []
        if not videos:
            raise RuntimeError("TikTok API não retornou o vídeo solicitado")
        return dict(videos[0])

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        wanted = max(1, min(limit, 100))
        videos: list[dict[str, Any]] = []
        cursor: int | None = None
        while len(videos) < wanted:
            payload: dict[str, Any] = {"max_count": min(20, wanted - len(videos))}
            if cursor is not None:
                payload["cursor"] = cursor
            data = self._request("POST", "/video/list/", fields=VIDEO_FIELDS, payload=payload)
            page = data.get("data") or {}
            videos.extend(dict(row) for row in page.get("videos") or [] if isinstance(row, dict))
            if not page.get("has_more"):
                break
            next_cursor = page.get("cursor")
            if not isinstance(next_cursor, int) or next_cursor == cursor:
                break
            cursor = next_cursor
        return videos[:wanted]

    @staticmethod
    def _published(value: Any) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(value), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None

    @classmethod
    def _history_row(cls, video: dict[str, Any]) -> dict[str, Any]:
        return {
            "post_id": str(video.get("id") or "") or None,
            "post_url": video.get("share_url"),
            "title": video.get("title") or video.get("video_description"),
            "published_at": cls._published(video.get("create_time")),
            "views": video.get("view_count"),
            "likes": video.get("like_count"),
            "comments": video.get("comment_count"),
            "shares": video.get("share_count"),
            "duration_seconds": video.get("duration"),
            "media_type": "VIDEO",
            "media_product_type": "TIKTOK",
        }

    def collect(
        self, *, video_id: str, include_history: bool = False, history_limit: int = 20
    ) -> dict[str, Any]:
        if not self.configured:
            return {"source_ok": False, "error": "Token do TikTok não configurado.", "source_notes": []}
        if not video_id.strip():
            return {
                "source_ok": False,
                "error": "Informe o ID do vídeo TikTok para coleta autorizada.",
                "source_notes": [],
            }
        try:
            video = self.query_video(video_id.strip())
            account = self.fetch_user()
            history = (
                [self._history_row(row) for row in self.list_recent(history_limit)] if include_history else []
            )
            return {
                "source_ok": True,
                "collection_source": "tiktok-display-api-authorized",
                "post_id": str(video.get("id") or video_id),
                "webpage_url": video.get("share_url"),
                "caption": video.get("video_description") or video.get("title"),
                "uploader": account.get("username") or account.get("display_name"),
                "published_at": self._published(video.get("create_time")),
                "followers": account.get("follower_count"),
                "views": video.get("view_count"),
                "likes": video.get("like_count"),
                "comments_count": video.get("comment_count"),
                "shares": video.get("share_count"),
                "duration_seconds": video.get("duration"),
                "account": account,
                "media": video,
                "profile_history": history,
                "source_notes": [
                    "Dados obtidos da TikTok Display API com autorização do criador.",
                    "A Display API fornece contagens públicas agregadas, mas não fornece retenção profunda, watch time ou pesos de ranking.",
                ],
            }
        except Exception as exc:
            return {
                "source_ok": False,
                "error": self._safe_error(exc),
                "source_notes": [
                    "Confirme o token, o escopo video.list e se o vídeo pertence ao usuário autenticado."
                ],
            }
