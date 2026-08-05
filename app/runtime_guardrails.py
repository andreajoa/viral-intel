"""Production quality gates installed before the analysis pipeline is imported.

The guards prevent four failure modes observed in real Streamlit tests:
1. a missing screenshot count being converted into a factual zero;
2. an empty distribution framework being presented as a causal diagnosis;
3. a useful creative reading being buried by an inconclusive benchmark;
4. a long table of unavailable fields dominating the report.
"""

from __future__ import annotations

import re
from typing import Any

_ZERO_RE = re.compile(r"(?<!\d)0(?:[.,]0+)?(?!\d)")
_INSTALLED = False


def _texts(value: Any, limit: int = 6) -> list[str]:
    rows = value if isinstance(value, (list, tuple, set)) else [value]
    return [text for item in rows if (text := str(item or "").strip())][:limit]


def _explicit_zero(metric: Any) -> bool:
    """Accept zero only when the screenshot explicitly shows the digit zero."""

    if getattr(metric, "value", None) != 0:
        return True
    evidence = " ".join(
        [
            str(getattr(metric, "displayed_text", "") or ""),
            str(getattr(metric, "visual_evidence", "") or ""),
        ]
    ).lower()
    if not _ZERO_RE.search(evidence):
        return False
    metric_name = str(getattr(metric, "metric", "") or "").lower()
    context_markers = {
        "likes": ("coração", "curtida", "like"),
        "comments": ("balão", "comentário", "comment"),
        "reposts": ("setas", "repost"),
        "shares": ("avião", "compartilh", "envio"),
        "views": ("visualiza", "view", "play"),
        "saves": ("salv", "favorito", "bookmark"),
    }
    markers = context_markers.get(metric_name, ())
    return not markers or any(marker in evidence for marker in markers)


def _install_metric_gate() -> None:
    from app.ai.media_observer import MediaObservation

    if getattr(MediaObservation, "_viral_intel_strict_metrics", False):
        return

    def strict_metrics_for_prefill(self: Any, minimum_confidence: int = 75) -> dict[str, int]:
        values: dict[str, int] = {}
        for item in self.visible_metrics:
            if item.metric == "unknown" or item.value is None or item.confidence < minimum_confidence:
                continue
            if item.value == 0 and not _explicit_zero(item):
                continue
            values.setdefault(item.metric, item.value)
        return values

    MediaObservation.metrics_for_prefill = strict_metrics_for_prefill
    MediaObservation._viral_intel_strict_metrics = True


def _install_distribution_gate() -> None:
    from app.analysis import distribution as module

    if getattr(module, "_viral_intel_quality_gate", False):
        return
    original = module.build_distribution_diagnosis

    def guarded_distribution(*args: Any, **kwargs: Any) -> dict[str, Any]:
        diagnosis = original(*args, **kwargs)
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
                "A peça e as interações visíveis podem ser analisadas, mas não há métricas suficientes "
                "para reconstruir a distribuição. Ausência de dado não significa baixa entrega."
            )
        return diagnosis

    module.build_distribution_diagnosis = guarded_distribution
    module._viral_intel_quality_gate = True


def _creative_explanation(technical: dict[str, Any]) -> str:
    summary = str(technical.get("creative_content_summary") or "").strip()
    hook = str(technical.get("creative_primary_hook") or "").strip()
    mechanisms = _texts(technical.get("creative_hook_mechanisms"), 5)
    emotions = _texts(technical.get("creative_emotional_triggers"), 5)
    tension = str(technical.get("creative_curiosity_or_tension") or "").strip()
    promise = str(technical.get("creative_audience_promise") or "").strip()
    styles = _texts(technical.get("creative_style_signals"), 5)

    parts: list[str] = []
    if summary:
        parts.append(summary.rstrip(".") + ".")
    if hook:
        parts.append(f"O gancho observado é “{hook}”.")
    if mechanisms:
        parts.append("A construção usa " + ", ".join(mechanisms) + ".")
    if emotions:
        parts.append("As emoções acionadas pela mensagem são " + ", ".join(emotions) + ".")
    if tension:
        parts.append("A tensão central é " + tension.rstrip(".") + ".")
    if promise:
        parts.append("A promessa percebida para o público é " + promise.rstrip(".") + ".")
    if styles:
        parts.append("O estilo visual apresenta " + ", ".join(styles) + ".")
    return " ".join(parts)


def _install_strategy_gate() -> None:
    from app.ai.reliable_strategist import ReliableAIStrategist
    from app.ai.schema import CausalHypothesis, GroundedInsight

    if getattr(ReliableAIStrategist, "_viral_intel_quality_gate", False):
        return
    original = ReliableAIStrategist.analyze

    def guarded_analyze(self: Any, *args: Any, **kwargs: Any):
        report, provider, model, errors = original(self, *args, **kwargs)
        technical = kwargs.get("technical") or {}
        quality = kwargs.get("quality")
        evidence = kwargs.get("evidence") or []
        diagnosis = technical.get("distribution_diagnosis") or {}
        has_distribution = bool(diagnosis.get("has_distribution_evidence"))
        creative = _creative_explanation(technical)

        if not has_distribution:
            blocked_terms = (
                "trajetória provável de distribuição",
                "impossibilidade de reconstruir",
                "distribuição e recomendação algorítmica",
                "resposta inicial e engajamento",
                "baixa conversão",
            )
            report.root_cause_hypotheses = [
                item
                for item in report.root_cause_hypotheses
                if not any(term in item.title.lower() for term in blocked_terms)
            ]

        if creative:
            creative_refs = [
                item.id
                for item in evidence
                if item.kind == "technical" and item.label.lower().startswith("creative ")
            ][:8]
            insight = GroundedInsight(
                title="Arquitetura do conteúdo observada",
                finding=creative,
                evidence_refs=creative_refs,
                confidence=88,
                limitation=(
                    "Explica a construção e o potencial de ressonância da peça; não prova, isoladamente, "
                    "a causa da distribuição."
                ),
            )
            report.format_insights = [
                insight,
                *[
                    item
                    for item in report.format_insights
                    if item.title.lower() != insight.title.lower()
                ],
            ][:5]

            hypothesis = CausalHypothesis(
                title="Mecanismo provável de ressonância do conteúdo",
                finding=(
                    creative
                    + " Esses elementos formam uma hipótese plausível de identificação, atenção ou vontade "
                    "de repassar a mensagem, que precisa ser comparada com outros posts para ganhar força causal."
                ),
                evidence_refs=creative_refs,
                confidence=62,
                limitation=(
                    "Sem alcance, circulação, salvamentos, origem da distribuição e histórico comparável, "
                    "não é possível afirmar que esse mecanismo causou o resultado."
                ),
                judgment="PLAUSÍVEL",
                needed_to_confirm=[
                    "comparar com posts do mesmo formato e tema",
                    "confirmar alcance, compartilhamentos, reposts e salvamentos",
                    "testar uma nova peça mantendo o mesmo mecanismo e mudando uma variável",
                ],
            )
            report.root_cause_hypotheses = [
                hypothesis,
                *[
                    item
                    for item in report.root_cause_hypotheses
                    if item.title.lower() != hypothesis.title.lower()
                ],
            ][:5]

        if report.repeat_decision == "DADOS_INSUFICIENTES":
            score = getattr(quality, "completeness_score", 0)
            level = getattr(quality, "level", "BAIXA")
            if creative:
                report.executive_summary = (
                    "A classificação do desempenho relativo permanece sem baseline, mas a análise do conteúdo "
                    "está disponível e identifica mecanismos específicos de gancho, emoção, tensão e apresentação."
                )
                report.performance_interpretation = (
                    f"Análise criativa: disponível. Classificação estatística: inconclusiva. "
                    f"Qualidade dos dados de distribuição: {level} ({score}/100). "
                    "O relatório não transforma ausência de métricas em baixo desempenho."
                )
            else:
                report.executive_summary = (
                    "A captura não forneceu elementos criativos ou métricas suficientes para uma conclusão segura."
                )
        return report, provider, model, errors

    ReliableAIStrategist.analyze = guarded_analyze
    ReliableAIStrategist._viral_intel_quality_gate = True


def _install_ui_gate() -> None:
    """Make the useful content diagnosis the first report tab and compact empty access tables."""

    import streamlit as st

    if getattr(st, "_viral_intel_quality_gate", False):
        return

    original_tabs = st.tabs
    original_dataframe = st.dataframe
    original_metric = st.metric

    def quality_tabs(labels: Any, *args: Any, **kwargs: Any):
        label_list = list(labels)
        report_tabs = [
            "Distribuição e algoritmo",
            "Conteúdo",
            "Público e comentários",
            "Conta e histórico",
            "Próximo conteúdo",
            "Experimentos",
            "Evidências",
        ]
        if label_list == report_tabs:
            displayed = [
                "Análise do conteúdo",
                "Distribuição comprovável",
                "Público e comentários",
                "Conta e histórico",
                "Próximo conteúdo",
                "Experimentos",
                "Evidências",
            ]
            contexts = original_tabs(displayed, *args, **kwargs)
            return [contexts[1], contexts[0], *contexts[2:]]
        return original_tabs(labels, *args, **kwargs)

    def compact_dataframe(data: Any = None, *args: Any, **kwargs: Any):
        if isinstance(data, list) and data and all(isinstance(row, dict) for row in data):
            keys = set(data[0])
            if keys == {"Dado", "Disponível"} and any(
                row.get("Dado") == "Insights privados autorizados" for row in data
            ):
                available = [row for row in data if row.get("Disponível") == "Sim"]
                if available:
                    st.caption("Dados adicionais disponíveis nesta execução:")
                    return original_dataframe(available, *args, **kwargs)
                st.warning(
                    "Esta execução não acessou Insights privados, textos de comentários nem histórico do perfil. "
                    "Isso limita a classificação da distribuição, mas não impede a análise do conteúdo."
                )
                return None
        return original_dataframe(data, *args, **kwargs)

    def quality_metric(label: str, value: Any, *args: Any, **kwargs: Any):
        if label == "Decisão" and str(value) == "Dados insuficientes":
            value = "Sem baseline"
        if label == "Qualidade dos dados":
            label = "Dados de distribuição"
        return original_metric(label, value, *args, **kwargs)

    st.tabs = quality_tabs
    st.dataframe = compact_dataframe
    st.metric = quality_metric
    st._viral_intel_quality_gate = True


def install_production_guardrails() -> None:
    """Install idempotent quality gates before importing the pipeline/dashboard."""

    global _INSTALLED
    if _INSTALLED:
        return
    _install_metric_gate()
    _install_distribution_gate()
    _install_strategy_gate()
    _install_ui_gate()
    _INSTALLED = True
