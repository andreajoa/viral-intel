"""AI strategist with an independent evidence-claim verification pass."""

from __future__ import annotations

from typing import Any

from app.ai.claim_verifier import verify_report_claims
from app.ai.reliable_strategist import ReliableAIStrategist
from app.ai.schema import StrategicReport
from app.models import BenchmarkResult, DataQuality, EvidenceItem, PostMetrics


class VerifiedAIStrategist(ReliableAIStrategist):
    """Run the normal strategist, then independently challenge unsupported claims."""

    def analyze(
        self,
        metrics: PostMetrics,
        benchmark: BenchmarkResult,
        quality: DataQuality,
        evidence: list[EvidenceItem],
        technical: dict[str, Any],
        transcription: str,
        niche: str = "",
        images: list[bytes] | None = None,
    ) -> tuple[StrategicReport, str, str, list[str]]:
        report, provider, model, errors = super().analyze(
            metrics=metrics,
            benchmark=benchmark,
            quality=quality,
            evidence=evidence,
            technical=technical,
            transcription=transcription,
            niche=niche,
            images=images,
        )
        report, verification = verify_report_claims(
            report,
            metrics=metrics,
            benchmark=benchmark,
            evidence=evidence,
        )
        technical["claim_verification"] = verification
        return report, provider, model, errors
