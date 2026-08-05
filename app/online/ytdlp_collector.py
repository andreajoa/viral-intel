"""Best-effort public metadata collection with explicit limitations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.config import Settings, get_settings
from app.online.apify_instagram import ApifyInstagramCollector
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

    @staticmethod
    def _is_instagram(url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return host == "instagram.com" or host.endswith(".instagram.com")

    def _apify_instagram(self, url: str) -> dict[str, Any]:
        if not self.settings.apify_api_token or not self._is_instagram(url):
            return {}
        collector = ApifyInstagramCollector(
            api_token=self.settings.apify_api_token,
            actor_id=self.settings.apify_instagram_actor,
            max_comments=self.settings.max_public_comments,
            timeout=self.settings.command_timeout_seconds,
        )
        return collector.collect(url, include_comments=True)

    def fetch_metadata(self, url: str) -> dict[str, Any]:
        """Collect public fields through a resilient source chain.

        For Instagram, a configured authenticated public-data provider is attempted
        first because cloud IPs are frequently blocked or rate-limited by Instagram.
        yt-dlp remains the fallback for all supported platforms. Private Insights such
        as saves, true retention, non-follower reach and attributed follows remain
        unavailable for posts not owned by an authorized professional account.
        """

        if not self.settings.enable_public_collection:
            return {"source_ok": False, "error": "Coleta pública desativada", "source_notes": []}
        checked_url = self.validate_url(url)

        provider_result = self._apify_instagram(checked_url)
        provider_error = ""
        if provider_result:
            if provider_result.get("source_ok"):
                return provider_result
            provider_error = str(provider_result.get("error") or "fonte pública autenticada falhou")

        try:
            import yt_dlp
        except ImportError:
            notes = ["Preencha as métricas manualmente com dados do Insights."]
            if provider_error:
                notes.insert(0, f"Fonte pública autenticada indisponível: {provider_error}")
            return {
                "source_ok": False,
                "error": "yt-dlp não está instalado",
                "source_notes": notes,
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
            result = self._normalize_metadata(info, checked_url)
            if provider_error:
                result["source_notes"].append(
                    "A fonte pública autenticada falhou e a coleta foi recuperada pelo yt-dlp: "
                    + provider_error
                )
            return result
        except Exception as exc:
            logger.warning("Public metadata collection failed for %s: %s", checked_url, exc)
            errors = []
            if provider_error:
                errors.append(f"API pública autenticada: {provider_error}")
            errors.append(f"yt-dlp: {type(exc).__name__}: {str(exc)[:300]}")
            return {
                "source_ok": False,
                "error": " | ".join(errors),
                "webpage_url": checked_url,
                "source_notes": [
                    "As fontes automáticas foram bloqueadas ou não expuseram os dados públicos.",
                    "No Instagram Cloud, uma resposta HTTP 429 significa bloqueio/rate limit do IP, não ausência de engajamento.",
                    "Envie uma captura completa para leitura visual ou configure APIFY_API_TOKEN para links públicos.",
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
