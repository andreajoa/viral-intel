"""Evidence-first orchestration for content, audience and distribution analysis."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ai.reliable_media_observer import observe_media
from app.ai.reliable_strategist import ReliableAIStrategist
from app.analysis.comment_intelligence import analyze_comments, normalize_comments
from app.analysis.distribution import build_distribution_diagnosis
from app.analysis.evidence import build_evidence
from app.analysis.io import merge_metric_sources
from app.analysis.metrics import assess_data_quality, derive_metrics
from app.analysis.profile import build_benchmark, summarize_profile
from app.config import Settings, get_settings
from app.media.inspector import MediaInspector, media_kind
from app.models import AnalysisEnvelope, ContentFormat, Platform, PostMetrics
from app.online.instagram_graph import InstagramGraphCollector
from app.online.ytdlp_collector import YTDLPCollector
from app.reporting.exporter import save_report

AIStrategist = ReliableAIStrategist

PLATFORM_ALIASES = {
    "instagram": Platform.INSTAGRAM,
    "instagramstories": Platform.INSTAGRAM,
    "tiktok": Platform.TIKTOK,
    "youtube": Platform.YOUTUBE,
    "youtubewebpage": Platform.YOUTUBE,
    "threads": Platform.THREADS,
}


def _platform(value: Platform | str | None, public: dict[str, Any]) -> Platform:
    if isinstance(value, Platform):
        return value
    normalized = re.sub(r"[^a-z]", "", str(value or public.get("platform") or "").lower())
    return PLATFORM_ALIASES.get(normalized, Platform.OTHER)


def _format_from_collected(public: dict[str, Any]) -> ContentFormat | None:
    media = public.get("media") or {}
    product = str(media.get("media_product_type") or "").upper()
    media_type = str(media.get("media_type") or "").upper()
    if product == "REELS":
        return ContentFormat.REEL
    if media_type == "CAROUSEL_ALBUM":
        return ContentFormat.CAROUSEL
    if media_type == "IMAGE":
        return ContentFormat.IMAGE
    if media_type == "VIDEO":
        return ContentFormat.REEL
    return None


def _format(
    value: ContentFormat | str | None,
    platform: Platform,
    media_paths: list[Path],
    collected: dict[str, Any] | None = None,
) -> ContentFormat:
    if isinstance(value, ContentFormat) and value != ContentFormat.UNKNOWN:
        return value
    if value:
        try:
            parsed = ContentFormat(str(value).lower())
            if parsed != ContentFormat.UNKNOWN:
                return parsed
        except ValueError:
            pass
    collected_format = _format_from_collected(collected or {})
    if collected_format:
        return collected_format
    kind = media_kind(media_paths)
    if kind == "carousel":
        return ContentFormat.CAROUSEL
    if kind == "image":
        return ContentFormat.IMAGE
    if kind == "video":
        if platform == Platform.INSTAGRAM:
            return ContentFormat.REEL
        if platform == Platform.YOUTUBE:
            return ContentFormat.SHORT
        return ContentFormat.VIDEO
    return ContentFormat.UNKNOWN


def _collect_public(url: str, settings: Settings) -> dict[str, Any]:
    clean_url = url.strip()
    if not clean_url:
        return {}
    if not settings.enable_public_collection:
        return {
            "source_ok": False,
            "error": "A coleta pública está desativada neste ambiente.",
        }
    try:
        result = YTDLPCollector(settings=settings).fetch_metadata(clean_url)
        return (
            result
            if isinstance(result, dict)
            else {"source_ok": False, "error": "Resposta pública inválida."}
        )
    except Exception as exc:
        return {
            "source_ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:220]}",
        }


def _collect_instagram_official(
    *,
    settings: Settings,
    media_id: str,
    url: str,
    access_token: str,
    user_id: str,
    include_history: bool,
) -> dict[str, Any]:
    token = access_token.strip() or settings.instagram_access_token
    ig_user_id = user_id.strip() or settings.instagram_user_id
    if not settings.enable_instagram_graph or not token:
        return {}
    collector = InstagramGraphCollector(
        access_token=token,
        ig_user_id=ig_user_id,
        api_version=settings.instagram_api_version,
        max_comments=settings.max_instagram_comments,
        timeout=settings.command_timeout_seconds,
    )
    return collector.collect(
        media_id=media_id,
        permalink=url,
        include_history=include_history,
        history_limit=settings.instagram_history_limit,
    )


def _history_format(row: dict[str, Any]) -> ContentFormat:
    product = str(row.get("media_product_type") or "").upper()
    media_type = str(row.get("media_type") or "").upper()
    if product == "REELS":
        return ContentFormat.REEL
    if media_type == "CAROUSEL_ALBUM":
        return ContentFormat.CAROUSEL
    if media_type == "IMAGE":
        return ContentFormat.IMAGE
    if media_type == "VIDEO":
        return ContentFormat.REEL
    return ContentFormat.UNKNOWN


def _official_history(rows: list[dict[str, Any]], followers: int | None) -> list[PostMetrics]:
    posts: list[PostMetrics] = []
    for row in rows:
        try:
            posts.append(
                PostMetrics.model_validate(
                    {
                        **row,
                        "platform": Platform.INSTAGRAM,
                        "format": _history_format(row),
                        "followers": followers,
                        "captured_at": datetime.now(UTC),
                        "source": "official_api",
                    }
                )
            )
        except Exception:
            continue
    return posts


def _merge_comments(*groups: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for row in normalize_comments(group):
            key = (str(row.get("id") or ""), row["text"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def _data_access_report(
    official: dict[str, Any],
    public: dict[str, Any],
    comments: list[dict[str, Any]],
    history: list[PostMetrics],
) -> dict[str, Any]:
    official_ok = bool(official.get("source_ok"))
    public_ok = bool(public.get("source_ok"))
    return {
        "level": (
            "official_authorized"
            if official_ok
            else "public_partial"
            if public_ok
            else "upload_and_manual_only"
        ),
        "official_private_insights": official_ok,
        "account_metadata": bool(official.get("account")),
        "comment_texts": bool(comments),
        "commenter_usernames": any(row.get("author") for row in comments),
        "profile_history": bool(history),
        "individual_liker_identities": False,
        "individual_sharer_identities": False,
        "individual_saver_identities": False,
        "ranking_model_weights": False,
        "note": (
            "A API oficial pode fornecer métricas agregadas e comentários de mídia pertencente à conta "
            "profissional autenticada. Ela não fornece a lista de pessoas que curtiram, salvaram ou compartilharam."
        ),
    }


def validate_match(online_data: dict[str, Any], local_meta: dict[str, Any], kind: str) -> tuple[bool, str]:
    """Compatibility helper; duration is a clue, never proof of identity."""
    if kind == "video":
        online_duration = online_data.get("duration_seconds") or online_data.get("duration")
        local_duration = local_meta.get("duration_seconds") or local_meta.get("duration")
        if online_duration is not None and local_duration is not None:
            difference = abs(float(online_duration) - float(local_duration))
            if difference <= 1:
                return True, "Durações compatíveis; confirme visualmente que é o mesmo conteúdo."
            return (
                False,
                f"Durações divergentes em {difference:.1f}s; confirme o arquivo antes de interpretar o resultado.",
            )
    return False, "Não há evidência suficiente para confirmar automaticamente a identidade da mídia."


def analyze_content(
    *,
    media_paths: list[str | Path] | None = None,
    platform: Platform | str | None = None,
    content_format: ContentFormat | str | None = None,
    manual_metrics: dict[str, Any] | PostMetrics | None = None,
    profile_history: list[PostMetrics] | None = None,
    url: str = "",
    niche: str = "",
    use_ai: bool = True,
    settings: Settings | None = None,
    inspector: MediaInspector | None = None,
    instagram_media_id: str = "",
    instagram_access_token: str = "",
    instagram_user_id: str = "",
    include_instagram_history: bool = False,
    manual_comments: list[dict[str, Any]] | None = None,
    distribution_context: dict[str, Any] | None = None,
) -> AnalysisEnvelope:
    settings = settings or get_settings()
    report_id = "vi_" + uuid.uuid4().hex[:12]
    job_dir = settings.temp_dir / report_id
    job_dir.mkdir(parents=True, exist_ok=True)

    requested_platform = _platform(platform, {})
    official: dict[str, Any] = {}
    if requested_platform == Platform.INSTAGRAM or instagram_media_id or instagram_access_token:
        official = _collect_instagram_official(
            settings=settings,
            media_id=instagram_media_id,
            url=url,
            access_token=instagram_access_token,
            user_id=instagram_user_id,
            include_history=include_instagram_history,
        )
    public = {} if official.get("source_ok") else _collect_public(url, settings)
    collected = official if official.get("source_ok") else public

    paths = [Path(path).expanduser().resolve() for path in (media_paths or [])]
    detected_platform = _platform(platform, collected)
    detected_format = _format(content_format, detected_platform, paths, collected)

    inspection: dict[str, Any] = {
        "kind": "none",
        "technical": {},
        "frames": [],
        "transcription": "",
        "transcription_segments": [],
        "warnings": [],
    }
    if paths:
        inspection = (inspector or MediaInspector(settings=settings)).inspect(paths, job_dir / "media")
        if detected_format == ContentFormat.CAROUSEL and inspection.get("kind") == "image":
            inspection.setdefault("warnings", []).append(
                "Somente uma captura/capa do carrossel foi inspecionada; envie todos os slides "
                "para avaliar progressão, entrega da promessa e fechamento."
            )
        if (
            detected_format in {ContentFormat.REEL, ContentFormat.SHORT, ContentFormat.VIDEO}
            and inspection.get("kind") == "image"
        ):
            inspection.setdefault("warnings", []).append(
                "Foi enviada uma captura estática de um vídeo. A análise criativa é parcial: "
                "ritmo, cortes, áudio e retenção temporal não puderam ser medidos."
            )

    observation_errors: list[str] = []
    observation_model = ""
    media_observation = None
    try:
        media_observation, observation_errors, observation_model = observe_media(
            settings=settings,
            images=inspection.get("frames") or [],
            technical=inspection.get("technical") or {},
            transcription=inspection.get("transcription") or "",
        )
    except Exception as exc:
        observation_errors = [f"observação multimodal: {type(exc).__name__}: {str(exc)[:240]}"]

    if (
        media_observation
        and media_observation.format_confidence >= 85
        and media_observation.format_hint in {item.value for item in ContentFormat}
        and media_observation.format_hint != "unknown"
    ):
        detected_format = ContentFormat(media_observation.format_hint)

    if isinstance(manual_metrics, PostMetrics):
        manual_data: dict[str, Any] | PostMetrics = manual_metrics
    else:
        manual_data = dict(manual_metrics or {})
        if inspection["technical"].get("duration_seconds") is not None:
            manual_data.setdefault("duration_seconds", inspection["technical"]["duration_seconds"])

    if isinstance(manual_data, dict) and media_observation:
        extracted = media_observation.metrics_for_prefill()
        metric_fields = {
            "followers",
            "views",
            "likes",
            "comments",
            "shares",
            "saves",
            "reposts",
        }
        user_supplied = any(manual_data.get(field) is not None for field in metric_fields)
        added: list[str] = []
        for field, value in extracted.items():
            if field in metric_fields and manual_data.get(field) is None:
                manual_data[field] = value
                added.append(field)
        if added:
            manual_data["source"] = "mixed" if user_supplied else "screenshot"
            notes = list(manual_data.get("source_notes") or [])
            notes.append(
                "Métricas lidas da captura enviada: "
                + ", ".join(added)
                + ". Confirme nos Insights do proprietário."
            )
            manual_data["source_notes"] = notes

    metrics = merge_metric_sources(
        detected_platform,
        detected_format,
        manual_data,
        collected if collected.get("source_ok") else {},
    )
    if url and not metrics.post_url:
        metrics.post_url = url
    if official.get("error"):
        metrics.source_notes.append(f"API oficial do Instagram indisponível: {official['error']}")
    if public.get("error"):
        metrics.source_notes.append(f"Coleta pública indisponível: {public['error']}")
    metrics.source_notes.extend(inspection.get("warnings") or [])

    official_history = _official_history(official.get("profile_history") or [], metrics.followers)
    history = list(profile_history or [])
    if include_instagram_history and official_history:
        known_ids = {post.post_id for post in history if post.post_id}
        history.extend(post for post in official_history if post.post_id not in known_ids)

    comments = _merge_comments(
        manual_comments,
        official.get("comments_sample") if official.get("source_ok") else None,
        public.get("comments_sample") if public.get("source_ok") else None,
    )
    comment_summary = analyze_comments(comments)

    benchmark = build_benchmark(metrics, history)
    derived = derive_metrics(metrics)
    quality = assess_data_quality(metrics, benchmark.comparable_posts)

    technical_context = dict(inspection.get("technical") or {})
    if media_observation:
        technical_context.update(media_observation.evidence_context())
        technical_context["creative_observation_model"] = observation_model
    if collected.get("caption"):
        technical_context["public_caption"] = collected["caption"]
    if public.get("comments_sample"):
        technical_context["public_comments_sample"] = normalize_comments(public["comments_sample"], limit=50)
    if official.get("source_ok"):
        technical_context["official_account"] = official.get("account") or {}
        technical_context["official_media"] = official.get("media") or {}
        technical_context["official_insights_raw"] = official.get("insights_raw") or {}
        technical_context["official_comments_sample"] = comments[:50]
    technical_context["comment_intelligence"] = comment_summary
    technical_context["profile_history_summary"] = summarize_profile(history)
    technical_context["media_warnings"] = inspection.get("warnings") or []
    if distribution_context:
        technical_context.update(
            {key: value for key, value in distribution_context.items() if value not in (None, "", [], {})}
        )
    technical_context["recommendation_eligibility"] = metrics.recommendation_eligibility
    technical_context["original_content"] = metrics.is_original
    technical_context["data_access_report"] = _data_access_report(official, public, comments, history)
    technical_context["distribution_diagnosis"] = build_distribution_diagnosis(
        metrics=metrics,
        derived=derived,
        benchmark=benchmark,
        technical=technical_context,
        comment_summary=comment_summary,
        data_access_level=technical_context["data_access_report"]["level"],
    )
    evidence = build_evidence(metrics, derived, benchmark, quality, technical_context)

    strategist = (
        AIStrategist(settings=settings) if use_ai else AIStrategist(provider="disabled", settings=settings)
    )
    strategy, provider, model, provider_errors = strategist.analyze(
        metrics=metrics,
        benchmark=benchmark,
        quality=quality,
        evidence=evidence,
        technical=technical_context,
        transcription=inspection.get("transcription") or "",
        niche=niche,
        images=inspection.get("frames") or [],
    )
    if use_ai and media_observation and observation_model and provider == "deterministic":
        provider = "hybrid"
        model = f"{observation_model} + {model}"
    provider_errors = observation_errors + provider_errors

    envelope = AnalysisEnvelope(
        report_id=report_id,
        metrics=metrics,
        derived_metrics=derived,
        benchmark=benchmark,
        data_quality=quality,
        evidence=evidence,
        technical_analysis=technical_context,
        transcription=inspection.get("transcription") or "",
        strategy=strategy.model_dump(mode="json"),
        provider=provider,
        model=model,
        provider_errors=provider_errors,
    )
    save_report(envelope, settings.exports_dir)
    return envelope


def run_pipeline(
    url: str,
    local_video_path: str,
    niche: str = "",
    force_mode: str = "auto",
) -> dict[str, Any]:
    """Backward-compatible entry point used by older local scripts."""
    use_media = force_mode in {"auto", "local", "both"}
    use_url = force_mode in {"auto", "link", "both"}
    report = analyze_content(
        media_paths=[local_video_path] if use_media and local_video_path else [],
        url=url if use_url else "",
        niche=niche,
    )
    return report.model_dump(mode="json")
