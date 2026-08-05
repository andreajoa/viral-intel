"""Quality controls for analyses that receive a public caption but no original media."""

from __future__ import annotations

import re
from typing import Any

_INSTALLED = False


def _caption_refs(evidence: list[Any]) -> list[str]:
    return [
        item.id
        for item in evidence
        if str(getattr(item, "label", "")).strip().lower() == "public caption"
    ][:4]


def _clean_findings(items: list[Any], limit: int = 3) -> list[str]:
    findings: list[str] = []
    for item in items:
        text = str(getattr(item, "finding", "") or "").strip()
        if text and text not in findings:
            findings.append(text)
        if len(findings) >= limit:
            break
    return findings


def _install_strategy_reconciliation() -> None:
    from app.ai.reliable_strategist import ReliableAIStrategist
    from app.ai.schema import CausalHypothesis, GroundedInsight

    if getattr(ReliableAIStrategist, "_viral_intel_link_content_gate", False):
        return

    original = ReliableAIStrategist.analyze

    def analyze_with_link_content(self: Any, *args: Any, **kwargs: Any):
        report, provider, model, errors = original(self, *args, **kwargs)
        technical = kwargs.get("technical") or {}
        quality = kwargs.get("quality")
        evidence = kwargs.get("evidence") or []

        public_caption = str(technical.get("public_caption") or "").strip()
        visual_summary = str(technical.get("creative_content_summary") or "").strip()
        if not public_caption or visual_summary:
            return report, provider, model, errors

        refs = _caption_refs(evidence)
        existing_findings = _clean_findings(report.format_insights)
        synthesis = " ".join(existing_findings[:2]).strip()
        if not synthesis:
            synthesis = (
                "A legenda pública foi recuperada e pode ser examinada quanto ao gancho, conflito, "
                "promessa, tensão e fechamento textual."
            )

        synthesis_insight = GroundedInsight(
            title="Síntese da leitura textual",
            finding=synthesis,
            evidence_refs=refs,
            confidence=82 if existing_findings else 70,
            limitation=(
                "A síntese utiliza a legenda pública e não descreve composição visual, áudio, ritmo, "
                "cortes ou retenção da mídia original."
            ),
        )
        coverage_insight = GroundedInsight(
            title="Alcance real desta análise",
            finding=(
                "O conteúdo textual foi analisado a partir do link público. A ausência do arquivo original "
                "limita a leitura visual e temporal, mas não invalida a análise da estrutura narrativa da legenda."
            ),
            evidence_refs=refs,
            confidence=98,
            limitation="Não permite avaliar execução visual nem comportamento de audiência não fornecido.",
        )

        titles = {item.title.strip().lower() for item in report.format_insights}
        enriched = list(report.format_insights)
        if synthesis_insight.title.lower() not in titles:
            enriched.append(synthesis_insight)
        if coverage_insight.title.lower() not in titles:
            enriched.append(coverage_insight)
        report.format_insights = enriched[:5]

        hypothesis = CausalHypothesis(
            title="Mecanismo textual provável de ressonância",
            finding=(
                synthesis
                + " Esses elementos sustentam uma hipótese plausível de identificação, curiosidade ou "
                "vontade de repassar a mensagem, mas não demonstram que a estrutura textual causou o alcance."
            ),
            evidence_refs=refs,
            confidence=58,
            limitation=(
                "Sem mídia original, alcance, compartilhamentos, salvamentos e histórico comparável, "
                "a relação entre texto e distribuição permanece hipotética."
            ),
            judgment="PLAUSÍVEL",
            needed_to_confirm=[
                "Comparar com publicações textuais semelhantes do mesmo perfil",
                "Confirmar alcance, compartilhamentos e salvamentos nos Insights",
                "Testar uma nova legenda mantendo o mesmo mecanismo e alterando apenas a situação",
            ],
        )
        report.root_cause_hypotheses = [
            hypothesis,
            *[
                item
                for item in report.root_cause_hypotheses
                if item.title.strip().lower() != hypothesis.title.lower()
            ],
        ][:5]

        if report.repeat_decision == "DADOS_INSUFICIENTES":
            score = getattr(quality, "completeness_score", 0)
            level = getattr(quality, "level", "BAIXA")
            report.executive_summary = (
                "O desempenho relativo permanece sem baseline, mas a legenda pública foi analisada e "
                "já sustenta uma leitura textual específica."
            )
            report.performance_interpretation = (
                f"Diagnóstico textual: disponível. Classificação estatística: inconclusiva. "
                f"Dados de distribuição: {level} ({score}/100). A ausência da mídia original limita "
                "a análise visual, não a leitura da estrutura narrativa da legenda."
            )

        return report, provider, model, errors

    ReliableAIStrategist.analyze = analyze_with_link_content
    ReliableAIStrategist._viral_intel_link_content_gate = True


def _install_metric_labels() -> None:
    from streamlit.delta_generator import DeltaGenerator

    if getattr(DeltaGenerator, "_viral_intel_metric_label_gate", False):
        return

    original = DeltaGenerator.metric

    def metric_with_clear_labels(
        self: Any,
        label: str,
        value: Any,
        *args: Any,
        **kwargs: Any,
    ):
        normalized = re.sub(r"[^a-zà-ÿ]+", " ", str(value).lower()).strip()
        if label == "Decisão" and (
            "dados insuficientes" in normalized or normalized == "dados insuficientes"
        ):
            value = "Sem baseline"
        if label == "Qualidade dos dados":
            label = "Dados de distribuição"
        return original(self, label, value, *args, **kwargs)

    DeltaGenerator.metric = metric_with_clear_labels
    DeltaGenerator._viral_intel_metric_label_gate = True


def install_link_content_guardrails() -> None:
    """Install idempotent report and UI corrections for public-link-only analyses."""

    global _INSTALLED
    if _INSTALLED:
        return
    _install_strategy_reconciliation()
    _install_metric_labels()
    _INSTALLED = True
