"""Reconstruct a post's probable Instagram distribution path from available evidence.

Instagram does not expose the internal score assigned to a post. This module therefore
separates measured distribution, evidence-backed inference and facts that remain
unknowable from the supplied data.
"""

from __future__ import annotations

from typing import Any

from app.models import BenchmarkResult, ContentFormat, PostMetrics


def _stage(
    name: str,
    status: str,
    finding: str,
    confidence: int,
    evidence: list[str] | None = None,
    limitation: str = "",
) -> dict[str, Any]:
    return {
        "stage": name,
        "status": status,
        "finding": finding,
        "confidence": max(0, min(100, confidence)),
        "evidence": evidence or [],
        "limitation": limitation,
    }


def _metric(value: float | int | None) -> bool:
    return value is not None


def _fmt(value: float | int | None, digits: int = 1) -> str:
    if value is None:
        return "indisponível"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.{digits}f}".replace(".", ",")
    return f"{int(value):,}".replace(",", ".")


def _surface_for(content_format: ContentFormat) -> str:
    if content_format == ContentFormat.REEL:
        return "Reels, recomendações no Feed e possíveis superfícies de descoberta"
    if content_format in {ContentFormat.IMAGE, ContentFormat.CAROUSEL}:
        return "Feed, Explorar e recomendações no Feed"
    return "superfície correspondente ao formato"


def build_distribution_diagnosis(
    metrics: PostMetrics,
    derived: dict[str, float],
    benchmark: BenchmarkResult,
    technical: dict[str, Any] | None = None,
    comment_summary: dict[str, Any] | None = None,
    data_access_level: str = "public_partial",
) -> dict[str, Any]:
    """Build an auditable algorithm/distribution diagnosis.

    The output never claims access to Instagram's private model weights or per-viewer
    ranking score. A probable path is produced only when the available metrics support it.
    """

    technical = technical or {}
    comment_summary = comment_summary or {}
    stages: list[dict[str, Any]] = []
    strongest: list[str] = []
    counter_signals: list[str] = []
    likely_path: list[str] = []
    unavailable: list[str] = []
    data_needed: list[str] = []

    recommendation_status = str(
        technical.get("recommendation_eligibility") or technical.get("account_recommendation_status") or ""
    ).strip()
    original_content = technical.get("original_content")
    if recommendation_status:
        positive = recommendation_status.lower() in {
            "eligible",
            "elegível",
            "eligible_for_recommendation",
            "recomendável",
            "ok",
        }
        stages.append(
            _stage(
                "Elegibilidade para recomendação",
                "COMPROVADO" if positive else "SINAL_DE_RISCO",
                f"O status informado da conta/conteúdo é: {recommendation_status}.",
                95,
                ["recommendation_eligibility"],
                "O status pode mudar após a captura e precisa vir do Status da Conta.",
            )
        )
    else:
        stages.append(
            _stage(
                "Elegibilidade para recomendação",
                "INCONCLUSIVO",
                "Não foi fornecido o Status da Conta nem a elegibilidade desta publicação.",
                0,
                limitation=(
                    "Um conteúdo pode permanecer visível aos seguidores e ainda assim não ser elegível "
                    "para recomendações a não seguidores."
                ),
            )
        )
        unavailable.append("elegibilidade real para recomendações")
        data_needed.append("captura do Status da Conta e da elegibilidade da publicação")

    if original_content is True:
        strongest.append("conteúdo informado como original")
    elif original_content is False:
        counter_signals.append("conteúdo informado como não original ou republicado")
    else:
        unavailable.append("confirmação de originalidade e possíveis correspondências de conteúdo")

    ratio_to_median = benchmark.ratio_to_median
    if benchmark.status != "INCONCLUSIVO" and ratio_to_median is not None:
        if ratio_to_median >= 1.25:
            finding = (
                f"A métrica principal ficou em {_fmt(ratio_to_median, 2)}× a mediana de "
                f"{benchmark.comparable_posts} posts comparáveis."
            )
            stages.append(
                _stage(
                    "Resposta inicial comparada ao próprio perfil",
                    "COMPROVADO",
                    finding,
                    90 if benchmark.comparable_posts >= 10 else 75,
                    ["benchmark"],
                    "O benchmark mostra desempenho relativo, não qual ação iniciou a expansão.",
                )
            )
            strongest.append(f"desempenho acima da mediana em {benchmark.primary_metric}")
            likely_path.append(
                "A publicação produziu resposta acima do padrão do próprio perfil no estágio comparado."
            )
        elif ratio_to_median < 0.8:
            stages.append(
                _stage(
                    "Resposta inicial comparada ao próprio perfil",
                    "COMPROVADO",
                    f"A métrica principal ficou em {_fmt(ratio_to_median, 2)}× a mediana comparável.",
                    88,
                    ["benchmark"],
                )
            )
            counter_signals.append("resposta abaixo da mediana do perfil")
        else:
            stages.append(
                _stage(
                    "Resposta inicial comparada ao próprio perfil",
                    "COMPROVADO",
                    "O resultado ficou dentro da faixa típica do histórico comparável.",
                    82,
                    ["benchmark"],
                )
            )
    else:
        stages.append(
            _stage(
                "Resposta inicial comparada ao próprio perfil",
                "INCONCLUSIVO",
                "Não há posts comparáveis suficientes no mesmo formato e estágio de vida.",
                0,
                limitation="Contagens absolutas não dizem se o resultado foi excepcional para esta conta.",
            )
        )
        data_needed.append("histórico de pelo menos 10 posts comparáveis no mesmo estágio de vida")

    circulation_per_likes = derived.get("circulation_to_likes_pct")
    circulation_vs_comments = derived.get("circulation_to_comments_ratio")
    if circulation_per_likes is not None:
        finding = f"Há {_fmt(circulation_per_likes)} ações de circulação conhecidas para cada 100 curtidas"
        if circulation_vs_comments is not None:
            finding += f", equivalentes a {_fmt(circulation_vs_comments)}× o volume de comentários"
        finding += "."
        stages.append(
            _stage(
                "Circulação social da mensagem",
                "COMPROVADO",
                finding,
                92,
                ["shares", "reposts", "likes", "comments"],
                "A composição mostra como as interações visíveis se distribuíram; não revela quem compartilhou.",
            )
        )
        strongest.append("circulação mensurável em relação às demais interações")
        likely_path.append(
            "A mensagem foi repassada em proporção relevante às interações visíveis, criando novas oportunidades de exposição."
        )
    elif metrics.shares is not None or metrics.reposts is not None:
        stages.append(
            _stage(
                "Circulação social da mensagem",
                "COMPROVADO",
                f"Foram registradas {_fmt((metrics.shares or 0) + (metrics.reposts or 0))} ações de circulação conhecidas.",
                88,
                ["shares", "reposts"],
                "Sem alcance ou visualizações, não é possível calcular a taxa de circulação por pessoa exposta.",
            )
        )
        data_needed.append("alcance ou visualizações para calcular taxa de circulação")
    else:
        stages.append(
            _stage(
                "Circulação social da mensagem",
                "NÃO_AVALIÁVEL",
                "Compartilhamentos e reposts não foram fornecidos.",
                0,
            )
        )
        data_needed.append("compartilhamentos, envios e reposts do Insights")

    non_follower_rate = metrics.non_follower_reach_rate
    reach_per_followers = derived.get("reach_per_follower_pct")
    views_per_followers = derived.get("views_per_follower_pct")
    if non_follower_rate is not None:
        stages.append(
            _stage(
                "Expansão para não seguidores",
                "COMPROVADO",
                f"{_fmt(non_follower_rate)}% do alcance informado veio de não seguidores.",
                95,
                ["non_follower_reach_rate"],
                "A porcentagem não informa em qual superfície cada pessoa encontrou a publicação.",
            )
        )
        if non_follower_rate >= 50:
            strongest.append("distribuição majoritária para não seguidores")
            likely_path.append(
                "A distribuição ultrapassou a base de seguidores, sinal compatível com recomendação e descoberta."
            )
    elif reach_per_followers is not None or views_per_followers is not None:
        proxy = reach_per_followers if reach_per_followers is not None else views_per_followers
        label = "alcance" if reach_per_followers is not None else "visualizações"
        stages.append(
            _stage(
                "Expansão para não seguidores",
                "PLAUSÍVEL",
                f"O volume de {label} equivale a {_fmt(proxy)}% da base de seguidores.",
                55,
                [f"{label}_per_follower"],
                "Esse quociente é apenas um proxy: seguidores podem gerar múltiplas visualizações e não seguidores podem não ter sido alcançados.",
            )
        )
    else:
        stages.append(
            _stage(
                "Expansão para não seguidores",
                "NÃO_AVALIÁVEL",
                "Não há alcance de não seguidores, alcance total ou visualizações comparáveis à base.",
                0,
            )
        )
        data_needed.append("alcance total e porcentagem de não seguidores")

    if metrics.saves is not None and metrics.reach:
        save_rate = derived.get("save_rate_by_views_pct")
        strongest.append(f"{_fmt(metrics.saves)} salvamentos observados")
        stages.append(
            _stage(
                "Valor de permanência e utilidade",
                "COMPROVADO",
                (
                    f"A publicação recebeu {_fmt(metrics.saves)} salvamentos."
                    + (f" A taxa por visualizações foi {_fmt(save_rate)}%." if save_rate is not None else "")
                ),
                88,
                ["saves"],
                "Salvamento é uma ação observada, mas seu peso exato no ranking não é público.",
            )
        )
    else:
        stages.append(
            _stage(
                "Valor de permanência e utilidade",
                "NÃO_AVALIÁVEL",
                "Salvamentos não foram fornecidos ou não há denominador para contextualizá-los.",
                0,
            )
        )
        data_needed.append("salvamentos e alcance/visualizações")

    if comment_summary.get("available"):
        sample_size = int(comment_summary.get("sample_size") or 0)
        mention_rate = comment_summary.get("mention_rate_pct")
        intents = comment_summary.get("intent_distribution") or []
        top_intents = (
            ", ".join(f"{item.get('intent')} ({item.get('count')})" for item in intents[:3])
            or "sem padrão dominante"
        )
        stages.append(
            _stage(
                "Qualidade da conversa observável",
                "COMPROVADO",
                f"Foram analisados {sample_size} comentários disponíveis. Intenções mais frequentes: {top_intents}.",
                86 if sample_size >= 30 else 62,
                ["comments_sample"],
                "Comentários são uma amostra autoselecionada e não representam toda a audiência.",
            )
        )
        if mention_rate is not None and mention_rate > 0:
            strongest.append(f"{_fmt(mention_rate)}% da amostra de comentários contém marcações")
    else:
        stages.append(
            _stage(
                "Qualidade da conversa observável",
                "NÃO_AVALIÁVEL",
                "O texto dos comentários não foi fornecido.",
                0,
            )
        )
        data_needed.append("comentários exportados ou acesso autorizado à mídia profissional")

    follow_conversion = derived.get("follow_conversion_by_reach_pct")
    profile_conversion = derived.get("profile_visit_conversion_pct")
    if metrics.follows is not None:
        finding = f"A publicação atribuiu {_fmt(metrics.follows)} novos seguidores"
        if follow_conversion is not None:
            finding += f", ou {_fmt(follow_conversion)}% do alcance"
        if profile_conversion is not None:
            finding += f"; {_fmt(profile_conversion)}% das visitas ao perfil converteram"
        finding += "."
        stages.append(
            _stage(
                "Conversão após o consumo",
                "COMPROVADO",
                finding,
                90,
                ["follows", "profile_visits", "reach"],
            )
        )
    else:
        stages.append(
            _stage(
                "Conversão após o consumo",
                "NÃO_AVALIÁVEL",
                "Novos seguidores atribuídos não foram fornecidos.",
                0,
            )
        )
        data_needed.append("novos seguidores e visitas ao perfil atribuídos ao conteúdo")

    if metrics.format in {ContentFormat.REEL, ContentFormat.VIDEO, ContentFormat.SHORT}:
        retention_available = any(
            _metric(value)
            for value in (
                metrics.average_watch_time_seconds,
                metrics.completion_rate,
                metrics.retention_3s_rate,
                metrics.average_view_percentage,
            )
        )
        if not retention_available:
            unavailable.append("retenção, conclusão, replays e abandono do vídeo")
            data_needed.append("tempo médio, retenção inicial, conclusão e replays")
    else:
        unavailable.append(
            "tempo real de leitura, pausas e permanência na imagem — o Instagram não entrega retenção de imagem equivalente à de vídeo"
        )

    unavailable.extend(
        [
            "peso exato de cada sinal nos modelos internos do Instagram",
            "score de ranking atribuído a cada pessoa",
            "identidade individual de quem enviou, compartilhou, salvou ou apenas visualizou",
            "motivo exato de cada impressão sem dados de origem e experimentos controlados",
        ]
    )

    if not likely_path:
        likely_path.append(
            "Os dados atuais descrevem a peça e algumas interações, mas ainda não reconstruem a expansão da distribuição."
        )

    surface = _surface_for(metrics.format)
    return {
        "framework": (
            "Diagnóstico por etapas: elegibilidade → resposta inicial → circulação → expansão para não seguidores → "
            "conversão. O Instagram usa sistemas de ranking por superfície; o aplicativo não presume um único algoritmo."
        ),
        "relevant_surfaces": surface,
        "data_access_level": data_access_level,
        "stages": stages,
        "likely_distribution_path": likely_path,
        "strongest_observed_signals": list(dict.fromkeys(strongest)),
        "counter_signals_or_risks": list(dict.fromkeys(counter_signals)),
        "cannot_be_known_from_current_data": list(dict.fromkeys(unavailable)),
        "minimum_data_to_improve": list(dict.fromkeys(data_needed)),
        "verdict": (
            "A explicação final deve combinar estas etapas. Nenhuma etapa isolada prova causalidade; a confiança cresce "
            "quando Insights privados, histórico comparável, comentários e evolução temporal apontam na mesma direção."
        ),
    }
