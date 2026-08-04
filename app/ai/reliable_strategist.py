"""Resilient production strategist for current Gemini APIs."""

from __future__ import annotations

from typing import Any

from app.ai.prompt_expert import SYSTEM_PROMPT
from app.ai.schema import CausalHypothesis, GroundedInsight, StrategicReport
from app.ai.strategist import AIStrategist, _extract_json, _gemini_json_schema
from app.models import BenchmarkResult, DataQuality, EvidenceItem, PostMetrics


def _models(primary: str) -> list[str]:
    ordered = [
        primary,
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    ]
    return list(dict.fromkeys(model for model in ordered if model))


def _report_text(response: Any) -> str:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, StrategicReport):
        return parsed.model_dump_json()
    if isinstance(parsed, dict):
        return StrategicReport.model_validate(parsed).model_dump_json()
    text = getattr(response, "text", "") or getattr(response, "output_text", "") or ""
    report = StrategicReport.model_validate(_extract_json(text))
    return report.model_dump_json()


def _items(value: Any, limit: int = 5) -> list[str]:
    values = value if isinstance(value, list | tuple | set) else [value]
    return [text for item in values if (text := str(item or "").strip())][:limit]


def _find_evidence(evidence: list[EvidenceItem], label: str) -> EvidenceItem | None:
    lowered = label.lower()
    return next((item for item in evidence if lowered in item.label.lower()), None)


def _creative_refs(evidence: list[EvidenceItem]) -> list[str]:
    return [
        item.id
        for item in evidence
        if item.kind == "technical" and item.label.lower().startswith("creative ")
    ][:8]


def _enrich_resonance(
    report: StrategicReport,
    metrics: PostMetrics,
    benchmark: BenchmarkResult,
    quality: DataQuality,
    evidence: list[EvidenceItem],
    technical: dict[str, Any],
) -> StrategicReport:
    """Keep performance uncertainty separate from useful creative interpretation."""

    creative_refs = _creative_refs(evidence)
    hook = str(technical.get("creative_primary_hook") or "").strip()
    mechanisms = _items(technical.get("creative_hook_mechanisms"), 4)
    emotions = _items(technical.get("creative_emotional_triggers"), 4)
    tension = str(technical.get("creative_curiosity_or_tension") or "").strip()
    summary = str(technical.get("creative_content_summary") or "").strip()
    creative_available = bool(creative_refs or hook or mechanisms or emotions or summary)

    circulation_ratio = _find_evidence(evidence, "Circulação em relação aos comentários")
    circulation_per_likes = _find_evidence(evidence, "Ações de circulação por 100 curtidas")
    composition_refs = [item.id for item in (circulation_ratio, circulation_per_likes) if item is not None]

    if not creative_available and not composition_refs:
        return report

    finding_parts: list[str] = []
    if hook:
        finding_parts.append(f"O gancho observado é “{hook}”.")
    if mechanisms:
        finding_parts.append("A peça emprega " + ", ".join(mechanisms) + ".")
    if emotions:
        finding_parts.append("Os gatilhos emocionais observáveis são " + ", ".join(emotions) + ".")
    if tension:
        finding_parts.append(f"A tensão central é {tension}.")
    if circulation_ratio is not None:
        ratio = float(circulation_ratio.value)
        finding_parts.append(
            f"As ações de circulação conhecidas equivalem a {ratio:.1f} vezes o número de comentários, "
            "portanto a resposta visível se concentrou muito mais em redistribuição do que em conversa pública."
        )
    if circulation_per_likes is not None:
        ratio = float(circulation_per_likes.value)
        finding_parts.append(
            f"Foram observadas {ratio:.1f} ações de circulação conhecidas para cada 100 curtidas."
        )
    finding_parts.append(
        "Esse conjunto sustenta uma hipótese plausível de identificação pessoal e vontade de enviar a mensagem "
        "a alguém, mas não prova que esses elementos causaram o alcance."
    )

    resonance_refs = list(dict.fromkeys(creative_refs + composition_refs))[:8]
    resonance = CausalHypothesis(
        title="Ressonância emocional e impulso de compartilhar",
        finding=" ".join(finding_parts),
        evidence_refs=resonance_refs,
        confidence=72 if creative_refs and composition_refs else 58,
        limitation=(
            "A análise explica por que a mensagem é compartilhável e como o público respondeu visivelmente; "
            "sem baseline, alcance e impressões, não mede a posição relativa nem prova causalidade."
        ),
        judgment="PLAUSÍVEL",
        needed_to_confirm=[
            "Comparar com posts de frase emocional do mesmo perfil",
            "Confirmar alcance, compartilhamentos e salvamentos nos Insights",
            "Testar nova frase mantendo a mesma arquitetura emocional",
        ],
    )
    report.root_cause_hypotheses = [
        resonance,
        *[item for item in report.root_cause_hypotheses if item.title.lower() != resonance.title.lower()],
    ][:5]

    if creative_available:
        architecture_parts = []
        if summary:
            architecture_parts.append(summary)
        if hook:
            architecture_parts.append(f"Gancho: “{hook}”.")
        if mechanisms:
            architecture_parts.append("Mecanismos: " + ", ".join(mechanisms) + ".")
        report.format_insights = [
            GroundedInsight(
                title="Arquitetura criativa observada",
                finding=" ".join(architecture_parts),
                evidence_refs=creative_refs,
                confidence=88,
                limitation="Descreve a construção da peça, não a distribuição da plataforma.",
            ),
            *[
                item
                for item in report.format_insights
                if item.title.lower() != "arquitetura criativa observada"
            ],
        ][:5]

    if composition_refs:
        composition_text = (
            "A composição do engajamento visível aponta mais circulação da mensagem do que conversa pública."
        )
        if circulation_ratio is not None:
            composition_text += (
                f" A circulação conhecida foi {float(circulation_ratio.value):.1f} vezes os comentários."
            )
        report.audience_insights = [
            GroundedInsight(
                title="Padrão de resposta visível",
                finding=composition_text,
                evidence_refs=composition_refs,
                confidence=92,
                limitation=(
                    "A captura mostra contagens públicas; compartilhamentos privados, alcance e salvamentos "
                    "precisam ser confirmados nos Insights."
                ),
            ),
            *[
                item
                for item in report.audience_insights
                if item.title.lower() != "padrão de resposta visível"
            ],
        ][:5]

    if report.repeat_decision == "DADOS_INSUFICIENTES":
        report.executive_summary = (
            "A posição do post em relação ao histórico do perfil permanece inconclusiva, mas a análise não é vazia: "
            "a peça apresenta mecanismos claros de identificação emocional e a composição visível do engajamento "
            "permite explicar por que ela foi amplamente redistribuída."
        )
        report.performance_interpretation = (
            f"Status estatístico: inconclusivo por falta de baseline comparável. Diagnóstico criativo: disponível. "
            f"Qualidade geral dos dados: {quality.level} ({quality.completeness_score}/100). "
            "O app separa a classificação de viralização da explicação plausível de ressonância."
        )

    if benchmark.status == "INCONCLUSIVO" and metrics.likes is not None:
        caveat = (
            "As contagens absolutas descrevem tração observada, mas a palavra “viral” exige comparação com o "
            "tamanho e o histórico do perfil."
        )
        if caveat not in report.caveats:
            report.caveats = [caveat, *report.caveats][:8]
    return report


class ReliableAIStrategist(AIStrategist):
    """Use typed Gemini output first, then progressively safer recovery routes."""

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
        return (
            _enrich_resonance(report, metrics, benchmark, quality, evidence, technical),
            provider,
            model,
            errors,
        )

    def _call_gemini(self, prompt: str, images: list[bytes]) -> tuple[str, str]:
        from google import genai
        from google.genai import types

        primary_model = self.model_override or self.settings.gemini_model
        request_text = SYSTEM_PROMPT + "\n\n" + prompt
        contents: list[Any] = [request_text]
        contents.extend(types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images)
        failures: list[str] = []
        client = genai.Client(api_key=self.settings.google_api_key)

        try:
            for model in _models(primary_model):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=StrategicReport,
                            max_output_tokens=min(self.settings.max_ai_output_tokens, 32000),
                        ),
                    )
                    return _report_text(response), model
                except Exception as exc:
                    failures.append(f"typed/{model}={type(exc).__name__}: {str(exc)[:180]}")

                try:
                    interaction = client.interactions.create(
                        model=model,
                        input=request_text,
                        response_format={
                            "type": "text",
                            "mime_type": "application/json",
                            "schema": _gemini_json_schema(),
                        },
                    )
                    return _report_text(interaction), model
                except Exception as exc:
                    failures.append(f"interactions/{model}={type(exc).__name__}: {str(exc)[:180]}")

                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            max_output_tokens=min(self.settings.max_ai_output_tokens, 32000),
                        ),
                    )
                    return _report_text(response), model
                except Exception as exc:
                    failures.append(f"json/{model}={type(exc).__name__}: {str(exc)[:180]}")

            detail = "; ".join(failures)
            if self.settings.google_api_key:
                detail = detail.replace(self.settings.google_api_key, "[CHAVE_OCULTA]")
            raise RuntimeError(detail)
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                close()
