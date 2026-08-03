"""Evidence-first orchestration for content and profile analysis."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from app.ai.media_observer import observe_media
from app.ai.strategist import AIStrategist
from app.analysis.evidence import build_evidence
from app.analysis.io import merge_metric_sources
from app.analysis.metrics import assess_data_quality, derive_metrics
from app.analysis.profile import build_benchmark, summarize_profile
from app.config import Settings, get_settings
from app.media.inspector import MediaInspector, media_kind
from app.models import AnalysisEnvelope, ContentFormat, Platform, PostMetrics
from app.online.ytdlp_collector import YTDLPCollector
from app.reporting.exporter import save_report

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


def _format(
    value: ContentFormat | str | None,
    platform: Platform,
    media_paths: list[Path],
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
) -> AnalysisEnvelope:
    settings = settings or get_settings()
    report_id = "vi_" + uuid.uuid4().hex[:12]
    job_dir = settings.temp_dir / report_id
    job_dir.mkdir(parents=True, exist_ok=True)

    public: dict[str, Any] = {}
    if url.strip():
        public = YTDLPCollector(settings=settings).fetch_metadata(url.strip())

    paths = [Path(path).expanduser().resolve() for path in (media_paths or [])]
    detected_platform = _platform(platform, public)
    detected_format = _format(content_format, detected_platform, paths)

    inspection = {
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

    media_observation, observation_errors, observation_model = observe_media(
        settings=settings,
        images=inspection.get("frames") or [],
        technical=inspection.get("technical") or {},
        transcription=inspection.get("transcription") or "",
    )

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
        public if public.get("source_ok") else {},
    )
    if url and not metrics.post_url:
        metrics.post_url = url
    if public.get("error"):
        metrics.source_notes.append(f"Coleta pública indisponível: {public['error']}")
    metrics.source_notes.extend(inspection.get("warnings") or [])

    history = profile_history or []
    benchmark = build_benchmark(metrics, history)
    derived = derive_metrics(metrics)
    quality = assess_data_quality(metrics, benchmark.comparable_posts)

    technical_context = dict(inspection.get("technical") or {})
    if media_observation:
        technical_context.update(media_observation.evidence_context())
        technical_context["creative_observation_model"] = observation_model
    if public.get("caption"):
        technical_context["public_caption"] = public["caption"]
    if public.get("comments_sample"):
        technical_context["public_comments_sample"] = public["comments_sample"]
    technical_context["profile_history_summary"] = summarize_profile(history)
    technical_context["media_warnings"] = inspection.get("warnings") or []
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
        # The visual Gemini pass succeeded even if the larger strategic pass needed
        # the evidence-engine fallback. Preserve that work and report the real mode.
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
