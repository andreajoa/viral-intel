"""Export analysis envelopes without losing evidence or caveats."""

from __future__ import annotations

from pathlib import Path

from app.ai.schema import StrategicReport
from app.models import AnalysisEnvelope


def report_json(report: AnalysisEnvelope) -> str:
    return report.model_dump_json(indent=2)


def report_markdown(report: AnalysisEnvelope) -> str:
    strategy = StrategicReport.model_validate(report.strategy)
    lines = [
        "# Viral Intel — Relatório de evidências",
        "",
        f"**Relatório:** `{report.report_id}`  ",
        f"**Plataforma/formato:** {report.metrics.platform.value} / {report.metrics.format.value}  ",
        f"**Confiança dos dados:** {report.data_quality.level} ({report.data_quality.completeness_score}/100)  ",
        f"**Benchmark do perfil:** {report.benchmark.label}",
        "",
        "## Conclusão",
        "",
        strategy.executive_summary,
        "",
        strategy.performance_interpretation,
        "",
        f"**Decisão:** {strategy.repeat_decision}",
        "",
        "## Hipóteses de causa",
        "",
    ]
    for hypothesis in strategy.root_cause_hypotheses:
        refs = ", ".join(hypothesis.evidence_refs) or "sem evidência direta"
        lines.extend(
            [
                f"### {hypothesis.title}",
                "",
                f"{hypothesis.finding}",
                "",
                f"- Julgamento: {hypothesis.judgment}",
                f"- Confiança: {hypothesis.confidence}%",
                f"- Evidências: {refs}",
                f"- Limite: {hypothesis.limitation or 'não informado'}",
                "",
            ]
        )

    lines.extend(["## Próximo conteúdo", "", f"**Objetivo:** {strategy.next_content.objective}", ""])
    lines.append("### Opções de gancho")
    lines.extend(f"- {item}" for item in strategy.next_content.hook_options)
    lines.extend(["", "### Estrutura"])
    lines.extend(f"{index}. {item}" for index, item in enumerate(strategy.next_content.structure, 1))
    lines.extend(
        [
            "",
            f"**Direção da legenda:** {strategy.next_content.caption_direction}",
            "",
            f"**CTA:** {strategy.next_content.cta}",
            "",
            "## Experimentos",
            "",
        ]
    )
    for experiment in strategy.experiments:
        lines.extend(
            [
                f"- **Hipótese:** {experiment.hypothesis}",
                f"  - Alterar: {experiment.change_one_thing}",
                f"  - Métrica principal: {experiment.primary_metric}",
                f"  - Regra: {experiment.comparison_rule}",
                f"  - Amostra: {experiment.minimum_sample}",
            ]
        )

    lines.extend(["", "## Ledger de evidências", ""])
    lines.append("| ID | Tipo | Evidência | Valor | Fonte |")
    lines.append("|---|---|---|---:|---|")
    for item in report.evidence:
        value = "INDISPONÍVEL" if item.value is None else str(item.value)
        if item.unit:
            value += f" {item.unit}"
        label = item.label.replace("|", "/")
        source = item.source.replace("|", "/")
        lines.append(f"| {item.id} | {item.kind} | {label} | {value} | {source} |")

    if strategy.caveats:
        lines.extend(["", "## Limites", ""])
        lines.extend(f"- {caveat}" for caveat in strategy.caveats)
    lines.append("")
    return "\n".join(lines)


def save_report(report: AnalysisEnvelope, directory: str | Path) -> dict[str, Path]:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / f"{report.report_id}.json"
    markdown_path = destination / f"{report.report_id}.md"
    json_path.write_text(report_json(report), encoding="utf-8")
    markdown_path.write_text(report_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}
