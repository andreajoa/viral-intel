"""Evidence-first orchestration for content, audience and distribution analysis."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.ai.reliable_media_observer import observe_media
from app.ai.verified_strategist import VerifiedAIStrategist
from app.analysis.comment_intelligence import analyze_comments, normalize_comments
from app.analysis.distribution import build_distribution_diagnosis
from app.analysis.evidence import build_evidence
from app.analysis.fingerprint import build_content_fingerprint, rank_content_twins
from app.analysis.io import merge_metric_sources
from app.analysis.metrics import assess_data_quality, derive_metrics
from app.analysis.profile import build_benchmark, lifecycle_bucket, summarize_profile
from app.analysis.semantic_comments import enrich_comment_intelligence
from app.analysis.text_content import analyze_text_content
from app.config import Settings, get_settings
from app.media.inspector import MediaInspector, media_kind
from app.models import AnalysisEnvelope, ContentFormat, Platform, PostMetrics
from app.online.instagram_graph import InstagramGraphCollector
from app.online.tiktok_authorized import TikTokAuthorizedCollector
from app.online.youtube_analytics import YouTubeAnalyticsCollector
from app.online.ytdlp_collector import YTDLPCollector
from app.reporting.exporter import save_report
from app.storage import IntelligenceStore

AIStrategist = VerifiedAIStrategist

PLATFORM_ALIASES = {
    "instagram": Platform.INSTAGRAM,
    "instagramstories": Platform.INSTAGRAM,
    "tiktok": Platform.TIKTOK,
    "youtube": Platform.YOUTUBE,
    "youtubewebpage": Platform.YOUTUBE,
    "threads": Platform.THREADS,
}


def _platform(value: Platform | str | None, collected: dict[str, Any]) -> Platform:
    if isinstance(value, Platform):
        return value
    normalized = re.sub(r"[^a-z]", "", str(value or collected.get("platform") or "").lower())
    return PLATFORM_ALIASES.get(normalized, Platform.OTHER)


def _format_from_collected(collected: dict[str, Any], platform: Platform) -> ContentFormat | None:
    media = collected.get("media") or {}
    product = str(media.get("media_product_type") or "").upper()
    media_type = str(media.get("media_type") or "").upper()
    url = str(collected.get("webpage_url") or "").lower()
    if product == "REELS":
        return ContentFormat.REEL
    if product == "TIKTOK":
        return ContentFormat.VIDEO
    if product == "YOUTUBE":
        return ContentFormat.SHORT if "/shorts/" in url else ContentFormat.VIDEO
    if media_type == "CAROUSEL_ALBUM":
        return ContentFormat.CAROUSEL
    if media_type == "IMAGE":
        return ContentFormat.IMAGE
    if media_type == "VIDEO":
        if platform == Platform.INSTAGRAM:
            return ContentFormat.REEL
        if platform == Platform.YOUTUBE and "/shorts/" in url:
            return ContentFormat.SHORT
        return ContentFormat.VIDEO
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

    collected_format = _format_from_collected(collected or {}, platform)
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
        return {"source_ok": False, "error": "A coleta pública está desativada neste ambiente."}
    try:
        result = YTDLPCollector(settings=settings).fetch_metadata(clean_url)
        return (
            result
            if isinstance(result, dict)
            else {"source_ok": False, "error": "Resposta pública inválida."}
        )
    except Exception as exc:
        return {"source_ok": False, "error": f"{type(exc).__name__}: {str(exc)[:220]}"}


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
        max_retries=settings.instagram_max_retries,
        backoff_seconds=settings.instagram_backoff_seconds,
    )
    return collector.collect(
        media_id=media_id,
        permalink=url,
        include_history=include_history,
        history_limit=settings.instagram_history_limit,
    )


def _tiktok_id_from_url(url: str) -> str:
    match = re.search(r"/video/(\d+)", url)
    return match.group(1) if match else ""


def _youtube_id_from_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0]
    if "/shorts/" in parsed.path:
        return parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
    values = parse_qs(parsed.query).get("v") or []
    return str(values[0]) if values else ""


def _collect_authorized_platform(
    *,
    platform: Platform,
    settings: Settings,
    url: str,
    tiktok_video_id: str,
    tiktok_access_token: str,
    youtube_video_id: str,
    youtube_access_token: str,
    include_history: bool,
) -> dict[str, Any]:
    if platform == Platform.TIKTOK:
        token = tiktok_access_token.strip() or settings.tiktok_access_token
        video_id = tiktok_video_id.strip() or _tiktok_id_from_url(url)
        if not token:
            return {}
        return TikTokAuthorizedCollector(
            token,
            timeout=settings.command_timeout_seconds,
        ).collect(
            video_id=video_id,
            include_history=include_history,
            history_limit=settings.tiktok_history_limit,
        )
    if platform == Platform.YOUTUBE:
        token = youtube_access_token.strip() or settings.youtube_access_token
        video_id = youtube_video_id.strip() or _youtube_id_from_url(url)
        if not token:
            return {}
        return YouTubeAnalyticsCollector(
            token,
            timeout=settings.command_timeout_seconds,
        ).collect(
            video_id=video_id,
            include_history=include_history,
            history_limit=settings.youtube_history_limit,
        )
    return {}


def _history_format(row: dict[str, Any], platform: Platform, target: ContentFormat) -> ContentFormat:
    product = str(row.get("media_product_type") or "").upper()
    media_type = str(row.get("media_type") or "").upper()
    post_url = str(row.get("post_url") or "").lower()
    if product == "REELS":
        return ContentFormat.REEL
    if platform == Platform.TIKTOK:
        return target if target in {ContentFormat.VIDEO, ContentFormat.SHORT} else ContentFormat.VIDEO
    if platform == Platform.YOUTUBE:
        if target == ContentFormat.SHORT or "/shorts/" in post_url:
            return ContentFormat.SHORT
        return ContentFormat.VIDEO
    if media_type == "CAROUSEL_ALBUM":
        return ContentFormat.CAROUSEL
    if media_type == "IMAGE":
        return ContentFormat.IMAGE
    if media_type == "VIDEO":
        return ContentFormat.REEL if platform == Platform.INSTAGRAM else ContentFormat.VIDEO
    return target if target != ContentFormat.UNKNOWN else ContentFormat.UNKNOWN


def _official_history(
    rows: list[dict[str, Any]],
    followers: int | None,
    platform: Platform = Platform.INSTAGRAM,
    target_format: ContentFormat = ContentFormat.UNKNOWN,
) -> list[PostMetrics]:
    posts: list[PostMetrics] = []
    for row in rows:
        try:
            posts.append(
                PostMetrics.model_validate(
                    {
                        **row,
                        "platform": platform,
                        "format": _history_format(row, platform, target_format),
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
        "level": "official_authorized"
        if official_ok
        else "public_partial"
        if public_ok
        else "upload_and_manual_only",
        "official_private_insights": official_ok,
        "official_collection_source": official.get("collection_source") if official_ok else None,
        "account_metadata": bool(official.get("account")),
        "comment_texts": bool(comments),
        "commenter_usernames": any(row.get("author") for row in comments),
        "profile_history": bool(history),
        "individual_liker_identities": False,
        "individual_sharer_identities": False,
        "individual_saver_identities": False,
        "ranking_model_weights": False,
        "note": (
            "APIs oficiais autorizadas podem fornecer métricas agregadas conforme a plataforma e os escopos "
            "concedidos. O Viral Intel nunca transforma campos não expostos em estimativas factuais e não "
            "afirma conhecer pesos privados de ranking."
        ),
    }


def _profile_key(explicit: str, official: dict[str, Any], metrics: PostMetrics) -> str:
    if explicit.strip():
        return explicit.strip()

    account = official.get("account") or {}
    account_id = str(account.get("id") or account.get("open_id") or "").strip()
    username = str(account.get("username") or account.get("display_name") or "").strip().lower()
    if account_id:
        return f"{metrics.platform.value}:id:{account_id}"
    if username:
        return f"{metrics.platform.value}:@{username}"
    return ""


def _post_key(metrics: PostMetrics, report_id: str) -> str:
    if metrics.post_id:
        return str(metrics.post_id)
    if metrics.post_url:
        return metrics.post_url.strip().rstrip("/")
    return report_id


def _stored_history(rows: list[dict[str, Any]], target: PostMetrics) -> list[PostMetrics]:
    """Use one snapshot per historical post, closest to the target lifecycle."""

    chosen: dict[str, tuple[float, PostMetrics]] = {}
    target_age = target.age_hours
    for row in rows:
        try:
            post = PostMetrics.model_validate(row.get("metrics") or {})
        except Exception:
            continue
        if target.post_id and post.post_id == target.post_id:
            continue
        key = post.post_id or str(row.get("post_id") or row.get("report_id") or "")
        if not key:
            continue
        if target_age is None or post.age_hours is None:
            distance = 0.0 if key not in chosen else 1.0
        else:
            distance = abs(post.age_hours - target_age)
            if lifecycle_bucket(post.age_hours) == lifecycle_bucket(target_age):
                distance *= 0.25
        current = chosen.get(key)
        if current is None or distance < current[0]:
            chosen[key] = (distance, post)
    return [item[1] for item in chosen.values()]


def _gate_distribution(diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Never present inconclusive stages as a reconstructed distribution path."""

    stages = diagnosis.get("stages") or []
    supported = [
        stage
        for stage in stages
        if stage.get("status") in {"COMPROVADO", "PLAUSÍVEL", "SINAL_DE_RISCO"}
    ]
    diagnosis["supported_stage_count"] = len(supported)
    diagnosis["has_distribution_evidence"] = bool(supported)
    if supported:
        diagnosis["stages"] = supported
    else:
        diagnosis["stages"] = []
        diagnosis["likely_distribution_path"] = []
        diagnosis["strongest_observed_signals"] = []
        diagnosis["counter_signals_or_risks"] = []
        diagnosis["verdict"] = (
            "A peça pode ser analisada, mas não há métricas suficientes para reconstruir a distribuição. "
            "Ausência de dado não significa baixa entrega."
        )
    return diagnosis


def _twin_summary(twins: list[dict[str, Any]]) -> dict[str, Any]:
    if not twins:
        return {"available": False, "count": 0}
    metrics = [item.get("metrics") or {} for item in twins]
    summary: dict[str, Any] = {
        "available": True,
        "count": len(twins),
        "mean_similarity": round(
            sum(float(item["similarity"]) for item in twins) / len(twins),
            3,
        ),
    }
    for field in ("views", "reach", "shares", "saves", "follows"):
        values = [float(row[field]) for row in metrics if isinstance(row.get(field), (int, float))]
        if values:
            summary[f"median_{field}"] = round(float(median(values)), 4)
    return summary


def validate_match(
    online_data: dict[str, Any],
    local_meta: dict[str, Any],
    kind: str,
) -> tuple[bool, str]:
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
    tiktok_video_id: str = "",
    tiktok_access_token: str = "",
    youtube_video_id: str = "",
    youtube_access_token: str = "",
    include_platform_history: bool = True,
    manual_comments: list[dict[str, Any]] | None = None,
    manual_caption: str = "",
    distribution_context: dict[str, Any] | None = None,
    profile_key: str = "",
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
    elif requested_platform in {Platform.TIKTOK, Platform.YOUTUBE}:
        official = _collect_authorized_platform(
            platform=requested_platform,
            settings=settings,
            url=url,
            tiktok_video_id=tiktok_video_id,
            tiktok_access_token=tiktok_access_token,
            youtube_video_id=youtube_video_id,
            youtube_access_token=youtube_access_token,
            include_history=include_platform_history,
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
                "Somente uma captura/capa do carrossel foi inspecionada; envie todos os slides para avaliar progressão e fechamento."
            )
        if (
            detected_format in {ContentFormat.REEL, ContentFormat.SHORT, ContentFormat.VIDEO}
            and inspection.get("kind") == "image"
        ):
            inspection.setdefault("warnings", []).append(
                "Foi enviada uma captura estática de um vídeo. Ritmo, áudio, cortes e progressão temporal não puderam ser medidos."
            )

    observation_errors: list[str] = []
    observation_model = ""
    media_observation = None
    try:
        native_video_path = paths[0] if paths and inspection.get("kind") == "video" else None
        media_observation, observation_errors, observation_model = observe_media(
            settings=settings,
            images=inspection.get("frames") or [],
            technical=inspection.get("technical") or {},
            transcription=inspection.get("transcription") or "",
            video_path=native_video_path,
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
        metric_fields = {"followers", "views", "likes", "comments", "shares", "saves", "reposts"}
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
        metrics.source_notes.append(f"API oficial autorizada indisponível: {official['error']}")
    if public.get("error"):
        metrics.source_notes.append(f"Coleta pública indisponível: {public['error']}")
    metrics.source_notes.extend(inspection.get("warnings") or [])

    resolved_profile_key = _profile_key(profile_key, official, metrics)
    store: IntelligenceStore | None = None
    stored_rows: list[dict[str, Any]] = []
    persistence_errors: list[str] = []
    if settings.persistence_active and resolved_profile_key:
        try:
            store = IntelligenceStore(settings.intelligence_db)
            stored_rows = store.comparable_reports(
                profile_key=resolved_profile_key,
                platform=metrics.platform.value,
                content_format=metrics.format.value,
                limit=250,
            )
        except Exception as exc:
            persistence_errors.append(
                f"memória longitudinal ({settings.persistence_backend}): {type(exc).__name__}: {str(exc)[:200]}"
            )
            store = None

    official_history = _official_history(
        official.get("profile_history") or [],
        metrics.followers,
        detected_platform,
        detected_format,
    )
    history = list(profile_history or [])
    if official_history:
        known_ids = {post.post_id for post in history if post.post_id}
        history.extend(post for post in official_history if post.post_id not in known_ids)

    if stored_rows:
        known_ids = {post.post_id for post in history if post.post_id}
        for post in _stored_history(stored_rows, metrics):
            if post.post_id and post.post_id in known_ids:
                continue
            history.append(post)
            if post.post_id:
                known_ids.add(post.post_id)

    comments = _merge_comments(
        manual_comments,
        official.get("comments_sample") if official.get("source_ok") else None,
        public.get("comments_sample") if public.get("source_ok") else None,
    )
    comment_summary = enrich_comment_intelligence(analyze_comments(comments), comments, settings)

    benchmark = build_benchmark(metrics, history)
    derived = derive_metrics(metrics)
    quality = assess_data_quality(metrics, benchmark.comparable_posts)

    technical_context = dict(inspection.get("technical") or {})
    technical_context["analysis_engine"] = "viral-intel-5.1"
    technical_context["profile_key_available"] = bool(resolved_profile_key)
    technical_context["persistence_backend"] = settings.persistence_backend

    if media_observation:
        technical_context.update(media_observation.evidence_context())
        technical_context["creative_observation_model"] = observation_model
        technical_context["native_video_observation"] = "+native-video" in observation_model

    caption = manual_caption.strip() or str(collected.get("caption") or "").strip()
    if caption:
        caption_source = "manual_input" if manual_caption.strip() else "authorized_or_public_source"
        technical_context["manual_caption" if manual_caption.strip() else "public_caption"] = caption
        technical_context["caption_source"] = caption_source
        technical_context.update(analyze_text_content(caption))

    if public.get("comments_sample"):
        technical_context["public_comments_sample"] = normalize_comments(public["comments_sample"], limit=50)
    if official.get("source_ok"):
        technical_context["official_account"] = official.get("account") or {}
        technical_context["official_media"] = official.get("media") or {}
        technical_context["official_insights_raw"] = official.get("insights_raw") or {}
        technical_context["official_comments_sample"] = comments[:50]
        technical_context["official_collection_source"] = official.get("collection_source")

    technical_context["comment_intelligence"] = comment_summary
    technical_context["profile_history_summary"] = summarize_profile(history)
    technical_context["media_warnings"] = inspection.get("warnings") or []
    if distribution_context:
        technical_context.update(
            {
                key: value
                for key, value in distribution_context.items()
                if value not in (None, "", [], {})
            }
        )

    technical_context["recommendation_eligibility"] = metrics.recommendation_eligibility
    technical_context["original_content"] = metrics.is_original
    technical_context["data_access_report"] = _data_access_report(official, public, comments, history)
    technical_context["distribution_diagnosis"] = _gate_distribution(
        build_distribution_diagnosis(
            metrics=metrics,
            derived=derived,
            benchmark=benchmark,
            technical=technical_context,
            comment_summary=comment_summary,
            data_access_level=technical_context["data_access_report"]["level"],
        )
    )

    fingerprint = build_content_fingerprint(
        metrics,
        technical_context,
        inspection.get("transcription") or "",
        niche,
    )
    twins = rank_content_twins(
        fingerprint,
        stored_rows,
        limit=settings.content_twin_limit,
        minimum_score=settings.content_twin_min_score,
    )
    technical_context["content_twin_summary"] = _twin_summary(twins)
    if persistence_errors:
        technical_context["persistence_warnings"] = persistence_errors

    evidence = build_evidence(metrics, derived, benchmark, quality, technical_context)
    strategist = (
        AIStrategist(settings=settings)
        if use_ai
        else AIStrategist(provider="disabled", settings=settings)
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
    provider_errors = observation_errors + provider_errors + persistence_errors

    post_key = _post_key(metrics, report_id)
    longitudinal = (
        store.longitudinal_summary(profile_key=resolved_profile_key, post_key=post_key)
        if store and resolved_profile_key
        else {"available": False, "snapshots": 0}
    )

    envelope = AnalysisEnvelope(
        report_id=report_id,
        metrics=metrics,
        derived_metrics=derived,
        benchmark=benchmark,
        data_quality=quality,
        evidence=evidence,
        technical_analysis=technical_context,
        content_fingerprint=fingerprint,
        content_twins=twins,
        longitudinal=longitudinal,
        transcription=inspection.get("transcription") or "",
        strategy=strategy.model_dump(mode="json"),
        provider=provider,
        model=model,
        provider_errors=provider_errors,
    )

    if store and resolved_profile_key:
        try:
            store.save_report(envelope, profile_key=resolved_profile_key, post_key=post_key)
            envelope.longitudinal = store.longitudinal_summary(
                profile_key=resolved_profile_key,
                post_key=post_key,
            )
            store.save_report(envelope, profile_key=resolved_profile_key, post_key=post_key)
        except Exception as exc:
            envelope.provider_errors.append(
                f"persistência final: {type(exc).__name__}: {str(exc)[:200]}"
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
