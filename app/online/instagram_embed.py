"""Tokenless, best-effort metadata parsing from Instagram's public embed page."""

from __future__ import annotations

import html as html_lib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests

_POST_RE = re.compile(r"/(p|reel|tv)/([^/?#]+)", re.IGNORECASE)
_SCRIPT_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_META_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"']([^\"']+)[\"'][^>]+content=[\"']([^\"']*)[\"'][^>]*>",
    re.IGNORECASE,
)


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != ""), None)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return max(0, int(value))
    if value is None:
        return None
    text = str(value).strip().lower().replace("\u00a0", " ")
    text = text.replace("likes", "").replace("comments", "").replace("views", "").strip()
    match = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)\s*([kmb]|mil|mi|m)?", text)
    if not match:
        digits = re.sub(r"[^0-9]", "", text)
        return int(digits) if digits else None
    number = float(match.group(1).replace(",", "."))
    suffix = match.group(2) or ""
    factor = {
        "k": 1_000,
        "mil": 1_000,
        "m": 1_000_000,
        "mi": 1_000_000,
        "b": 1_000_000_000,
    }.get(suffix, 1)
    return round(number * factor)


def _datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (ValueError, OSError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _find_json_number(text: str, *keys: str) -> int | None:
    for key in keys:
        patterns = (
            rf'"{re.escape(key)}"\s*:\s*(\d+)',
            rf'"{re.escape(key)}"\s*:\s*"(\d+)"',
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
    return None


def _find_json_string(text: str, *keys: str) -> str | None:
    for key in keys:
        match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
        if not match:
            continue
        try:
            return json.loads('"' + match.group(1) + '"')
        except json.JSONDecodeError:
            return html_lib.unescape(match.group(1))
    return None


def _iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _iter_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dicts(item)


def _json_ld_metrics(document: str) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for raw in _SCRIPT_RE.findall(document):
        try:
            payload = json.loads(html_lib.unescape(raw).strip())
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _iter_dicts(payload):
            interaction_type = item.get("interactionType")
            interaction_name = ""
            if isinstance(interaction_type, dict):
                interaction_name = str(interaction_type.get("@type") or "")
            else:
                interaction_name = str(interaction_type or "")
            count = _integer(item.get("userInteractionCount"))
            lowered = interaction_name.lower()
            if count is not None and "like" in lowered:
                output.setdefault("likes", count)
            elif count is not None and "comment" in lowered:
                output.setdefault("comments_count", count)
            elif count is not None and ("watch" in lowered or "view" in lowered):
                output.setdefault("views", count)
            output.setdefault("caption", item.get("caption") or item.get("description"))
            output.setdefault("published_at", _datetime(item.get("uploadDate") or item.get("datePublished")))
            author = item.get("author")
            if isinstance(author, dict):
                output.setdefault("uploader", author.get("alternateName") or author.get("name"))
    return {key: value for key, value in output.items() if value not in (None, "")}


def _meta_tags(document: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for name, value in _META_RE.findall(document):
        tags[name.lower()] = html_lib.unescape(value)
    return tags


def _description_counts(description: str) -> dict[str, int]:
    output: dict[str, int] = {}
    patterns = {
        "likes": r"([0-9]+(?:[.,][0-9]+)?\s*(?:k|m|b|mil|mi)?)\s+likes?",
        "comments_count": r"([0-9]+(?:[.,][0-9]+)?\s*(?:k|m|b|mil|mi)?)\s+comments?",
        "views": r"([0-9]+(?:[.,][0-9]+)?\s*(?:k|m|b|mil|mi)?)\s+views?",
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            value = _integer(match.group(1))
            if value is not None:
                output[field] = value
    return output


class InstagramEmbedCollector:
    """Read only counts and metadata actually exposed by the public embed page."""

    def __init__(
        self,
        timeout: int = 30,
        session: requests.Session | None = None,
    ):
        self.timeout = max(5, int(timeout))
        self.session = session or requests.Session()

    @staticmethod
    def validate_url(url: str) -> tuple[str, str, str]:
        clean = url.strip()
        parsed = urlparse(clean)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not (
            host == "instagram.com" or host.endswith(".instagram.com")
        ):
            raise ValueError("O link precisa ser uma publicação pública do Instagram.")
        match = _POST_RE.search(parsed.path)
        if not match:
            raise ValueError("Informe o link direto de um post, Reel ou vídeo do Instagram.")
        return clean, match.group(1).lower(), match.group(2)

    def _fetch(self, kind: str, shortcode: str) -> tuple[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        errors: list[str] = []
        for suffix in ("embed/captioned/", "embed/"):
            endpoint = f"https://www.instagram.com/{kind}/{shortcode}/{suffix}"
            response = self.session.get(endpoint, headers=headers, timeout=self.timeout)
            if response.status_code < 400 and response.text.strip():
                return response.text, endpoint
            errors.append(f"{response.status_code} em {suffix.rstrip('/')}")
        raise RuntimeError("; ".join(errors) or "Embed público indisponível")

    def collect(self, url: str) -> dict[str, Any]:
        try:
            clean, kind, shortcode = self.validate_url(url)
            document, endpoint = self._fetch(kind, shortcode)
            decoded = html_lib.unescape(document)
            tags = _meta_tags(document)
            description = _first_present(tags.get("og:description"), tags.get("description"), "")
            ld = _json_ld_metrics(document)
            counts = _description_counts(str(description))

            likes = _first_present(
                ld.get("likes"),
                counts.get("likes"),
                _find_json_number(decoded, "like_count", "likes_count"),
            )
            comments_count = _first_present(
                ld.get("comments_count"),
                counts.get("comments_count"),
                _find_json_number(decoded, "comment_count", "comments_count"),
            )
            views = _first_present(
                ld.get("views"),
                counts.get("views"),
                _find_json_number(
                    decoded,
                    "video_view_count",
                    "video_play_count",
                    "play_count",
                    "view_count",
                ),
            )
            caption = _first_present(
                ld.get("caption"),
                tags.get("og:title"),
                _find_json_string(decoded, "caption", "text"),
            )
            uploader = _first_present(
                ld.get("uploader"),
                _find_json_string(decoded, "username", "owner_username"),
            )
            published_at = _first_present(
                ld.get("published_at"),
                _datetime(_find_json_number(decoded, "taken_at_timestamp", "taken_at")),
            )

            has_useful_data = any(
                value is not None for value in (likes, comments_count, views, caption, uploader)
            )
            if not has_useful_data:
                raise RuntimeError("O embed abriu, mas não expôs metadados utilizáveis.")

            return {
                "source_ok": True,
                "collection_source": "instagram/public-embed",
                "platform": "Instagram",
                "post_id": shortcode,
                "caption": caption,
                "uploader": uploader,
                "views": views,
                "likes": likes,
                "comments_count": comments_count,
                "published_at": published_at,
                "webpage_url": clean,
                "comments_sample": [],
                "source_notes": [
                    "Contagens lidas do embed público do Instagram; podem estar abreviadas ou atrasadas.",
                    "O embed não fornece salvamentos, envios privados, alcance de não seguidores nem conversão.",
                    f"Fonte consultada: {endpoint}",
                ],
            }
        except Exception as exc:
            return {
                "source_ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:400]}",
                "webpage_url": url,
                "source_notes": ["O embed público do Instagram não expôs os dados nesta execução."],
            }
