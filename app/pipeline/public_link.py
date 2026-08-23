"""One-click pipeline for reverse engineering public third-party posts."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.ai.schema import StrategicReport
from app.analysis.viral_lab import (
    build_public_creator_baseline,
    build_replication_blueprint,
    build_viral_dna,
    public_history_to_posts,
)
from app.config import Settings, get_settings
from app.media.inspector import MediaInspector
from app.models import AnalysisEnvelope, ContentFormat, Platform
from app.online.public_post_package import PublicPostPackageCollector
from app.pipeline.main import analyze_content
from app.reporting.exporter import save_report


def _platform_from_package(package: dict[str, Any], url: str) -> Platform:
    label = str(package.get("platform") or "").lower()
    host = (urlparse(url).hostname or "").lower()
    if "instagram" in label or host.endswith("instagram.com"):
        return Platform.INSTAGRAM
    if "tiktok" in label or host.endswith("tiktok.com"):
        return Platform.TIKTOK
    if "youtube" in label or host.endswith(("youtube.com", "youtu.be")):
        return Platform.YOUTUBE
    if "threads" in label or host.endswith("threads.net"):
        return Platform.THREADS
    return Platform.OTHER


def _format_from_package(package: dict[str, Any], url: str) -> ContentFormat | None:
    path = urlparse(url).path.lower()
    if "/reel/" in path:
        return ContentFormat.REEL
    if "/shorts/" in path:
        return ContentFormat.SHORT
    raw = package.get("public_raw") if isinstance(package.get("public_raw"), dict) else {}
    product = str(raw.get("productType") or raw.get("mediaProductType") or "").upper()
    media_type = str(raw.get("type") or raw.get("mediaType") or "").upper()
    if "REEL" in product:
        return ContentFormat.REEL
    if media_type in {"SIDECAR", "CAROUSEL", "CAROUSEL_ALBUM"}:
        return ContentFormat.CAROUSEL
    if raw.get("childPosts"):
        return ContentFormat.CAROUSEL
    if media_type in {"VIDEO", "GRAPHVIDEO"} or raw.get("videoUrl"):
        return ContentFormat.VIDEO
    if media_type in {"IMAGE", "PHOTO", "GRAPHIMAGE"} or raw.get("displayUrl"):
        return ContentFormat.IMAGE
    return None


def _manual_public_metrics(package: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "post_id": package.get("post_id"),
            "post_url": package.get("webpage_url"),
            "title": package.get("title") or package.get("caption"),
            "published_at": package.get("published_at"),
            "followers": package.get("followers"),
            "views": package.get("views"),
            "likes": package.get("likes"),
            "comments": package.get("comments_count"),
            "shares": package.get("shares"),
            "reposts": package.get("reposts"),
            "duration_seconds": package.get("duration_seconds"),
            "source": "public",
            "source_notes": list(package.get("source_notes") or []),
        }.items()
        if value not in (None, "")
    }


def _profile_key(package: dict[str, Any], platform: Platform) -> str:
    account = package.get("account") if isinstance(package.get("account"), dict) else {}
    account_id = str(account.get("id") or "").strip()
    username = str(account.get("username") or package.get("uploader") or "").strip().lstrip("@").lower()
    if account_id:
        return f"public:{platform.value}:id:{account_id}"
    if username:
        return f"public:{platform.value}:@{username}"
    return ""


def _collection_quality(package: dict[str, Any]) -> dict[str, Any]:
    auto = dict(package.get("auto_collection") or {})
    signals = {
        "metadata": bool(package.get("source_ok")),
        "media": bool(package.get("downloaded_media_paths")),
        "creator_history": bool(package.get("creator_history")),
        "comments": bool(package.get("comments_sample")),
        "views": package.get("views") is not None,
        "likes": package.get("likes") is not None,
    }
    score = round(sum(signals.values()) / len(signals) * 100)
    auto.update(
        {
            "coverage_score": score,
            "signals": signals,
            "ready_for_creative_reverse_engineering": signals["media"],
            "ready_for_creator_breakout_proof": signals["creator_history"]
            and (signals["views"] or signals["likes"]),
        }
    )
    return auto


def analyze_public_link(
    url: str,
    *,
    niche: str = "",
    settings: Settings | None = None,
    inspector: MediaInspector | None = None,
    use_ai: bool = True,
) -> AnalysisEnvelope:
    """Analyze a public post from only its URL.

    The collector performs best-effort public scraping and media download. Private
    creator Insights are deliberately unavailable and remain missing.
    """

    settings = settings or get_settings()
    clean_url = url.strip()
    if not clean_url:
        raise ValueError("Cole o link público do post que deseja investigar.")

    collection_dir = settings.temp_dir / ("public_link_" + uuid.uuid4().hex[:12])
    package: dict[str, Any] = {}
    report: AnalysisEnvelope | None = None
    try:
        package = PublicPostPackageCollector(settings=settings).collect(clean_url, collection_dir)
        if not package.get("source_ok") and not package.get("downloaded_media_paths"):
            detail = str(package.get("error") or "nenhuma fonte pública retornou dados")
            raise RuntimeError(
                "Não foi possível extrair este post automaticamente. "
                f"Detalhe: {detail[:320]}"
            )

        platform = _platform_from_package(package, clean_url)
        content_format = _format_from_package(package, clean_url)
        history = public_history_to_posts(
            package.get("creator_history") or [],
            platform=platform,
            followers=package.get("followers"),
        )
        public_metrics = _manual_public_metrics(package)
        runtime_settings = replace(settings, enable_public_collection=False)

        report = analyze_content(
            media_paths=package.get("downloaded_media_paths") or [],
            platform=platform,
            content_format=content_format,
            manual_metrics=public_metrics,
            profile_history=history,
            url=clean_url,
            niche=niche,
            use_ai=use_ai,
            settings=runtime_settings,
            inspector=inspector,
            manual_comments=package.get("comments_sample") or [],
            manual_caption=str(package.get("caption") or ""),
            profile_key=_profile_key(package, platform),
        )

        baseline = build_public_creator_baseline(report.metrics, history)
        comments = report.technical_analysis.get("comment_intelligence") or {}
        viral_dna = build_viral_dna(
            metrics=report.metrics,
            technical=report.technical_analysis,
            creator_baseline=baseline,
            comments=comments,
        )
        strategy = StrategicReport.model_validate(report.strategy)
        blueprint = build_replication_blueprint(
            strategy=strategy,
            technical=report.technical_analysis,
            creator_baseline=baseline,
            niche=niche,
        )

        report.technical_analysis["link_only_mode"] = True
        report.technical_analysis["auto_collection"] = _collection_quality(package)
        report.technical_analysis["public_collection_source"] = package.get("collection_source")
        report.technical_analysis["public_account"] = package.get("account") or {
            "username": package.get("uploader")
        }
        report.technical_analysis["public_creator_history_count"] = len(history)
        report.technical_analysis["public_creator_baseline"] = baseline
        report.technical_analysis["viral_dna"] = viral_dna
        report.technical_analysis["replication_blueprint"] = blueprint
        report.technical_analysis["third_party_private_metrics_unavailable"] = [
            "saves",
            "true_reach",
            "retention",
            "non_follower_reach",
            "attributed_follows",
            "ranking_weights",
        ]
        save_report(report, settings.exports_dir)
        return report
    finally:
        shutil.rmtree(collection_dir, ignore_errors=True)
