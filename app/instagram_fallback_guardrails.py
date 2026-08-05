"""Runtime safeguards for Instagram links blocked in cloud environments."""

from __future__ import annotations

from typing import Any

_INSTALLED = False


def _manual_text() -> str:
    import streamlit as st

    return str(st.session_state.get("vi_manual_caption") or "").strip()


def _install_caption_input() -> None:
    import streamlit as st

    if getattr(st, "_viral_intel_instagram_caption_input", False):
        return

    original_text_input = st.text_input

    def text_input_with_fallback(label: str, *args: Any, **kwargs: Any):
        value = original_text_input(label, *args, **kwargs)
        if label == "Link público (opcional)":
            st.text_area(
                "Legenda, texto falado ou texto da publicação (recomendado)",
                key="vi_manual_caption",
                height=120,
                placeholder=(
                    "Cole aqui a legenda ou o texto principal. Isso garante a análise mesmo quando "
                    "o Instagram bloqueia a leitura automática do link."
                ),
                help=(
                    "O Instagram pode limitar requisições feitas por servidores em nuvem. "
                    "O texto fornecido é analisado sem inventar imagens, áudio ou métricas."
                ),
            )
            st.caption(
                "Para Instagram, mantenha o link e cole também o texto. Se o link abrir normalmente, "
                "o sistema combina as fontes; se houver bloqueio 429, a análise textual continua."
            )
        return value

    st.text_input = text_input_with_fallback
    st._viral_intel_instagram_caption_input = True


def _has_creative_content(report: Any) -> bool:
    technical = report.technical_analysis or {}
    return any(
        str(technical.get(key) or "").strip()
        for key in (
            "manual_caption",
            "public_caption",
            "creative_content_summary",
            "creative_primary_hook",
        )
    )


def _collection_was_blocked(report: Any, url: str) -> bool:
    if not url.strip() or _has_creative_content(report):
        return False
    notes = " ".join(str(item) for item in (report.metrics.source_notes or [])).lower()
    return "coleta pública indisponível" in notes or "http error 429" in notes or "429" in notes


def _mark_text_evidence(report: Any) -> None:
    for item in report.evidence:
        label = str(item.label or "").strip().lower()
        if label == "manual caption":
            item.source = "texto fornecido pela pessoa usuária"
        elif label.startswith("creative "):
            item.source = "análise textual determinística do texto fornecido"


def _reconcile_manual_text_report(report: Any) -> None:
    from app.ai.schema import GroundedInsight, StrategicReport

    strategy = StrategicReport.model_validate(report.strategy)
    lowered = strategy.executive_summary.lower()
    refs = [
        item.id
        for item in report.evidence
        if str(item.label or "").lower().startswith("creative ")
    ][:8]

    if "não forneceu elementos criativos" in lowered or "captura não forneceu" in lowered:
        strategy.executive_summary = (
            "A classificação do desempenho permanece sem baseline, mas o texto fornecido foi analisado "
            "quanto ao gancho, conflito, emoção, progressão e potencial de compartilhamento."
        )
        strategy.performance_interpretation = (
            "Diagnóstico textual: disponível. Classificação estatística: inconclusiva sem histórico "
            "comparável e métricas de distribuição. O relatório não presume elementos visuais ou de áudio."
        )

    title = "Fonte utilizada nesta análise"
    if not any(item.title == title for item in strategy.format_insights):
        strategy.format_insights = [
            GroundedInsight(
                title=title,
                finding=(
                    "A leitura criativa foi feita sobre o texto colado no formulário. O link permanece "
                    "como referência, mas não é necessário fingir que a mídia foi acessada."
                ),
                evidence_refs=refs,
                confidence=98,
                limitation="Não descreve imagem, vídeo, áudio, cortes ou retenção sem a mídia original.",
            ),
            *strategy.format_insights,
        ][:5]

    report.strategy = strategy.model_dump(mode="json")
    report.technical_analysis["content_input_status"] = "manual_text_available"
    _mark_text_evidence(report)


def _replace_empty_blocked_report(report: Any) -> None:
    from app.ai.schema import Experiment, GroundedInsight, NextContentPlan, StrategicReport

    strategy = StrategicReport.model_validate(report.strategy)
    strategy.executive_summary = "O Instagram bloqueou a leitura automática do link nesta execução."
    strategy.performance_interpretation = (
        "Nenhuma mídia, legenda ou métrica pública foi recebida. Isso é um bloqueio de coleta HTTP 429, "
        "não um diagnóstico sobre a qualidade ou o alcance da publicação. Cole a legenda no novo campo "
        "do formulário ou envie a mídia original e execute novamente."
    )
    strategy.root_cause_hypotheses = []
    strategy.audience_insights = []
    strategy.format_insights = [
        GroundedInsight(
            title="Conteúdo não recebido",
            finding=(
                "O link foi informado, mas o servidor do Instagram recusou a coleta automática. "
                "Sem o conteúdo, o Viral Intel não realizará uma análise criativa genérica."
            ),
            evidence_refs=[],
            confidence=0,
            limitation="A análise será liberada quando a legenda ou a mídia forem fornecidas.",
        )
    ]
    strategy.next_content = NextContentPlan(
        format=report.metrics.format.value,
        objective="Disponibilizar o conteúdo antes de gerar recomendações estratégicas.",
        hook_options=[
            "Cole a legenda completa no campo de texto do formulário.",
            "Envie a imagem, os slides ou o vídeo original da publicação.",
        ],
        structure=[
            "1. Mantenha o link da publicação como referência.",
            "2. Cole a legenda ou envie a mídia original.",
            "3. Execute novamente para receber o diagnóstico real do conteúdo.",
        ],
        caption_direction="Nenhuma direção de legenda deve ser criada sem receber o conteúdo.",
        cta="Forneça a legenda ou a mídia e refaça a análise.",
        preserve=[],
        change=["adicionar uma fonte de conteúdo acessível"],
        based_on_refs=[],
    )
    strategy.experiments = [
        Experiment(
            hypothesis="O conteúdo poderá ser analisado quando uma fonte acessível for fornecida.",
            change_one_thing="Cole a legenda ou envie a mídia original.",
            keep_constant=["link", "plataforma", "objetivo da análise"],
            primary_metric="conteúdo recebido",
            comparison_rule="A nova execução deve exibir gancho, estrutura, emoção e limites específicos.",
            minimum_sample="Uma nova execução com texto ou mídia disponível.",
            based_on_refs=[],
        )
    ]
    report.strategy = strategy.model_dump(mode="json")
    report.technical_analysis["content_input_status"] = "instagram_collection_blocked"
    report.technical_analysis["collection_block_reason"] = "HTTP 429 ou coleta pública indisponível"


def _install_pipeline_fallback() -> None:
    import streamlit as st

    from app.analysis.text_content import analyze_text_content
    from app.pipeline import main as pipeline

    if getattr(pipeline, "_viral_intel_instagram_fallback", False):
        return

    original = pipeline.analyze_content

    def analyze_with_instagram_fallback(*args: Any, **kwargs: Any):
        manual_text = _manual_text()
        if manual_text:
            context = dict(kwargs.get("distribution_context") or {})
            context["manual_caption"] = manual_text
            context["caption_source"] = "manual_input"
            context.update(analyze_text_content(manual_text))
            kwargs["distribution_context"] = context

        report = original(*args, **kwargs)
        if manual_text:
            _reconcile_manual_text_report(report)
        elif _collection_was_blocked(report, str(kwargs.get("url") or "")):
            _replace_empty_blocked_report(report)
            st.session_state["vi_instagram_collection_blocked"] = True
        return report

    pipeline.analyze_content = analyze_with_instagram_fallback
    pipeline._viral_intel_instagram_fallback = True


def install_instagram_fallback_guardrails() -> None:
    """Install an idempotent caption fallback and honest 429 recovery state."""

    global _INSTALLED
    if _INSTALLED:
        return
    _install_caption_input()
    _install_pipeline_fallback()
    _INSTALLED = True
