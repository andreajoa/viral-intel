"""Strict, evidence-linked schema for strategic recommendations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _normalize_refs(value: object, limit: int = 8) -> object:
    """Deduplicate and cap evidence references before Pydantic length validation."""

    if not isinstance(value, list):
        return value
    normalized: list[str] = []
    for item in value:
        ref = str(item or "").strip()
        if ref and ref not in normalized:
            normalized.append(ref)
        if len(normalized) >= limit:
            break
    return normalized


class GroundedInsight(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    finding: str = Field(min_length=3)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    confidence: int = Field(ge=0, le=100)
    limitation: str = ""

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def normalize_evidence_refs(cls, value: object) -> object:
        return _normalize_refs(value)


class CausalHypothesis(GroundedInsight):
    judgment: Literal["SUSTENTADA", "PLAUSÍVEL", "FRACA", "NÃO_AVALIÁVEL"]
    counterevidence_refs: list[str] = Field(default_factory=list, max_length=8)
    needed_to_confirm: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("counterevidence_refs", mode="before")
    @classmethod
    def normalize_counterevidence_refs(cls, value: object) -> object:
        return _normalize_refs(value)


class Experiment(BaseModel):
    hypothesis: str
    change_one_thing: str
    keep_constant: list[str] = Field(default_factory=list, max_length=5)
    primary_metric: str
    comparison_rule: str
    minimum_sample: str
    based_on_refs: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("based_on_refs", mode="before")
    @classmethod
    def normalize_based_on_refs(cls, value: object) -> object:
        return _normalize_refs(value)


class NextContentPlan(BaseModel):
    format: str
    objective: str
    hook_options: list[str] = Field(default_factory=list, min_length=2, max_length=5)
    structure: list[str] = Field(default_factory=list, min_length=3, max_length=12)
    caption_direction: str
    cta: str
    preserve: list[str] = Field(default_factory=list, max_length=6)
    change: list[str] = Field(default_factory=list, max_length=6)
    based_on_refs: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("based_on_refs", mode="before")
    @classmethod
    def normalize_based_on_refs(cls, value: object) -> object:
        return _normalize_refs(value, limit=10)


class StrategicReport(BaseModel):
    executive_summary: str
    performance_interpretation: str
    repeat_decision: Literal["REPETIR", "ITERAR", "MUDAR", "DADOS_INSUFICIENTES"]
    root_cause_hypotheses: list[CausalHypothesis] = Field(default_factory=list, max_length=5)
    format_insights: list[GroundedInsight] = Field(default_factory=list, max_length=5)
    profile_insights: list[GroundedInsight] = Field(default_factory=list, max_length=5)
    audience_insights: list[GroundedInsight] = Field(default_factory=list, max_length=5)
    next_content: NextContentPlan
    experiments: list[Experiment] = Field(default_factory=list, min_length=1, max_length=3)
    caveats: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("executive_summary", "performance_interpretation")
    @classmethod
    def reject_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("texto obrigatório vazio")
        return value.strip()


def validate_evidence_references(report: StrategicReport, valid_ids: set[str]) -> StrategicReport:
    """Remove invalid citations and downgrade unsupported causal statements."""

    def valid(refs: list[str]) -> list[str]:
        return list(dict.fromkeys(ref for ref in refs if ref in valid_ids))

    for insight in (
        list(report.root_cause_hypotheses)
        + list(report.format_insights)
        + list(report.profile_insights)
        + list(report.audience_insights)
    ):
        insight.evidence_refs = valid(insight.evidence_refs)
        if isinstance(insight, CausalHypothesis):
            insight.counterevidence_refs = valid(insight.counterevidence_refs)
            if not insight.evidence_refs:
                insight.judgment = "NÃO_AVALIÁVEL"
                insight.confidence = 0
                insight.limitation = (
                    insight.limitation or "A hipótese não possui referência válida nos dados desta análise."
                )
        elif not insight.evidence_refs:
            insight.confidence = min(insight.confidence, 20)
            insight.limitation = insight.limitation or "Sem evidência direta nos dados fornecidos."

    report.next_content.based_on_refs = valid(report.next_content.based_on_refs)
    for experiment in report.experiments:
        experiment.based_on_refs = valid(experiment.based_on_refs)
    return report
