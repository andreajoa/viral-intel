"""Best-effort public metadata collection with explicit limitations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import Settings, get_settings
from app.online.base import BaseCollector

logger = logging.getLogger(__name__)

SUPPORTED_HOST_SUFFIXES = (
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "threads.net",
    "facebook.com",
)


class _YTDLPLogger:
    """Prevent yt-dlp from printing recoverable extractor failures to stderr."""

    def debug(self, message: str) -> None:
        logger.debug("yt-dlp: %s", message)

    def info(self, message: str) -> None:
        logger.debug("yt-dlp: %s", message)

    def warning(self, message: str) -> None:
        logger.debug("yt-dlp warning: %s", message)

    def error(self, message: str) -> None:
        logger.debug("yt-dlp error: %s", message)


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _published_at(info: dict[str, Any]) -> datetime | None:
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(float(timestamp), tz=UTC)
        except (ValueError, TypeError, OSError):
            pass
    upload_date = info.get("upload_date")
    if upload_date:
        try:
            return datetime.strptime(str(upload_date), "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            pass
    return None


class YTDLPCollector(BaseCollector):
    def __init__(self, settings: Settings | None = None, max_comments: int = 50):
        self.settings = settings or get_settings()
        self.max_comments = max_comments

    @staticmethod
    def validate_url(url: str) -> str:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            raise ValueError("Informe um link público completo iniciado por http:// ou https://")
        if not any(host == suffix or host.endswith("." + suffix) for suffix in SUPPORTED_HOST_SUFFIXES):
            raise ValueError("O link precisa ser do Instagram, TikTok, YouTube, Threads ou Facebook.")
        return url.strip()

    def fetch_metadata(self, url: str) -> dict[str, Any]:
        """Collect only fields publicly returned by yt-dlp.

        Public collection cannot expose private Insights such as saves, true retention,
        non-follower reach, or attributed follows.  Those fields remain missing.
        """

        if not self.settings.enable_public_collection:
            return {"source_ok": False, "error": "Coleta pública desativada", "source_notes": []}
        checked_url = self.validate_url(url)
        try:
            import yt_dlp
        except ImportError:
            return {
                "source_ok": False,
                "error": "yt-dlp não está instalado",
                "source_notes": ["Preencha as métricas manualmente com dados do Insights."],
            }

        options: dict[str, Any] = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "getcomments": True,
            "extract_flat": False,
            "socket_timeout": 30,
            "logger": _YTDLPLogger(),
        }
        if self.settings.cookies_file and Path(self.settings.cookies_file).expanduser().is_file():
            options["cookiefile"] = str(Path(self.settings.cookies_file).expanduser())
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(checked_url, download=False) or {}
            return self._normalize_metadata(info, checked_url)
        except Exception as exc:
            logger.warning("Public metadata collection failed for %s: %s", checked_url, exc)
            return {
                "source_ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "webpage_url": checked_url,
                "source_notes": [
                    "A plataforma bloqueou ou não expôs os dados públicos. Use os números do Insights."
                ],
            }

    def _normalize_metadata(self, info: dict[str, Any], url: str) -> dict[str, Any]:
        raw_comments = info.get("comments") or []
        comments = [
            {
                "author": comment.get("author"),
                "text": comment.get("text"),
                "likes": _first_present(comment.get("like_count"), comment.get("likes")),
            }
            for comment in raw_comments[: self.max_comments]
            if comment.get("text")
        ]
        return {
            "source_ok": True,
            "collection_source": "yt-dlp/public",
            "platform": info.get("extractor_key") or info.get("extractor"),
            "post_id": info.get("id"),
            "title": info.get("title"),
            "caption": info.get("description"),
            "uploader": info.get("uploader") or info.get("channel"),
            "followers": _first_present(
                info.get("channel_follower_count"), info.get("uploader_follower_count")
            ),
            "views": info.get("view_count"),
            "likes": info.get("like_count"),
            "comments_count": info.get("comment_count"),
            "shares": info.get("share_count"),
            "reposts": info.get("repost_count"),
            "duration_seconds": info.get("duration"),
            "published_at": _published_at(info),
            "hashtags": info.get("tags") or [],
            "webpage_url": info.get("webpage_url") or url,
            "comments_sample": comments,
            "source_notes": [
                "Dados públicos são uma fotografia parcial e podem estar atrasados.",
                "Salvamentos, retenção, alcance de não seguidores e seguidores atribuídos exigem Insights do proprietário.",
            ],
        }
