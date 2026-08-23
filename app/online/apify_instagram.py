"""Resilient public Instagram collection through an optional Apify actor.

The official Instagram API exposes complete Insights only for authorized professional
accounts. This adapter is the public-post fallback for links belonging to other public
accounts. It collects only data returned by the configured Apify actor and never turns
missing fields into zero.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != -1), None)


def _as_datetime(value: Any) -> datetime | None:
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


def _author(comment: dict[str, Any]) -> tuple[str | None, str | None]:
    owner = comment.get("owner") or comment.get("from") or {}
    if isinstance(owner, dict):
        return owner.get("username"), str(owner.get("id") or "") or None
    return comment.get("author") or comment.get("username"), None


def _normalize_comment(comment: dict[str, Any]) -> dict[str, Any] | None:
    text = comment.get("text") or comment.get("comment")
    if not text:
        return None
    username, author_id = _author(comment)
    return {
        "id": str(comment.get("id") or "") or None,
        "author": username,
        "author_id": author_id,
        "text": str(text),
        "likes": _first_present(comment.get("likesCount"), comment.get("likeCount"), comment.get("likes")),
        "timestamp": _as_datetime(
            _first_present(comment.get("timestamp"), comment.get("created_at"), comment.get("createdAt"))
        ),
        "replies_count": _first_present(comment.get("repliesCount"), comment.get("childCommentCount")),
    }


def _normalize_history_row(post: dict[str, Any]) -> dict[str, Any]:
    """Keep only public fields needed for a creator-relative baseline."""

    return {
        "post_id": str(_first_present(post.get("id"), post.get("shortCode")) or "") or None,
        "url": _first_present(post.get("url"), post.get("inputUrl")),
        "caption": post.get("caption"),
        "views": _first_present(
            post.get("videoPlayCount"),
            post.get("videoViewCount"),
            post.get("playCount"),
            post.get("viewCount"),
            post.get("viewsCount"),
        ),
        "likes": _first_present(post.get("likesCount"), post.get("likeCount")),
        "comments": _first_present(post.get("commentsCount"), post.get("commentCount")),
        "shares": _first_present(post.get("sharesCount"), post.get("shareCount"), post.get("reshareCount")),
        "reposts": _first_present(post.get("repostsCount"), post.get("repostCount")),
        "timestamp": _first_present(post.get("timestamp"), post.get("takenAt"), post.get("createdAt")),
        "type": _first_present(post.get("type"), post.get("mediaType")),
        "media_product_type": _first_present(post.get("productType"), post.get("mediaProductType")),
        "videoUrl": post.get("videoUrl"),
        "displayUrl": post.get("displayUrl"),
        "videoDuration": _first_present(post.get("videoDuration"), post.get("duration")),
    }


class ApifyInstagramCollector:
    """Read public post metrics, comments and recent creator posts using Apify."""

    def __init__(
        self,
        api_token: str,
        actor_id: str = "apify~instagram-scraper",
        max_comments: int = 50,
        timeout: int = 180,
        session: requests.Session | None = None,
    ):
        self.api_token = api_token.strip()
        self.actor_id = actor_id.strip().replace("/", "~") or "apify~instagram-scraper"
        self.max_comments = max(0, min(int(max_comments), 200))
        self.timeout = max(30, int(timeout))
        self.session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.api_token)

    @staticmethod
    def validate_url(url: str) -> str:
        parsed = urlparse(url.strip())
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not (
            host == "instagram.com" or host.endswith(".instagram.com")
        ):
            raise ValueError("O link precisa ser uma publicação pública do Instagram.")
        if not any(segment in parsed.path for segment in ("/p/", "/reel/", "/tv/", "/share/")):
            raise ValueError("Informe o link direto de um post, Reel ou vídeo do Instagram.")
        return url.strip()

    @staticmethod
    def _profile_url(username: str) -> str:
        clean = username.strip().lstrip("@").split("?", 1)[0].strip("/")
        if not clean or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._" for character in clean):
            raise ValueError("Username público inválido para coleta do histórico.")
        return f"https://www.instagram.com/{clean}/"

    def _safe_error(self, exc: Exception) -> str:
        detail = str(exc)
        if self.api_token:
            detail = detail.replace(self.api_token, "[TOKEN_OCULTO]")
        return f"{type(exc).__name__}: {detail[:400]}"

    def _run(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        endpoint = f"https://api.apify.com/v2/acts/{self.actor_id}/run-sync-get-dataset-items"
        response = self.session.post(
            endpoint,
            params={
                "token": self.api_token,
                "timeout": self.timeout,
                "memory": 1024,
                "clean": "true",
            },
            json=payload,
            timeout=self.timeout + 30,
        )
        if response.status_code >= 400:
            message = response.text[:500]
            raise RuntimeError(f"Apify HTTP {response.status_code}: {message}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("A Apify retornou uma resposta que não era JSON.") from exc
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        if not isinstance(data, list):
            raise RuntimeError("Formato inesperado no dataset retornado pela Apify.")
        return [row for row in data if isinstance(row, dict)]

    def _fetch_post(self, url: str) -> dict[str, Any]:
        rows = self._run(
            {
                "directUrls": [url],
                "resultsType": "posts",
                "resultsLimit": 1,
                "addParentData": True,
                "searchLimit": 1,
            }
        )
        if not rows:
            raise RuntimeError("Nenhum dado público foi retornado para esta publicação.")
        canonical = url.rstrip("/")
        return next(
            (
                row
                for row in rows
                if str(row.get("url") or row.get("inputUrl") or "").rstrip("/") == canonical
            ),
            rows[0],
        )

    def _fetch_comments(self, url: str) -> list[dict[str, Any]]:
        if self.max_comments <= 0:
            return []
        rows = self._run(
            {
                "directUrls": [url],
                "resultsType": "comments",
                "resultsLimit": self.max_comments,
                "isNewestComments": False,
                "includeNestedComments": True,
            }
        )
        comments: list[dict[str, Any]] = []
        for row in rows:
            normalized = _normalize_comment(row)
            if normalized:
                comments.append(normalized)
        return comments[: self.max_comments]

    def collect_creator_history(self, username: str, limit: int = 30) -> dict[str, Any]:
        """Collect recent public posts for a creator-relative breakout baseline."""

        if not self.configured:
            return {
                "source_ok": False,
                "error": "APIFY_API_TOKEN não configurado.",
                "posts": [],
            }
        try:
            profile_url = self._profile_url(username)
            bounded_limit = max(5, min(int(limit), 100))
            rows = self._run(
                {
                    "directUrls": [profile_url],
                    "resultsType": "posts",
                    "resultsLimit": bounded_limit,
                    "searchLimit": 1,
                }
            )
            posts = [_normalize_history_row(row) for row in rows[:bounded_limit]]
            return {
                "source_ok": bool(posts),
                "collection_source": "apify/instagram-public-profile",
                "username": username.strip().lstrip("@"),
                "posts": posts,
                "count": len(posts),
                "source_notes": [
                    "Baseline montado com publicações públicas recentes do mesmo criador.",
                    "O número atual de seguidores não representa necessariamente o tamanho da conta na data de cada post."
                ],
            }
        except Exception as exc:
            return {
                "source_ok": False,
                "error": self._safe_error(exc),
                "posts": [],
            }

    def collect(self, url: str, include_comments: bool = True) -> dict[str, Any]:
        if not self.configured:
            return {
                "source_ok": False,
                "error": "APIFY_API_TOKEN não configurado.",
                "source_notes": [],
            }
        try:
            checked_url = self.validate_url(url)
            post = self._fetch_post(checked_url)
            comments: list[dict[str, Any]] = []
            comment_error = ""
            if include_comments:
                try:
                    comments = self._fetch_comments(checked_url)
                except Exception as exc:
                    comment_error = self._safe_error(exc)

            if not comments:
                embedded = post.get("latestComments") or post.get("topComments") or []
                for row in embedded:
                    if isinstance(row, dict):
                        normalized = _normalize_comment(row)
                        if normalized:
                            comments.append(normalized)

            owner = post.get("owner") if isinstance(post.get("owner"), dict) else {}
            account = {
                "username": _first_present(post.get("ownerUsername"), owner.get("username")),
                "name": _first_present(post.get("ownerFullName"), owner.get("fullName"), owner.get("name")),
                "id": str(_first_present(post.get("ownerId"), owner.get("id")) or "") or None,
                "followers_count": _first_present(
                    post.get("ownerFollowersCount"),
                    post.get("ownerFollowerCount"),
                    owner.get("followersCount"),
                ),
                "is_verified": _first_present(post.get("isOwnerVerified"), owner.get("isVerified")),
            }
            account = {key: value for key, value in account.items() if value is not None}

            shares = _first_present(post.get("sharesCount"), post.get("shareCount"), post.get("reshareCount"))
            reposts = _first_present(post.get("repostsCount"), post.get("repostCount"))
            source_notes = [
                "Dados públicos coletados por uma API de scraping configurada; são uma fotografia parcial e podem mudar.",
                "Curtidas, comentários e visualizações são usados somente quando o Instagram os expôs publicamente.",
                "Salvamentos, alcance de não seguidores, envios privados e conversão exigem Insights do proprietário.",
            ]
            if comment_error:
                source_notes.append(f"A coleta ampliada de comentários falhou: {comment_error}")

            return {
                "source_ok": True,
                "collection_source": "apify/instagram-public",
                "platform": "Instagram",
                "post_id": str(_first_present(post.get("id"), post.get("shortCode")) or "") or None,
                "title": None,
                "caption": post.get("caption"),
                "uploader": account.get("username"),
                "followers": account.get("followers_count"),
                "views": _first_present(
                    post.get("videoPlayCount"),
                    post.get("videoViewCount"),
                    post.get("playCount"),
                    post.get("viewCount"),
                    post.get("viewsCount"),
                ),
                "likes": _first_present(post.get("likesCount"), post.get("likeCount")),
                "comments_count": _first_present(post.get("commentsCount"), post.get("commentCount")),
                "shares": shares,
                "reposts": reposts,
                "duration_seconds": _first_present(post.get("videoDuration"), post.get("duration")),
                "published_at": _as_datetime(
                    _first_present(post.get("timestamp"), post.get("takenAt"), post.get("createdAt"))
                ),
                "hashtags": post.get("hashtags") or [],
                "mentions": post.get("mentions") or [],
                "webpage_url": _first_present(post.get("url"), post.get("inputUrl"), checked_url),
                "comments_sample": comments,
                "account": account,
                "public_raw": post,
                "source_notes": source_notes,
            }
        except Exception as exc:
            return {
                "source_ok": False,
                "error": self._safe_error(exc),
                "webpage_url": url,
                "source_notes": [
                    "A fonte pública autenticada não conseguiu ler esta publicação. Confirme se o link é público e válido."
                ],
            }
