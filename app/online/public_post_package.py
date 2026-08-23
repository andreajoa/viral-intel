"""Link-only collection for public social posts.

A public URL is turned into the richest evidence package the environment can legally
observe: public metadata, comments, creator history and downloadable media. Missing
private Insights remain missing.
"""

from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from app.config import Settings, get_settings
from app.online.apify_instagram import ApifyInstagramCollector
from app.online.ytdlp_collector import YTDLPCollector

logger = logging.getLogger(__name__)

_CONTENT_TYPE_EXTENSIONS = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".jpg", ".jpeg", ".png", ".webp"}


def _is_instagram(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "instagram.com" or host.endswith(".instagram.com")


def _safe_stem(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return clean[:90] or "public_media"


def _extension(url: str, content_type: str, fallback: str = ".bin") -> str:
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if normalized_type in _CONTENT_TYPE_EXTENSIONS:
        return _CONTENT_TYPE_EXTENSIONS[normalized_type]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in _ALLOWED_EXTENSIONS:
        return suffix
    guessed = mimetypes.guess_extension(normalized_type) if normalized_type else None
    return guessed if guessed in _ALLOWED_EXTENSIONS else fallback


def _media_candidates(raw: dict[str, Any]) -> list[str]:
    """Return one best media URL per public item/slide, preserving order."""

    candidates: list[str] = []

    def add_best(item: dict[str, Any]) -> None:
        video = item.get("videoUrl") or item.get("video_url") or item.get("video")
        image = (
            item.get("displayUrl") or item.get("display_url") or item.get("imageUrl") or item.get("image_url")
        )
        chosen = video or image
        if isinstance(chosen, str) and chosen.startswith(("http://", "https://")):
            candidates.append(chosen)
            return
        images = item.get("images") or item.get("displayResources") or []
        if isinstance(images, list):
            for value in reversed(images):
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    candidates.append(value)
                    return
                if isinstance(value, dict):
                    src = value.get("src") or value.get("url")
                    if isinstance(src, str) and src.startswith(("http://", "https://")):
                        candidates.append(src)
                        return

    children = raw.get("childPosts") or raw.get("sidecarChildren") or raw.get("children") or []
    if isinstance(children, list) and children:
        for child in children:
            if isinstance(child, dict):
                add_best(child)
    else:
        add_best(raw)

    return list(dict.fromkeys(candidates))


class PublicPostPackageCollector:
    """Collect everything observable from a public post using a single URL."""

    def __init__(
        self,
        settings: Settings | None = None,
        session: requests.Session | None = None,
    ):
        self.settings = settings or get_settings()
        self.session = session or requests.Session()

    def _download_direct(self, metadata: dict[str, Any], destination: Path) -> list[Path]:
        raw = metadata.get("public_raw")
        if not isinstance(raw, dict):
            return []
        urls = _media_candidates(raw)
        if not urls:
            return []

        destination.mkdir(parents=True, exist_ok=True)
        max_bytes = int(getattr(self.settings, "max_public_media_mb", 200)) * 1024 * 1024
        max_items = 12
        downloaded: list[Path] = []
        base_name = _safe_stem(str(metadata.get("post_id") or "public_post"))

        for index, media_url in enumerate(urls[:max_items], start=1):
            try:
                response = self.session.get(
                    media_url,
                    timeout=min(self.settings.command_timeout_seconds, 90),
                    stream=True,
                    headers={"User-Agent": "Mozilla/5.0 ViralIntel/5.2"},
                )
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise RuntimeError("mídia pública excede o limite configurado")
                extension = _extension(media_url, response.headers.get("Content-Type", ""), ".bin")
                if extension not in _ALLOWED_EXTENSIONS:
                    raise RuntimeError("tipo de mídia pública não suportado")
                path = destination / f"{base_name}_{index:02d}{extension}"
                written = 0
                with path.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 512):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > max_bytes:
                            raise RuntimeError("mídia pública excede o limite durante o download")
                        handle.write(chunk)
                if path.stat().st_size:
                    downloaded.append(path)
                else:
                    path.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Direct public-media download failed: %s", exc)
        return downloaded

    def _download_ytdlp(self, url: str, destination: Path) -> list[Path]:
        try:
            import yt_dlp
        except ImportError:
            return []

        destination.mkdir(parents=True, exist_ok=True)
        before = {path.resolve() for path in destination.glob("*") if path.is_file()}
        outtmpl = str(destination / "%(id)s_%(playlist_index|0)02d.%(ext)s")
        options: dict[str, Any] = {
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "format": "best[ext=mp4]/best",
            "noplaylist": False,
            "restrictfilenames": True,
        }
        if self.settings.cookies_file and Path(self.settings.cookies_file).expanduser().is_file():
            options["cookiefile"] = str(Path(self.settings.cookies_file).expanduser())
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([url])
        except Exception as exc:
            logger.warning("yt-dlp public-media download failed for %s: %s", url, exc)
            return []

        files = [
            path.resolve()
            for path in destination.glob("*")
            if path.is_file() and path.resolve() not in before and path.suffix.lower() in _ALLOWED_EXTENSIONS
        ]
        return sorted(files)

    def collect(self, url: str, destination: str | Path) -> dict[str, Any]:
        """Return metadata plus media paths and creator history, all best effort."""

        checked_url = YTDLPCollector.validate_url(url)
        collector = YTDLPCollector(settings=self.settings, max_comments=self.settings.max_public_comments)
        metadata = collector.fetch_metadata(checked_url)
        metadata.setdefault("webpage_url", checked_url)
        metadata.setdefault("source_notes", [])

        media_paths: list[Path] = []
        if getattr(self.settings, "auto_download_public_media", True):
            media_paths = self._download_direct(metadata, Path(destination))
            if not media_paths:
                media_paths = self._download_ytdlp(checked_url, Path(destination))

        creator_history: dict[str, Any] = {"source_ok": False, "posts": [], "count": 0}
        account = metadata.get("account") if isinstance(metadata.get("account"), dict) else {}
        username = str(account.get("username") or metadata.get("uploader") or "").strip().lstrip("@")
        if _is_instagram(checked_url) and username and self.settings.apify_api_token:
            apify = ApifyInstagramCollector(
                api_token=self.settings.apify_api_token,
                actor_id=self.settings.apify_instagram_actor,
                max_comments=self.settings.max_public_comments,
                timeout=self.settings.command_timeout_seconds,
            )
            creator_history = apify.collect_creator_history(
                username,
                limit=getattr(self.settings, "public_creator_history_limit", 30),
            )

        metadata["downloaded_media_paths"] = [str(path) for path in media_paths]
        metadata["creator_history"] = creator_history.get("posts") or []
        metadata["creator_history_meta"] = {
            key: value
            for key, value in creator_history.items()
            if key not in {"posts"} and value not in (None, "", [], {})
        }
        metadata["auto_collection"] = {
            "link_only": True,
            "metadata": bool(metadata.get("source_ok")),
            "media_downloaded": bool(media_paths),
            "media_files": len(media_paths),
            "comments": len(metadata.get("comments_sample") or []),
            "creator_history": len(metadata.get("creator_history") or []),
            "collection_source": metadata.get("collection_source"),
            "apify_configured": bool(self.settings.apify_api_token),
        }
        if not media_paths:
            metadata["source_notes"].append(
                "A mídia não pôde ser baixada automaticamente nesta execução; a análise continuará com metadados públicos disponíveis."
            )
        if not metadata.get("creator_history"):
            metadata["source_notes"].append(
                "O histórico público do criador não foi coletado; o breakout relativo pode ficar inconclusivo."
            )
        return metadata
