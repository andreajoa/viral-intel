"""Deterministic post-generation verification for evidence-backed AI reports.

The LLM is allowed to interpret creative evidence, but this verifier acts as an
independent final gate for claims that require specific performance metrics. It does
not try to rewrite the report; it lowers support and makes the missing evidence explicit.
"""

from __future__ import annotations

import re
from typing import Any

from app.models import BenchmarkResult, EvidenceItem, PostMetrics

from .schema import CausalHypothesis, StrategicReport

RULES = (
    (
        "retenção",
        re.compile(r"\b(reten[cç][aã]o|conclus[aã]o|tempo m[eé]dio assistido|watch time)\b", re.I),
        lambda m: any(
            value is not None
            for value in (
                m.average_watch_time_seconds,
                m.completion_rate,
                m.retention_3s_rate,
                m.average_view_percentage,
            )
        ),
    ),
    (
        "alcance de não seguidores",
        re.compile(r"\b(n[aã]o seguidores?|fora da base|expans[aã]o para n[aã]o seguidores)\b", re.I),
        lambda m: m.non_follower_reach_rate is not None or m.non_followers_reach is not None,
    ),
    (
        "salvamentos",
        re.compile(r"\b(salvamentos?|salvaram|save rate)\b", re.I),
        lambda m: m.saves is not None,
    ),
    (
        "compartilhamentos",
        re.compile(r"\b(compartilhamentos?|envios?|shares?|reposts?)\b", re.I),
        lambda m: m.shares is not None or m.reposts is not None,
    ),
    (
        "conversão em seguidores",
        re.compile(r"\b(convers[aã]o|seguidores? ganhos?|novos seguidores|visitas? ao perfil)\b", re.I),
        lambda m: m.follows is not None or m.profile_visits is not None,
    ),
)

PERFORMANCE_QUALIFIER = re.compile(
    r"\b(viral(?:izou|iza[cç][aã]o)?|acima do (?:normal|t[ií]pico)|abaixo do (?:normal|t[ií]pico)|fora da curva)\b",
    re.I,
)


def _claim_objects(report: StrategicReport) -> list[Any]:
    return [
        *report.root_cause_hypotheses,
        *report.format_insights,
        *report.profile_insights,
        *report.audience_insights,
    ]


def verify_report_claims(
    report: StrategicReport,
    *,
    metrics: PostMetrics,
    benchmark: BenchmarkResult,
    evidence: list[EvidenceItem],
) -> tuple[StrategicReport, dict[str, Any]]:
    valid_ids = {item.id for item in evidence}
    issues: list[dict[str, str]] = []

    for claim in _claim_objects(report):
        text = f"{getattr(claim, 'title', '')} {getattr(claim, 'finding', '')}"
        missing: list[str] = []
        for label, pattern, available in RULES:
            if pattern.search(text) and not available(metrics):
                missing.append(label)
        if PERFORMANCE_QUALIFIER.search(text) and benchmark.status == "INCONCLUSIVO":
            missing.append("benchmark comparável")

        invalid_refs = [ref for ref in getattr(claim, "evidence_refs", []) if ref not in valid_ids]
        if invalid_refs:
            missing.append("referências válidas no ledger")

        if not missing:
            continue

        unique = list(dict.fromkeys(missing))
        limitation = (
            "Verificação independente: faltam " + ", ".join(unique) + " para sustentar esta formulação."
        )
        current = str(getattr(claim, "limitation", "") or "").strip()
        claim.limitation = (current + " " + limitation).strip()
        claim.confidence = min(int(getattr(claim, "confidence", 0) or 0), 35)
        if isinstance(claim, CausalHypothesis):
            claim.judgment = "NÃO_AVALIÁVEL" if not claim.evidence_refs else "FRACA"
        issues.append({"claim": getattr(claim, "title", "sem título"), "missing": ", ".join(unique)})

    return report, {
        "version": "claim-verifier-v1",
        "checked_claims": len(_claim_objects(report)),
        "issues": issues,
        "passed": not issues,
    }
