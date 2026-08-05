"""Evidence-package workflow for analyses that cannot rely on public links alone.

The production dashboard remains backward compatible, while this module adds three
explicit modes and enriches the pipeline with owner-provided Insight and comment
screenshots. Public-link analysis is deliberately labelled as triage, not complete
forensics.
"""

from __future__ import annotations

from typing import Any

from app.ai.evidence_observer import (
    CommentScreenshotObservation,
    InsightScreenshotObservation,
    ScreenshotAsset,
    observation_json,
    observe_comment_screenshots,
    observe_insight_screenshots,
)
from app.models import PostMetrics

OWNER_MODE = "Meu post — análise profunda"
EXTERNAL_MODE = "Post externo — análise forense"
PUBLIC_MODE = "Link público — triagem limitada"
_MODES = (OWNER_MODE, EXTERNAL_MODE, PUBLIC_MODE)
_INSTALLED = False


def merge_metric_evidence(
    manual_metrics: dict[str, Any] | PostMetrics | None,
    extracted: dict[str, float | int],
) -> dict[str, Any]:
    """Fill missing manual fields with screenshot values without overwriting the owner."""

    if isinstance(manual_metrics, PostMetrics):
        merged = manual_metrics.model_dump(mode="python")
    else:
        merged = dict(manual_metrics or {})

    had_manual_metric = any(
        merged.get(field) is not None
        for field in (
            "views",
            "reach",
            "impressions",
            "likes",
            "comments",
            "shares",
            "saves",
            "reposts",
        )
    )
    added: list[str] = []
    for field, value in extracted.items():
        if merged.get(field) is None:
            merged[field] = value
            added.append(field)

    if added:
        merged["source"] = "mixed" if had_manual_metric else "screenshot"
        notes = list(merged.get("source_notes") or [])
        notes.append(
            "Métricas lidas de capturas do Instagram Insights fornecidas pelo proprietário: "
            + ", ".join(sorted(added))
            + "."
        )
        merged["source_notes"] = notes
    return merged


def merge_comment_evidence(
    existing: list[dict[str, Any]] | None,
    extracted: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in [*(existing or []), *extracted]:
        author = str(row.get("author") or row.get("username") or "").strip()
        text = str(row.get("text") or row.get("comment") or "").strip()
        if not text:
            continue
        key = (author.lower(), text.lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append({**row, "author": author or None, "text": text})
    return merged


def evidence_readiness(
    *,
    mode: str,
    media_count: int,
    has_text: bool,
    metric_count: int,
    comment_count: int,
    history_count: int,
    official_access: bool,
) -> dict[str, Any]:
    """Describe what the current evidence package can actually support."""

    present: list[str] = []
    missing: list[str] = []

    if media_count:
        present.append("mídia ou captura da publicação")
    elif has_text:
        present.append("texto ou legenda")
    else:
        missing.append("mídia, captura ou texto da publicação")

    if official_access:
        present.append("acesso oficial à conta")
    elif metric_count >= 4:
        present.append("métricas suficientes para taxas básicas")
    elif metric_count:
        present.append("métricas parciais")
        missing.append("alcance, circulação, retenção ou conversão")
    else:
        missing.append("métricas do Insights ou contagens visíveis")

    if comment_count:
        present.append("amostra de comentários")
    else:
        missing.append("textos dos comentários")

    if history_count >= 5:
        present.append("histórico comparável")
    else:
        missing.append("pelo menos 5 a 10 posts comparáveis")

    if mode == OWNER_MODE:
        score = min(
            100,
            (25 if media_count or has_text else 0)
            + (35 if official_access or metric_count >= 4 else 15 if metric_count else 0)
            + (15 if comment_count else 0)
            + (25 if history_count >= 5 else 0),
        )
    elif mode == EXTERNAL_MODE:
        score = min(
            85,
            (40 if media_count else 20 if has_text else 0)
            + (25 if metric_count >= 3 else 10 if metric_count else 0)
            + (20 if comment_count else 0),
        )
    else:
        score = min(45, (20 if has_text else 0) + (15 if metric_count else 0) + (10 if comment_count else 0))

    if score >= 75:
        level = "PRONTO PARA ANÁLISE PROFUNDA"
    elif score >= 45:
        level = "ANÁLISE PARCIAL CONFIÁVEL"
    else:
        level = "TRIAGEM OU CONTEÚDO INSUFICIENTE"

    return {
        "mode": mode,
        "score": score,
        "level": level,
        "present": present,
        "missing": missing,
        "hard_limits": [
            "A identidade de quem curtiu, salvou ou compartilhou não é fornecida.",
            "Os pesos internos e o score individual do ranking do Instagram não são públicos.",
            "Posts externos não expõem salvamentos, envios privados, alcance de não seguidores ou conversão.",
        ],
    }


def _mode() -> str:
    import streamlit as st

    value = str(st.session_state.get("vi_analysis_mode") or OWNER_MODE)
    return value if value in _MODES else OWNER_MODE


def _uploads(key: str) -> list[Any]:
    import streamlit as st

    value = st.session_state.get(key)
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _assets(key: str) -> list[ScreenshotAsset]:
    assets: list[ScreenshotAsset] = []
    for upload in _uploads(key):
        try:
            data = upload.getvalue()
        except AttributeError:
            continue
        if not data:
            continue
        assets.append(
            ScreenshotAsset(
                data=data,
                mime_type=str(getattr(upload, "type", "") or "image/jpeg"),
                name=str(getattr(upload, "name", "") or "screenshot"),
            )
        )
    return assets


def _install_mode_ui() -> None:
    import streamlit as st

    if getattr(st, "_viral_intel_evidence_mode_ui", False):
        return

    original_write = st.write
    original_text_input = st.text_input

    def write_with_analysis_mode(*args: Any, **kwargs: Any):
        result = original_write(*args, **kwargs)
        text = str(args[0]) if args else ""
        if text == (
            "A análise mais profunda combina mídia original, Insights autorizados, comentários e histórico do próprio perfil."
        ):
            st.radio(
                "Qual é a fonte desta análise?",
                _MODES,
                key="vi_analysis_mode",
                horizontal=True,
                help=(
                    "Escolha 'Meu post' para usar Insights e histórico da conta; 'Post externo' para uma "
                    "análise limitada ao material público fornecido; 'Link público' apenas para triagem."
                ),
            )
            mode = _mode()
            if mode == OWNER_MODE:
                st.success(
                    "Modo profundo: envie a mídia original, capturas dos Insights, comentários e histórico. "
                    "O link é apenas uma referência."
                )
            elif mode == EXTERNAL_MODE:
                st.info(
                    "Modo forense externo: envie a peça, a legenda, as contagens visíveis e os comentários. "
                    "Métricas privadas do proprietário continuarão indisponíveis."
                )
            else:
                st.warning(
                    "Triagem por link: o Instagram pode bloquear a coleta. Este modo nunca substitui mídia, "
                    "Insights, comentários e histórico fornecidos."
                )
        return result

    def text_input_with_evidence_uploads(label: str, *args: Any, **kwargs: Any):
        value = original_text_input(label, *args, **kwargs)
        if label != "Link público (opcional)":
            return value

        mode = _mode()
        if mode == OWNER_MODE:
            st.file_uploader(
                "Capturas dos Insights do post",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                key="vi_insights_screenshots",
                help=(
                    "Envie as telas com alcance, visualizações, compartilhamentos, salvamentos, não seguidores, "
                    "retenção e conversão. O sistema lê apenas o que estiver visível."
                ),
            )
            st.file_uploader(
                "Capturas dos comentários",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                key="vi_comment_screenshots",
                help="Envie capturas sequenciais e legíveis para extrair username, comentário e curtidas visíveis.",
            )
        elif mode == EXTERNAL_MODE:
            st.file_uploader(
                "Capturas dos comentários públicos",
                type=["jpg", "jpeg", "png", "webp"],
                accept_multiple_files=True,
                key="vi_comment_screenshots",
                help="Os comentários serão analisados somente quando estiverem legíveis nas capturas.",
            )
            st.caption(
                "Para post externo, envie também a imagem, o vídeo ou uma captura completa no primeiro campo."
            )
        else:
            st.caption(
                "Neste modo o link é testado como fonte pública, mas bloqueios e dados incompletos são esperados."
            )
        return value

    st.write = write_with_analysis_mode
    st.text_input = text_input_with_evidence_uploads
    st._viral_intel_evidence_mode_ui = True


def _metric_count(data: dict[str, Any]) -> int:
    fields = {
        "followers",
        "views",
        "reach",
        "impressions",
        "likes",
        "comments",
        "shares",
        "saves",
        "reposts",
        "follows",
        "profile_visits",
        "accounts_engaged",
        "non_followers_reach",
        "non_follower_reach_rate",
        "average_watch_time_seconds",
        "completion_rate",
        "retention_3s_rate",
    }
    return sum(data.get(field) is not None for field in fields)


def _reconcile_report(
    report: Any,
    *,
    readiness: dict[str, Any],
    insight_observation: InsightScreenshotObservation | None,
    comment_observation: CommentScreenshotObservation | None,
    observer_models: list[str],
    observer_errors: list[str],
) -> None:
    from app.ai.schema import GroundedInsight, StrategicReport

    technical = report.technical_analysis
    technical["evidence_readiness"] = readiness
    technical["insights_screenshot_observation"] = observation_json(insight_observation)
    technical["comment_screenshot_observation"] = observation_json(comment_observation)
    technical["evidence_observer_models"] = observer_models

    access = technical.get("data_access_report") or {}
    if insight_observation and insight_observation.metrics_for_merge():
        access["official_private_insights"] = True
        access["level"] = "owner_evidence_package"
    if comment_observation and comment_observation.comments_for_merge():
        access["comment_texts"] = True
        access["commenter_usernames"] = any(
            row.get("author") for row in comment_observation.comments_for_merge()
        )
    technical["data_access_report"] = access

    strategy = StrategicReport.model_validate(report.strategy)
    coverage = GroundedInsight(
        title="Cobertura real desta análise",
        finding=(
            f"{readiness['level']} ({readiness['score']}/100). "
            + ("Fontes presentes: " + ", ".join(readiness["present"]) + ". " if readiness["present"] else "")
            + ("Ainda falta: " + ", ".join(readiness["missing"]) + "." if readiness["missing"] else "")
        ),
        evidence_refs=[],
        confidence=100,
        limitation="A pontuação mede cobertura das fontes, não probabilidade de viralização.",
    )
    strategy.format_insights = [
        coverage,
        *[item for item in strategy.format_insights if item.title != coverage.title],
    ][:5]

    if readiness["mode"] == PUBLIC_MODE:
        strategy.performance_interpretation = (
            "Esta execução é uma triagem pública. Ela pode analisar somente o conteúdo e as contagens que "
            "forem efetivamente recuperados ou fornecidos; não representa uma leitura completa do post. "
            + strategy.performance_interpretation
        )
    elif readiness["mode"] == OWNER_MODE and readiness["score"] < 45:
        strategy.executive_summary = (
            "O modo profundo foi selecionado, mas o pacote de evidências ainda não contém dados suficientes."
        )
        strategy.performance_interpretation = (
            "Envie a mídia ou o texto do post e acrescente capturas dos Insights. Para comparar o desempenho, "
            "inclua também o histórico do perfil. O link isolado não será tratado como acesso completo."
        )

    report.strategy = strategy.model_dump(mode="json")
    report.provider_errors = [*report.provider_errors, *observer_errors]


def _install_pipeline_enrichment() -> None:
    import streamlit as st

    from app.config import get_settings
    from app.pipeline import main as pipeline

    if getattr(pipeline, "_viral_intel_evidence_ingestion", False):
        return

    original = pipeline.analyze_content

    def analyze_with_evidence_package(*args: Any, **kwargs: Any):
        settings = kwargs.get("settings") or get_settings()
        mode = _mode()
        insight_assets = _assets("vi_insights_screenshots") if mode == OWNER_MODE else []
        comment_assets = _assets("vi_comment_screenshots") if mode != PUBLIC_MODE else []

        insight_observation = None
        comment_observation = None
        observer_errors: list[str] = []
        observer_models: list[str] = []

        if insight_assets:
            insight_observation, errors, model = observe_insight_screenshots(settings, insight_assets)
            observer_errors.extend(errors)
            if model:
                observer_models.append(model)
            extracted_metrics = (
                insight_observation.metrics_for_merge() if insight_observation is not None else {}
            )
            kwargs["manual_metrics"] = merge_metric_evidence(
                kwargs.get("manual_metrics"),
                extracted_metrics,
            )

        if comment_assets:
            comment_observation, errors, model = observe_comment_screenshots(settings, comment_assets)
            observer_errors.extend(errors)
            if model:
                observer_models.append(model)
            extracted_comments = (
                comment_observation.comments_for_merge() if comment_observation is not None else []
            )
            kwargs["manual_comments"] = merge_comment_evidence(
                kwargs.get("manual_comments"),
                extracted_comments,
            )

        manual = kwargs.get("manual_metrics")
        manual_dict = (
            manual.model_dump(mode="python") if isinstance(manual, PostMetrics) else dict(manual or {})
        )
        context = dict(kwargs.get("distribution_context") or {})
        context["analysis_mode"] = mode
        context["evidence_package_declared"] = True
        kwargs["distribution_context"] = context

        readiness = evidence_readiness(
            mode=mode,
            media_count=len(kwargs.get("media_paths") or []),
            has_text=bool(str(st.session_state.get("vi_manual_caption") or "").strip()),
            metric_count=_metric_count(manual_dict),
            comment_count=len(kwargs.get("manual_comments") or []),
            history_count=len(kwargs.get("profile_history") or []),
            official_access=bool(
                str(kwargs.get("instagram_media_id") or "").strip()
                or str(kwargs.get("instagram_access_token") or "").strip()
                or settings.instagram_access_token
            ),
        )
        context["evidence_readiness"] = readiness

        report = original(*args, **kwargs)
        _reconcile_report(
            report,
            readiness=readiness,
            insight_observation=insight_observation,
            comment_observation=comment_observation,
            observer_models=observer_models,
            observer_errors=observer_errors,
        )
        return report

    pipeline.analyze_content = analyze_with_evidence_package
    pipeline._viral_intel_evidence_ingestion = True


def install_evidence_ingestion_guardrails() -> None:
    """Install the mode selector, screenshot readers and evidence-readiness contract."""

    global _INSTALLED
    if _INSTALLED:
        return
    _install_mode_ui()
    _install_pipeline_enrichment()
    _INSTALLED = True
