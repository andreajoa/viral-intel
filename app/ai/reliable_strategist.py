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


def _refs_for(evidence: list[EvidenceItem], *labels: str) -> list[str]:
    refs: list[str] = []
    for label in labels:
        item = _find_evidence(evidence, label)
        if item is not None:
            refs.append(item.id)
    return list(dict.fromkeys(refs))[:8]


def _creative_refs(evidence: list[EvidenceItem]) -> list[str]:
    return [
        item.id
        for item in evidence
        if item.kind == "technical" and item.label.lower().startswith("creative ")
    ][:8]


def _cta_missing(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or normalized in {
        "não identificado",
        "nao identificado",
        "nenhum",
        "ausente",
        "não há",
        "nao ha",
    }


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
    styles = _items(technical.get("creative_style_signals"), 4)
    visual_structure = _items(technical.get("creative_visual_structure"), 4)
    tension = str(technical.get("creative_curiosity_or_tension") or "").strip()
    summary = str(technical.get("creative_content_summary") or "").strip()
    observed_cta = str(technical.get("creative_cta_observed") or "").strip()
    creative_available = bool(
        creative_refs or hook or mechanisms or emotions or styles or visual_structure or summary
    )

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
    if styles:
        finding_parts.append(
            "A apresentação visual sinaliza "
            + ", ".join(styles)
            + ", o que dá à mensagem aparência íntima e pessoal."
        )
    if visual_structure:
        finding_parts.append("A estrutura visual observada é " + ", ".join(visual_structure) + ".")
    if _cta_missing(observed_cta) and composition_refs:
        finding_parts.append(
            "Não há CTA explícito; a própria frase funciona como uma mensagem pronta para ser repassada a alguém."
        )
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
        if styles:
            architecture_parts.append("Estilo visual: " + ", ".join(styles) + ".")
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

    if _cta_missing(observed_cta) and composition_refs:
        report.next_content.change = [
            item
            for item in report.next_content.change
            if not ("cta" in item.lower() and "explícito" in item.lower())
        ]
        preserve_note = "manter a arte sem CTA intrusivo quando a própria mensagem já for compartilhável"
        if preserve_note not in report.next_content.preserve:
            report.next_content.preserve = [preserve_note, *report.next_content.preserve][:6]
        report.next_content.cta = (
            "Não interrompa a arte com um CTA comercial. Teste uma chamada discreta apenas na legenda, "
            "ou publique uma variação sem CTA para preservar a imersão emocional."
        )

    if report.repeat_decision == "DADOS_INSUFICIENTES":
        report.executive_summary = (
            "A posição do post em relação ao histórico do perfil permanece inconclusiva, mas a análise não é vazia: "
            "a peça apresenta mecanismos claros de identificação emocional e a composição visível do engajamento "
            "permite explicar o padrão de redistribuição observado."
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


def _enrich_forensics(
    report: StrategicReport,
    metrics: PostMetrics,
    benchmark: BenchmarkResult,
    evidence: list[EvidenceItem],
    technical: dict[str, Any],
) -> StrategicReport:
    """Guarantee a visible distribution, audience and account investigation."""

    distribution = technical.get("distribution_diagnosis") or {}
    comments = technical.get("comment_intelligence") or {}
    account = technical.get("official_account") or {}
    access = technical.get("data_access_report") or {}

    distribution_refs = _refs_for(
        evidence,
        "Distribution diagnosis",
        "Alcance de não seguidores",
        "Ações de circulação por 100 curtidas",
        "Razão vs mediana",
        "Novos seguidores atribuídos",
    )
    comment_refs = _refs_for(evidence, "Comment intelligence", "Official comments sample")
    account_refs = _refs_for(evidence, "Official account", "Seguidores no momento da captura")

    stages = distribution.get("stages") or []
    useful_stages = [
        stage
        for stage in stages
        if stage.get("status") not in {"NÃO_AVALIÁVEL", "INCONCLUSIVO"}
    ]
    path = _items(distribution.get("likely_distribution_path"), 5)
    strongest = _items(distribution.get("strongest_observed_signals"), 5)
    counter = _items(distribution.get("counter_signals_or_risks"), 4)

    if distribution and (path or useful_stages):
        finding_parts = []
        if path:
            finding_parts.append("Trajetória reconstruída: " + " ".join(path))
        if strongest:
            finding_parts.append("Sinais mais fortes: " + "; ".join(strongest) + ".")
        if counter:
            finding_parts.append("Sinais contrários ou riscos: " + "; ".join(counter) + ".")
        finding_parts.append(
            "A conclusão combina as etapas disponíveis; não representa acesso ao score privado nem aos pesos internos do Instagram."
        )
        has_official_expansion = metrics.non_follower_reach_rate is not None
        has_benchmark = benchmark.status != "INCONCLUSIVO"
        judgment = "SUSTENTADA" if has_official_expansion and has_benchmark else "PLAUSÍVEL"
        confidence = 86 if judgment == "SUSTENTADA" else 68 if useful_stages else 48
        hypothesis = CausalHypothesis(
            title="Trajetória provável de distribuição",
            finding=" ".join(finding_parts),
            evidence_refs=distribution_refs,
            confidence=confidence,
            limitation=(
                "O Instagram não entrega o score individual de ranking, o peso exato dos sinais ou a causa de cada impressão."
            ),
            judgment=judgment,
            counterevidence_refs=[],
            needed_to_confirm=_items(distribution.get("minimum_data_to_improve"), 5),
        )
        report.root_cause_hypotheses = [
            hypothesis,
            *[
                item
                for item in report.root_cause_hypotheses
                if item.title.lower() != hypothesis.title.lower()
            ],
        ][:5]

    if comments.get("available"):
        sample_size = int(comments.get("sample_size") or 0)
        unique = int(comments.get("unique_commenters") or 0)
        intents = comments.get("intent_distribution") or []
        intent_text = "; ".join(
            f"{item.get('intent')} ({item.get('share_of_sample_pct')}%)" for item in intents[:4]
        ) or "sem intenção dominante"
        finding = (
            f"A amostra contém {sample_size} comentários e {unique} comentadores identificáveis na fonte. "
            f"Padrões mais frequentes: {intent_text}. "
            f"Marcações aparecem em {comments.get('mention_rate_pct', 0)}% da amostra e perguntas em "
            f"{comments.get('question_rate_pct', 0)}%."
        )
        insight = GroundedInsight(
            title="Leitura da amostra de comentários",
            finding=finding,
            evidence_refs=comment_refs,
            confidence=88 if sample_size >= 30 else 65,
            limitation=str(comments.get("coverage_note") or "Comentários não representam toda a audiência."),
        )
        report.audience_insights = [
            insight,
            *[
                item
                for item in report.audience_insights
                if item.title.lower() != insight.title.lower()
            ],
        ][:5]

    if account:
        username = str(account.get("username") or "conta autenticada")
        follower_count = account.get("followers_count")
        media_count = account.get("media_count")
        biography = str(account.get("biography") or "").strip()
        account_parts = [f"Conta profissional autenticada: @{username}."]
        if follower_count is not None:
            account_parts.append(f"Seguidores informados pela API: {follower_count}.")
        if media_count is not None:
            account_parts.append(f"Publicações informadas: {media_count}.")
        if biography:
            account_parts.append(f"Posicionamento declarado na bio: {biography[:280]}")
        insight = GroundedInsight(
            title="Contexto da conta autenticada",
            finding=" ".join(account_parts),
            evidence_refs=account_refs,
            confidence=95,
            limitation=(
                "Esses campos descrevem a conta; não revelam reputação algorítmica, interesses privados da audiência ou o motivo causal do alcance."
            ),
        )
        report.profile_insights = [
            insight,
            *[
                item
                for item in report.profile_insights
                if item.title.lower() != insight.title.lower()
            ],
        ][:5]

    access_level = str(access.get("level") or "upload_and_manual_only")
    access_caveat = (
        f"Nível de acesso aos dados nesta execução: {access_level}. "
        "Contagens agregadas podem ser analisadas, mas a API não fornece a identidade individual de quem curtiu, salvou ou compartilhou."
    )
    if access_caveat not in report.caveats:
        report.caveats = [access_caveat, *report.caveats][:8]
    algorithm_caveat = (
        "O relatório reconstrói uma trajetória provável por superfícies e sinais observáveis; não conhece os pesos internos nem o score atribuído a cada usuário."
    )
    if algorithm_caveat not in report.caveats:
        report.caveats = [algorithm_caveat, *report.caveats][:8]

    if distribution and path:
        status = "confirmada em parte" if useful_stages else "ainda inconclusiva"
        report.performance_interpretation = (
            f"Investigação de distribuição {status}. "
            + report.performance_interpretation
            + " A análise separa elegibilidade, resposta inicial, circulação, expansão para não seguidores, conversa e conversão."
        )
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
        report = _enrich_resonance(report, metrics, benchmark, quality, evidence, technical)
        report = _enrich_forensics(report, metrics, benchmark, evidence, technical)
        return report, provider, model, errors

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
