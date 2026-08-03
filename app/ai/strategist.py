"""Multi-provider, schema-constrained strategy generation.

The deterministic evidence engine runs first.  The model may interpret and propose
experiments, but it cannot introduce a metric that is absent from the evidence ledger.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from app.ai.prompt_expert import SYSTEM_PROMPT
from app.ai.schema import (
    CausalHypothesis,
    Experiment,
    GroundedInsight,
    NextContentPlan,
    StrategicReport,
    validate_evidence_references,
)
from app.config import Settings, get_settings
from app.models import BenchmarkResult, DataQuality, EvidenceItem, PostMetrics

logger = logging.getLogger(__name__)


def _json_schema() -> dict[str, Any]:
    schema = StrategicReport.model_json_schema()

    def make_strict(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                properties = node.get("properties") or {}
                node["required"] = list(properties)
            for value in node.values():
                make_strict(value)
        elif isinstance(node, list):
            for value in node:
                make_strict(value)

    make_strict(schema)
    return schema


def _gemini_json_schema() -> dict[str, Any]:
    """Return only JSON Schema keywords accepted by Gemini structured output."""

    schema = _json_schema()
    unsupported = {
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "minLength",
        "maxLength",
        "pattern",
        "multipleOf",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "uniqueItems",
    }

    def clean(node: Any) -> None:
        if isinstance(node, dict):
            for key in list(node):
                if key in unsupported:
                    node.pop(key, None)
                else:
                    clean(node[key])
        elif isinstance(node, list):
            for value in node:
                clean(value)

    clean(schema)
    return schema


def _prompt(
    metrics: PostMetrics,
    benchmark: BenchmarkResult,
    quality: DataQuality,
    evidence: list[EvidenceItem],
    technical: dict[str, Any],
    transcription: str,
    niche: str,
) -> str:
    payload = {
        "niche": niche or "não informado",
        "platform": metrics.platform.value,
        "format": metrics.format.value,
        "benchmark_verdict": benchmark.model_dump(mode="json"),
        "data_quality": quality.model_dump(mode="json"),
        "evidence_ledger": [item.model_dump(mode="json") for item in evidence],
        "technical_context": technical,
        "transcription": transcription or "INDISPONÍVEL",
    }
    return (
        "Produza o diagnóstico e o próximo plano a partir do pacote abaixo. "
        "Não use conhecimento presumido sobre o desempenho deste post.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        + "\n\nJSON SCHEMA OBRIGATÓRIO:\n"
        + json.dumps(_json_schema(), ensure_ascii=False)
    )


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("A IA não retornou JSON válido") from None
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("A resposta estruturada precisa ser um objeto JSON")
    return value


def _image_data_url(image: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")


class AIStrategist:
    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or get_settings()
        self.provider_pref = (provider or self.settings.ai_provider or "auto").lower()
        self.model_override = model

    def _available_providers(self) -> list[str]:
        configured = {
            "gemini": bool(self.settings.google_api_key),
            "openai": bool(self.settings.openai_api_key),
            "anthropic": bool(self.settings.anthropic_api_key),
        }
        if self.provider_pref != "auto":
            return [self.provider_pref] if configured.get(self.provider_pref) else []
        return [name for name in self.settings.provider_order if configured.get(name)]

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
        prompt = _prompt(metrics, benchmark, quality, evidence, technical, transcription, niche)
        valid_ids = {item.id for item in evidence}
        errors: list[str] = []

        for provider in self._available_providers():
            try:
                if provider == "gemini":
                    raw, model = self._call_gemini(prompt, images or [])
                elif provider == "openai":
                    raw, model = self._call_openai(prompt, images or [])
                elif provider == "anthropic":
                    raw, model = self._call_anthropic(prompt, images or [])
                else:
                    raise ValueError(f"provedor desconhecido: {provider}")
                report = StrategicReport.model_validate(_extract_json(raw))
                return validate_evidence_references(report, valid_ids), provider, model, errors
            except Exception as exc:  # provider fallback is an intentional resilience boundary
                detail = str(exc)
                for secret in (
                    self.settings.google_api_key,
                    self.settings.openai_api_key,
                    self.settings.anthropic_api_key,
                ):
                    if secret:
                        detail = detail.replace(secret, "[CHAVE_OCULTA]")
                safe_error = f"{provider}: {type(exc).__name__}: {detail[:240]}"
                logger.warning("AI provider failed: %s", safe_error)
                errors.append(safe_error)

        report = deterministic_strategy(metrics, benchmark, quality, evidence, technical, niche)
        return report, "deterministic", "evidence-engine-v2", errors

    def _call_gemini(self, prompt: str, images: list[bytes]) -> tuple[str, str]:
        from google import genai
        from google.genai import types

        primary_model = self.model_override or self.settings.gemini_model
        models = [primary_model]
        if primary_model != "gemini-3.5-flash":
            models.append("gemini-3.5-flash")

        client = genai.Client(api_key=self.settings.google_api_key)
        request_text = SYSTEM_PROMPT + "\n\n" + prompt
        failures: list[str] = []
        try:
            for model in models:
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
                    text = interaction.output_text or ""
                    StrategicReport.model_validate(_extract_json(text))
                    return text, model
                except Exception as exc:
                    failures.append(f"interactions/{model}={type(exc).__name__}: {str(exc)[:160]}")

                try:
                    # JSON mode is intentionally schema-free here. It recovers from API
                    # rejection of a deeply nested schema while the prompt and Pydantic
                    # validation still enforce the complete contract locally.
                    parts = [types.Part.from_text(text=request_text)]
                    parts.extend(
                        types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images
                    )
                    response = client.models.generate_content(
                        model=model,
                        contents=parts,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            max_output_tokens=min(self.settings.max_ai_output_tokens, 8192),
                        ),
                    )
                    text = response.text or ""
                    StrategicReport.model_validate(_extract_json(text))
                    return text, model
                except Exception as exc:
                    failures.append(f"generate/{model}={type(exc).__name__}: {str(exc)[:160]}")

            raise RuntimeError("; ".join(failures))
        finally:
            client.close()

    def _call_openai(self, prompt: str, images: list[bytes]) -> tuple[str, str]:
        from openai import OpenAI

        model = self.model_override or self.settings.openai_model
        client = OpenAI(api_key=self.settings.openai_api_key)
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        content.extend(
            {"type": "input_image", "image_url": _image_data_url(image), "detail": "low"} for image in images
        )
        response = client.responses.create(
            model=model,
            reasoning={"effort": self.settings.openai_reasoning_effort},
            instructions=SYSTEM_PROMPT,
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "viral_intel_report",
                    "strict": True,
                    "schema": _json_schema(),
                },
                "verbosity": "medium",
            },
            max_output_tokens=self.settings.max_ai_output_tokens,
            store=False,
        )
        return response.output_text or "", model

    def _call_anthropic(self, prompt: str, images: list[bytes]) -> tuple[str, str]:
        from anthropic import Anthropic

        model = self.model_override or self.settings.anthropic_model
        client = Anthropic(api_key=self.settings.anthropic_api_key)
        content: list[dict[str, Any]] = []
        for image in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(image).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})
        response = client.messages.create(
            model=model,
            max_tokens=self.settings.max_ai_output_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_config={
                "format": {"type": "json_schema", "schema": _json_schema()},
                "effort": "medium",
            },
        )
        text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        return "\n".join(text_blocks), model


def _ref_for(evidence: list[EvidenceItem], label_fragment: str) -> list[str]:
    fragment = label_fragment.lower()
    return [item.id for item in evidence if fragment in item.label.lower()][:3]


def _text_items(value: Any, limit: int = 6) -> list[str]:
    """Normalize Gemini observations without leaking dict/list objects into prose."""

    values = value if isinstance(value, list | tuple | set) else [value]
    return [text for item in values if (text := str(item or "").strip())][:limit]


def deterministic_strategy(
    metrics: PostMetrics,
    benchmark: BenchmarkResult,
    quality: DataQuality,
    evidence: list[EvidenceItem],
    technical: dict[str, Any],
    niche: str,
) -> StrategicReport:
    """Useful offline report that remains honest when no AI key is configured."""

    benchmark_refs = [item.id for item in evidence if item.kind == "benchmark"]
    technical_refs = [item.id for item in evidence if item.kind == "technical"][:4]
    observed_refs = [item.id for item in evidence if item.kind == "observed"][:5]
    missing_labels = [item.label for item in evidence if item.kind == "missing"]
    creative_refs = [
        item.id
        for item in evidence
        if item.kind == "technical" and item.label.lower().startswith("creative ")
    ][:10]
    creative_summary = str(technical.get("creative_content_summary") or "").strip()
    primary_hook = str(technical.get("creative_primary_hook") or "").strip()
    mechanisms = _text_items(technical.get("creative_hook_mechanisms"), 4)
    promise = str(technical.get("creative_audience_promise") or "").strip()
    tension = str(technical.get("creative_curiosity_or_tension") or "").strip()
    observed_cta = str(technical.get("creative_cta_observed") or "").strip()
    emotional_triggers = _text_items(technical.get("creative_emotional_triggers"), 4)
    sequence = _text_items(technical.get("creative_sequence_or_progression"), 6)
    if not sequence:
        sequence = _text_items(technical.get("creative_visual_structure"), 6)
    risks = _text_items(technical.get("creative_risks_or_ambiguities"), 3)
    creative_available = bool(creative_summary or primary_hook or mechanisms)

    if benchmark.status == "BREAKOUT":
        decision = "REPETIR"
        summary = "O conteúdo foi um breakout relativo ao histórico comparável do próprio perfil."
    elif benchmark.status == "ACIMA_DO_TÍPICO":
        decision = "ITERAR"
        summary = "O conteúdo ficou acima do desempenho típico do próprio perfil."
    elif benchmark.status == "ABAIXO_DO_TÍPICO":
        decision = "MUDAR"
        summary = "O conteúdo ficou abaixo do desempenho típico do próprio perfil."
    elif benchmark.status == "TÍPICO":
        decision = "ITERAR"
        summary = "O conteúdo ficou dentro da faixa típica do próprio perfil."
    else:
        decision = "DADOS_INSUFICIENTES"
        summary = (
            "Ainda não há histórico comparável suficiente para afirmar se o conteúdo viralizou ou fracassou."
        )
    if creative_available:
        summary += " A execução criativa foi analisada e já permite planejar o próximo teste."

    hypothesis = CausalHypothesis(
        title="Desempenho relativo ao padrão do perfil",
        finding=(
            benchmark.label
            if benchmark.status != "INCONCLUSIVO"
            else "O desempenho não pode ser classificado com segurança sem um baseline comparável."
        ),
        evidence_refs=benchmark_refs,
        confidence=80 if benchmark.comparable_posts >= 10 else 45 if benchmark.comparable_posts >= 5 else 0,
        limitation="Comparação observacional não prova qual elemento criativo causou o resultado.",
        judgment="SUSTENTADA" if benchmark.status != "INCONCLUSIVO" else "NÃO_AVALIÁVEL",
        needed_to_confirm=(
            missing_labels[:4]
            if benchmark.status == "INCONCLUSIVO"
            else ["Teste controlado de uma variável por vez"]
        ),
    )

    hypotheses = [hypothesis]
    if creative_available:
        mechanism_text = ", ".join(mechanisms) or "o gancho observado"
        performance_known = benchmark.status != "INCONCLUSIVO"
        hypotheses.append(
            CausalHypothesis(
                title="Mecanismo criativo candidato a explicar o resultado",
                finding=(
                    f"O conteúdo usa {mechanism_text}. Como o desempenho foi comparado com o "
                    "histórico do perfil, esse mecanismo merece um teste de repetição controlado."
                    if performance_known
                    else f"O conteúdo usa {mechanism_text}, mas ainda faltam métricas e histórico "
                    "para saber se esse mecanismo ajudou ou prejudicou a distribuição."
                ),
                evidence_refs=(creative_refs + benchmark_refs)[:8],
                confidence=55 if performance_known else 20,
                limitation=(
                    "A presença do elemento criativo junto ao resultado é associação, não prova de causa."
                ),
                judgment="PLAUSÍVEL" if performance_known else "NÃO_AVALIÁVEL",
                needed_to_confirm=[
                    "Publicar variações mudando somente o gancho",
                    "Comparar no mesmo estágio de vida do post",
                    "Registrar alcance, salvamentos e compartilhamentos",
                ],
            )
        )

    format_insights: list[GroundedInsight] = []
    if technical_refs:
        format_insights.append(
            GroundedInsight(
                title="Execução técnica observada",
                finding="A mídia foi inspecionada localmente; use os sinais técnicos como contexto, não como prova de distribuição algorítmica.",
                evidence_refs=technical_refs,
                confidence=90,
                limitation="Qualidade técnica isolada não determina alcance.",
            )
        )

    if creative_available:
        creative_finding = creative_summary or "A mídia teve seus elementos criativos observados."
        if primary_hook:
            creative_finding += f" Gancho principal: “{primary_hook}”."
        if mechanisms:
            creative_finding += f" Mecanismos: {', '.join(mechanisms)}."
        format_insights.insert(
            0,
            GroundedInsight(
                title="Leitura do gancho e da estrutura",
                finding=creative_finding,
                evidence_refs=creative_refs[:8],
                confidence=85,
                limitation="A leitura visual descreve a execução; métricas são necessárias para medir o efeito.",
            ),
        )

    audience_insights: list[GroundedInsight] = []
    if promise or emotional_triggers:
        audience_bits = []
        if promise:
            audience_bits.append(f"promessa percebida: {promise}")
        if emotional_triggers:
            audience_bits.append(f"gatilhos observados: {', '.join(emotional_triggers)}")
        audience_insights.append(
            GroundedInsight(
                title="Promessa e reação pretendida",
                finding="; ".join(audience_bits).capitalize() + ".",
                evidence_refs=creative_refs[:8],
                confidence=75,
                limitation="A reação real do público exige comentários, retenção e métricas dos Insights.",
            )
        )

    if benchmark.primary_metric:
        experiment_metric = benchmark.primary_metric
    elif metrics.format.value == "carousel":
        experiment_metric = "salvamentos e compartilhamentos por alcance"
    elif metrics.views is not None:
        experiment_metric = "views"
    else:
        experiment_metric = "alcance e retenção inicial"
    comparison = (
        f"Superar a mediana de {benchmark.median_value:g} em {experiment_metric} no mesmo estágio de vida."
        if benchmark.median_value is not None
        else "Comparar no mesmo estágio de vida após reunir pelo menos 5 posts do mesmo formato."
    )
    base_refs = (benchmark_refs + observed_refs + creative_refs)[:8]

    if creative_available:
        hook_options = [
            (
                f"Recrie o padrão do gancho “{primary_hook[:120]}” com uma situação nova, "
                "mantendo a mesma tensão."
                if primary_hook
                else "Abra com o mesmo mecanismo de tensão, aplicado a uma situação nova."
            ),
            (
                f"Transforme a tensão “{tension[:120]}” em uma pergunta curta que exija continuar."
                if tension
                else "Antecipe uma consequência concreta e revele a explicação no slide seguinte."
            ),
        ]
        structure = [
            "1. Gancho: apresente a tensão ou contradição em uma única frase legível.",
        ]
        structure.extend(f"{index}. Progressão: {item}" for index, item in enumerate(sequence[:5], start=2))
        if len(structure) < 2:
            structure.append("2. Desenvolvimento: prove a promessa com uma cena ou exemplo específico.")
        structure.append(f"{len(structure) + 1}. Fechamento: resolva a promessa e peça uma ação mensurável.")
        preserve = ["formato e identidade visual"]
        if mechanisms:
            preserve.append("mecanismo do gancho: " + ", ".join(mechanisms[:3]))
        if promise:
            preserve.append("promessa central ao público")
        change = ["uma única variável criativa por publicação"]
        cta_missing = not observed_cta or observed_cta.lower() in {
            "não identificado",
            "nao identificado",
            "nenhum",
            "ausente",
        }
        if cta_missing:
            change.insert(0, "incluir um CTA explícito ligado à métrica principal")
        if risks:
            change.append("eliminar a principal ambiguidade: " + risks[0])
        objective = (
            "Criar uma continuação reconhecível, mantendo o mecanismo criativo e mudando apenas a história."
            if decision == "REPETIR"
            else "Testar uma variação controlada do mecanismo observado e medir o efeito no perfil."
        )
        caption_direction = (
            f"Conectar a tensão central ao nicho {niche or 'do perfil'}, sem repetir literalmente o post; "
            "entregar a promessa no conteúdo e usar a legenda para contexto e ação."
        )
        cta = (
            f"Preserve a intenção do CTA observado (“{observed_cta[:120]}”), mas formule uma ação "
            "única e mensurável."
            if not cta_missing
            else "Use um único CTA mensurável: salvar para consultar, compartilhar com alguém ou comentar uma experiência."
        )
        experiment_hypothesis = (
            f"O mecanismo {', '.join(mechanisms[:2])} sustenta melhor o interesse quando aplicado a uma nova história."
            if mechanisms
            else "O padrão do gancho observado sustenta melhor o interesse quando aplicado a uma nova história."
        )
    else:
        hook_options = [
            "Abra com a dor específica que o público reconhece em uma frase.",
            "Abra com uma contradição concreta que será resolvida no conteúdo.",
        ]
        structure = [
            "Gancho: promessa clara e específica.",
            "Contexto: mostre rapidamente para quem é e por que importa.",
            "Entrega: desenvolva uma ideia principal com exemplo concreto.",
            "Fechamento: conclua a promessa e convide a uma ação coerente.",
        ]
        preserve = ["tema e público"] if decision in {"REPETIR", "ITERAR"} else ["público-alvo"]
        change = ["uma única variável criativa por teste"]
        objective = (
            "Validar se a mesma promessa central sustenta o resultado com uma história diferente."
            if decision in {"REPETIR", "ITERAR"}
            else "Testar uma promessa mais clara sem alterar tema, duração e horário ao mesmo tempo."
        )
        caption_direction = f"Conectar o tema ao nicho {niche or 'informado pela pessoa usuária'}, sem acrescentar fatos não verificados."
        cta = "Peça a resposta que mede o objetivo real do post, como salvar, compartilhar ou comentar uma experiência."
        experiment_hypothesis = (
            "Uma promessa mais clara nos primeiros segundos melhora a distribuição relativa."
        )

    return StrategicReport(
        executive_summary=summary,
        performance_interpretation=(
            f"Confiança dos dados: {quality.level} ({quality.completeness_score}/100). "
            "A classificação é relativa ao perfil; não representa uma regra universal da plataforma. "
            + (
                "A leitura visual foi concluída e sustenta o diagnóstico de execução, mas não prova causa de distribuição."
                if creative_available
                else ""
            )
        ),
        repeat_decision=decision,
        root_cause_hypotheses=hypotheses,
        format_insights=format_insights,
        profile_insights=[
            GroundedInsight(
                title="Baseline do perfil",
                finding=benchmark.label,
                evidence_refs=benchmark_refs,
                confidence=80 if benchmark.comparable_posts >= 10 else 30,
                limitation="São recomendados 10 ou mais posts comparáveis.",
            )
        ],
        audience_insights=audience_insights,
        next_content=NextContentPlan(
            format=metrics.format.value,
            objective=objective,
            hook_options=hook_options,
            structure=structure[:12],
            caption_direction=caption_direction,
            cta=cta,
            preserve=preserve,
            change=change,
            based_on_refs=base_refs,
        ),
        experiments=[
            Experiment(
                hypothesis=experiment_hypothesis,
                change_one_thing="Trocar apenas o gancho; manter tema, formato, duração e janela de publicação próximos.",
                keep_constant=["tema", "formato", "duração aproximada", "janela de publicação"],
                primary_metric=experiment_metric,
                comparison_rule=comparison,
                minimum_sample="Publicar pelo menos 3 variações antes de concluir; idealmente comparar 5 ou mais.",
                based_on_refs=base_refs,
            )
        ],
        caveats=quality.limitations
        + [
            "O sistema não tem acesso ao código interno do algoritmo; ele testa hipóteses com métricas do perfil."
        ],
    )
