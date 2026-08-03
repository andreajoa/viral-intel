"""Streamlit dashboard for evidence-first content intelligence."""

from __future__ import annotations

import json
import re
import statistics
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st

from app.ai.schema import StrategicReport
from app.analysis.io import parse_optional_number, profile_posts_from_csv
from app.analysis.profile import summarize_profile
from app.config import get_settings
from app.media.inspector import MediaInspector, validate_media_selection
from app.models import AnalysisEnvelope, ContentFormat, Platform
from app.pipeline.main import analyze_content
from app.reporting.exporter import report_json, report_markdown

settings = get_settings()

st.set_page_config(
    page_title="Viral Intel",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --navy:#09274B; --terra:#A64B2A; --sand:#F3DED0; --cream:#FFF8F3; }
    .stApp { background: linear-gradient(180deg, #fffaf7 0%, #ffffff 34%); }
    [data-testid="stSidebar"] { background: #09274B; }
    [data-testid="stSidebar"] * { color: #FFF8F3; }
    [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea { color: #09274B; }
    h1, h2, h3 { color: #09274B; letter-spacing: -0.02em; }
    .hero { padding: 1.5rem 1.7rem; border-radius: 22px; background:#09274B; color:#FFF8F3;
            box-shadow: 0 18px 45px rgba(9,39,75,.18); margin-bottom:1.2rem; }
    .hero h1 { color:#FFF8F3; margin:0; font-size:2.35rem; }
    .hero p { margin:.45rem 0 0; max-width:850px; color:#F3DED0; font-size:1.02rem; }
    .truth-card { padding:1rem 1.2rem; border:1px solid #ecd8ce; border-radius:16px; background:#FFF8F3; }
    .evidence-id { display:inline-block; padding:.08rem .42rem; border-radius:7px; background:#F3DED0;
                   color:#09274B; font-weight:700; font-size:.82rem; }
    div.stButton > button[kind="primary"], div.stDownloadButton > button[kind="primary"] {
        background:#A64B2A; border-color:#A64B2A; color:white; border-radius:12px; font-weight:700;
    }
    [data-testid="stMetric"] { background:white; border:1px solid #efe2dc; border-radius:16px; padding:1rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def cached_inspector() -> MediaInspector:
    return MediaInspector(settings=settings)


def optional_number(label: str, key: str, help_text: str = "") -> float | int | None:
    raw = st.text_input(label, key=key, placeholder="Deixe vazio se não tiver", help=help_text)
    try:
        return parse_optional_number(raw)
    except (ValueError, TypeError):
        st.error(f"Valor inválido em “{label}”. Use somente números.")
        return None


def safe_filename(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name).strip("._")
    return stem[:120] or f"media_{uuid.uuid4().hex[:8]}"


def persist_uploads(files: list[Any]) -> list[Path]:
    batch_dir = settings.inbox_dir / ("upload_" + uuid.uuid4().hex[:12])
    batch_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for upload in files:
        destination = batch_dir / safe_filename(upload.name)
        destination.write_bytes(upload.getvalue())
        paths.append(destination)
    return paths


def fmt_number(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "Indisponível"
    if isinstance(value, float) and not value.is_integer():
        text = f"{value:,.2f}"
    else:
        text = f"{int(value):,}"
    return text.replace(",", ".") + suffix


def display_value(value: Any) -> str:
    """Keep every dataframe cell scalar so PyArrow never receives mixed objects."""

    if value is None:
        return "INDISPONÍVEL"
    if isinstance(value, dict | list | tuple | set):
        return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    return str(value)


def render_report(report: AnalysisEnvelope) -> None:
    strategy = StrategicReport.model_validate(report.strategy)
    st.divider()
    st.subheader("Conclusão baseada nos dados")
    cols = st.columns(4)
    decision_labels = {
        "DADOS_INSUFICIENTES": "Sem baseline",
        "REPETIR": "Repetir",
        "ITERAR": "Iterar",
        "MUDAR": "Mudar",
    }
    cols[0].metric("Decisão", decision_labels.get(strategy.repeat_decision, strategy.repeat_decision))
    cols[1].metric(
        "Confiança dos dados",
        f"{report.data_quality.level} · {report.data_quality.completeness_score}/100",
    )
    cols[2].metric("Comparáveis", report.benchmark.comparable_posts)
    cols[3].metric(
        "Vs. mediana",
        fmt_number(report.benchmark.ratio_to_median, "×")
        if report.benchmark.ratio_to_median is not None
        else "Inconclusivo",
    )
    st.markdown(f"### {strategy.executive_summary}")
    st.write(strategy.performance_interpretation)
    st.caption(f"Análise: {report.provider} · {report.model} · relatório {report.report_id}")
    if report.provider == "deterministic" and report.provider_errors:
        st.error(
            "A IA configurada não participou desta resposta. O relatório abaixo é o fallback "
            "determinístico; abra “Falhas de provedores” no final para ver o motivo."
        )
    elif report.provider != "deterministic":
        mode = "multimodal" if report.technical_analysis.get("creative_content_summary") else "estruturada"
        st.success(f"Análise {mode} concluída por {report.provider.title()} ({report.model}).")

    creative_summary = report.technical_analysis.get("creative_content_summary")
    if creative_summary:
        st.markdown("### Leitura criativa observável")
        st.write(creative_summary)
        hook, cta = st.columns(2)
        hook.write(
            "**Gancho observado:** "
            + str(report.technical_analysis.get("creative_primary_hook") or "Não identificado")
        )
        cta.write(
            "**CTA observado:** "
            + str(report.technical_analysis.get("creative_cta_observed") or "Não identificado")
        )
        mechanisms = report.technical_analysis.get("creative_hook_mechanisms") or []
        if mechanisms:
            st.write("**Mecanismos criativos:** " + ", ".join(map(str, mechanisms)))
        limitations = report.technical_analysis.get("creative_observation_limitations") or []
        if limitations:
            st.caption("Limites da leitura: " + " · ".join(map(str, limitations)))
        visible_metrics = report.technical_analysis.get("creative_visible_metric_observations") or []
        readable_metrics = [
            item
            for item in visible_metrics
            if item.get("value") is not None and int(item.get("confidence") or 0) >= 90
        ]
        if readable_metrics:
            labels = {
                "likes": "Curtidas visíveis",
                "comments": "Comentários visíveis",
                "reposts": "Reposts visíveis",
                "shares": "Compartilhamentos visíveis",
                "views": "Views visíveis",
            }
            columns = st.columns(min(len(readable_metrics), 4))
            for index, item in enumerate(readable_metrics[:4]):
                columns[index].metric(
                    labels.get(str(item.get("metric")), str(item.get("metric")).title()),
                    str(item.get("displayed_text") or fmt_number(item.get("value"))),
                )
            st.caption(
                "Números lidos da captura, não dos Insights privados. Confirme-os antes de "
                "usar o relatório como benchmark."
            )

    if report.data_quality.missing:
        with st.expander("Dados que faltaram e limitam a conclusão"):
            st.write(", ".join(report.data_quality.missing))
            for limitation in report.data_quality.limitations:
                st.write(f"• {limitation}")

    tab_diag, tab_evidence, tab_next, tab_experiments = st.tabs(
        ["Diagnóstico", "Evidências", "Próximo conteúdo", "Experimentos"]
    )
    with tab_diag:
        for hypothesis in strategy.root_cause_hypotheses:
            refs = " ".join(f"`{ref}`" for ref in hypothesis.evidence_refs) or "sem evidência direta"
            with st.container(border=True):
                st.markdown(f"#### {hypothesis.title}")
                st.write(hypothesis.finding)
                a, b = st.columns(2)
                a.write(f"**Julgamento:** {hypothesis.judgment}")
                b.write(f"**Confiança:** {hypothesis.confidence}%")
                st.markdown(f"**Base:** {refs}")
                if hypothesis.limitation:
                    st.caption(hypothesis.limitation)

        categories = [
            ("Formato", strategy.format_insights),
            ("Perfil", strategy.profile_insights),
            ("Público", strategy.audience_insights),
        ]
        for title, insights in categories:
            if insights:
                st.markdown(f"### {title}")
                for insight in insights:
                    st.markdown(f"**{insight.title}** — {insight.finding}")
                    st.caption("Evidências: " + (", ".join(insight.evidence_refs) or "nenhuma direta"))

    with tab_evidence:
        rows = []
        for item in report.evidence:
            rows.append(
                {
                    "ID": item.id,
                    "Tipo": item.kind,
                    "Evidência": item.label,
                    "Valor": display_value(item.value),
                    "Unidade": item.unit or "",
                    "Fonte": item.source,
                    "Fórmula/limite": item.formula or item.note or "",
                }
            )
        st.dataframe(rows, width="stretch", hide_index=True)
        with st.expander("Sinais técnicos da mídia"):
            st.json(report.technical_analysis)

    with tab_next:
        plan = strategy.next_content
        st.markdown(f"### Objetivo: {plan.objective}")
        left, right = st.columns(2)
        with left:
            st.markdown("#### Ganchos para testar")
            for hook in plan.hook_options:
                st.write(f"• {hook}")
            st.markdown("#### Manter")
            for item in plan.preserve:
                st.write(f"• {item}")
        with right:
            st.markdown("#### Estrutura")
            for index, item in enumerate(plan.structure, 1):
                st.write(f"{index}. {item}")
            st.markdown("#### Alterar")
            for item in plan.change:
                st.write(f"• {item}")
        st.info(f"**Legenda:** {plan.caption_direction}\n\n**CTA:** {plan.cta}")

    with tab_experiments:
        for index, experiment in enumerate(strategy.experiments, 1):
            with st.container(border=True):
                st.markdown(f"### Teste {index}: {experiment.hypothesis}")
                st.write(f"**Mude somente:** {experiment.change_one_thing}")
                st.write(f"**Métrica principal:** {experiment.primary_metric}")
                st.write(f"**Como comparar:** {experiment.comparison_rule}")
                st.write(f"**Amostra mínima:** {experiment.minimum_sample}")

    dl1, dl2 = st.columns(2)
    dl1.download_button(
        "Baixar relatório completo (.json)",
        report_json(report),
        file_name=f"{report.report_id}.json",
        mime="application/json",
        width="stretch",
    )
    dl2.download_button(
        "Baixar relatório para leitura (.md)",
        report_markdown(report),
        file_name=f"{report.report_id}.md",
        mime="text/markdown",
        width="stretch",
    )
    if report.provider_errors:
        with st.expander("Falhas de provedores e fallback aplicado"):
            st.write("A análise determinística continuou funcionando. Detalhes:")
            for error in report.provider_errors:
                st.code(error)


st.markdown(
    """
    <div class="hero">
      <h1>Viral Intel</h1>
      <p>Descubra o que os dados realmente sustentam, o que ainda é hipótese e qual deve ser o próximo teste do seu conteúdo.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Estado do sistema")
    providers = {
        "Gemini": bool(settings.google_api_key),
        "OpenAI": bool(settings.openai_api_key),
        "Anthropic": bool(settings.anthropic_api_key),
    }
    for name, configured in providers.items():
        st.write(("●" if configured else "○") + f" {name}: " + ("configurado" if configured else "sem chave"))
    st.caption("Sem chave de IA, o motor determinístico continua calculando o desempenho e os testes.")
    st.divider()
    st.markdown("### Regra central")
    st.write("Dado ausente não é zero. Hipótese não é causa comprovada.")

analysis_tab, profile_tab, method_tab = st.tabs(
    ["Analisar conteúdo", "Ler histórico do perfil", "Como a análise funciona"]
)

with analysis_tab:
    st.write(
        "Envie a mídia e, sempre que possível, copie os números do Insights. O link público é complementar."
    )
    with st.form("analysis_form"):
        top1, top2 = st.columns(2)
        platform_value = top1.selectbox(
            "Plataforma", [item.value for item in Platform if item != Platform.OTHER]
        )
        format_value = top2.selectbox(
            "Formato", [item.value for item in ContentFormat if item != ContentFormat.UNKNOWN]
        )
        media_uploads = st.file_uploader(
            "Vídeo, imagem ou slides do carrossel",
            type=["mp4", "mov", "m4v", "webm", "mkv", "jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help=(
                "Para carrossel, envie todos os slides na ordem correta. Se tiver apenas uma "
                "captura do post, ela será analisada como leitura parcial."
            ),
        )
        url = st.text_input(
            "Link público do post (opcional)", placeholder="https://www.instagram.com/reel/..."
        )
        niche = st.text_area(
            "Nicho, público e objetivo do perfil",
            placeholder="Ex.: autismo e TDAH para pais e cuidadores; objetivo: autoridade e compartilhamentos.",
            height=90,
        )
        meta1, meta2, meta3 = st.columns(3)
        topic = meta1.text_input("Tema/pilar do conteúdo", placeholder="Ex.: sinais do autismo")
        hook_type = meta2.text_input("Tipo de gancho", placeholder="Ex.: erro comum")
        cta_type = meta3.text_input("Objetivo do CTA", placeholder="Ex.: compartilhar")
        is_paid = st.checkbox("Este conteúdo teve impulsionamento ou mídia paga")
        profile_file = st.file_uploader(
            "Histórico do perfil em CSV (recomendado)",
            type=["csv"],
            help="Use pelo menos 10 posts do mesmo formato com métricas no mesmo estágio de vida.",
        )

        with st.expander("Métricas do Insights — preencha apenas o que realmente aparece"):
            age_hours = optional_number("Horas desde a publicação", "age_hours")
            r1 = st.columns(4)
            with r1[0]:
                followers = optional_number("Seguidores", "followers")
                views = optional_number("Visualizações", "views")
                reach = optional_number("Alcance", "reach")
            with r1[1]:
                likes = optional_number("Curtidas", "likes")
                comments = optional_number("Comentários", "comments")
                shares = optional_number("Compartilhamentos", "shares")
            with r1[2]:
                saves = optional_number("Salvamentos/favoritos", "saves")
                profile_visits = optional_number("Visitas ao perfil", "profile_visits")
                follows = optional_number("Novos seguidores", "follows")
            with r1[3]:
                avg_watch = optional_number("Tempo médio assistido (s)", "avg_watch")
                completion = optional_number("Taxa de conclusão (%)", "completion")
                retention_3s = optional_number("Retenção em 3s (%)", "retention_3s")
                nonfollowers = optional_number("Alcance de não seguidores (%)", "nonfollowers")
            r2 = st.columns(4)
            with r2[0]:
                impressions = optional_number("Impressões", "impressions")
            with r2[1]:
                impressions_ctr = optional_number("CTR de impressões (%)", "impressions_ctr")
            with r2[2]:
                average_view_pct = optional_number("Percentual médio assistido (%)", "average_view_pct")
            with r2[3]:
                reposts = optional_number("Reposts", "reposts")
        submitted = st.form_submit_button("Gerar análise verdadeira", type="primary", width="stretch")

    if submitted:
        selection_error = validate_media_selection(
            [Path(upload.name) for upload in (media_uploads or [])], format_value
        )
        if not media_uploads:
            st.error(
                "Envie o vídeo, a imagem, uma captura do post ou os slides do carrossel. "
                "O link público é complementar e não garante acesso à mídia."
            )
        elif selection_error:
            st.error(selection_error)
        else:
            try:
                paths = persist_uploads(list(media_uploads or []))
                profile_history = profile_posts_from_csv(profile_file.getvalue()) if profile_file else []
                captured_at = datetime.now(UTC)
                published_at = (
                    captured_at - timedelta(hours=float(age_hours)) if age_hours is not None else None
                )
                manual = {
                    "captured_at": captured_at,
                    "published_at": published_at,
                    "topic": topic or None,
                    "hook_type": hook_type or None,
                    "cta_type": cta_type or None,
                    "is_paid": is_paid,
                    "followers": followers,
                    "views": views,
                    "reach": reach,
                    "impressions": impressions,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "saves": saves,
                    "reposts": reposts,
                    "profile_visits": profile_visits,
                    "follows": follows,
                    "average_watch_time_seconds": avg_watch,
                    "completion_rate": completion,
                    "retention_3s_rate": retention_3s,
                    "non_follower_reach_rate": nonfollowers,
                    "average_view_percentage": average_view_pct,
                    "impressions_ctr": impressions_ctr,
                }
                with st.spinner("Inspecionando a mídia, calculando o baseline e testando hipóteses..."):
                    report = analyze_content(
                        media_paths=paths,
                        platform=platform_value,
                        content_format=format_value,
                        manual_metrics=manual,
                        profile_history=profile_history,
                        url=url,
                        niche=niche,
                        settings=settings,
                        inspector=cached_inspector(),
                    )
                st.session_state["latest_report"] = report.model_dump(mode="json")
            except Exception as exc:
                st.error(f"Não foi possível concluir a análise: {exc}")
                with st.expander("Detalhes técnicos para diagnóstico"):
                    st.exception(exc)

    if st.session_state.get("latest_report"):
        render_report(AnalysisEnvelope.model_validate(st.session_state["latest_report"]))

with profile_tab:
    st.subheader("O perfil faz parte da análise")
    st.write(
        "Um post não compete apenas com uma regra genérica: ele precisa ser comparado ao histórico do mesmo perfil, formato e estágio de vida."
    )
    profile_audit_file = st.file_uploader("Envie o CSV do histórico", type=["csv"], key="profile_audit")
    if profile_audit_file:
        try:
            posts = profile_posts_from_csv(profile_audit_file.getvalue())
            profile_summary = summarize_profile(posts)
            st.success(f"{len(posts)} posts válidos carregados.")
            groups: dict[tuple[str, str], list[Any]] = {}
            for post in posts:
                groups.setdefault((post.platform.value, post.format.value), []).append(post)
            summaries = []
            for (platform_name, format_name), rows in sorted(groups.items()):
                views_values = [row.views for row in rows if row.views is not None]
                reach_values = [row.reach for row in rows if row.reach is not None]
                summaries.append(
                    {
                        "Plataforma": platform_name,
                        "Formato": format_name,
                        "Posts": len(rows),
                        "Mediana de views": statistics.median(views_values) if views_values else None,
                        "Mediana de alcance": statistics.median(reach_values) if reach_values else None,
                        "Com retenção": sum(row.average_watch_time_seconds is not None for row in rows),
                        "Com shares": sum(row.shares is not None for row in rows),
                        "Com saves": sum(row.saves is not None for row in rows),
                    }
                )
            st.dataframe(summaries, width="stretch", hide_index=True)
            cadence = profile_summary.get("cadence") or {}
            if cadence.get("average_posts_per_week") is not None:
                a, b, c = st.columns(3)
                a.metric("Posts com data", cadence.get("posts_with_date", 0))
                b.metric("Período analisado", f"{cadence.get('date_span_days')} dias")
                c.metric("Média semanal", cadence.get("average_posts_per_week"))

            p_topics, p_hooks, p_ctas, p_top = st.tabs(["Temas", "Ganchos", "CTAs", "Top posts"])
            with p_topics:
                st.dataframe(profile_summary.get("topics") or [], width="stretch", hide_index=True)
            with p_hooks:
                st.dataframe(profile_summary.get("hook_types") or [], width="stretch", hide_index=True)
            with p_ctas:
                st.dataframe(profile_summary.get("cta_types") or [], width="stretch", hide_index=True)
            with p_top:
                st.dataframe(
                    profile_summary.get("top_posts_by_views") or [], width="stretch", hide_index=True
                )
            st.caption(str(profile_summary.get("interpretation_rule") or ""))
            st.caption("A auditoria detalhada de um post usa somente o grupo compatível com ele.")
        except Exception as exc:
            st.error(str(exc))

    template = (
        "platform,format,post_id,published_at,captured_at,followers,views,reach,impressions,likes,comments,shares,saves,follows,profile_visits,duration_seconds,average_watch_time_seconds,completion_rate,retention_3s_rate,average_view_percentage,non_follower_reach_rate,impressions_ctr,topic,hook_type,cta_type,is_paid\n"
        "instagram,reel,exemplo-01,2026-08-01T18:30:00-03:00,2026-08-02T18:30:00-03:00,14000,32000,25000,,1800,90,740,520,120,800,25,14.2,38,72,,,autismo,erro_comum,compartilhar,false\n"
    )
    st.download_button("Baixar modelo de CSV", template, "historico_perfil_modelo.csv", "text/csv")

with method_tab:
    st.subheader("O que o sistema consegue afirmar")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Fato ou cálculo")
        st.write(
            "Métricas fornecidas, propriedades técnicas da mídia e fórmulas transparentes entram no ledger com IDs próprios."
        )
        st.write("O desempenho é comparado à mediana de posts semelhantes do próprio perfil.")
    with c2:
        st.markdown("#### Hipótese")
        st.write(
            "Gancho, emoção, edição e promessa são explicações testáveis. O relatório informa confiança, limite e dado necessário para confirmar."
        )
        st.write("O sistema não afirma conhecer o código interno do algoritmo.")

    st.markdown("### Métricas priorizadas pelas próprias plataformas")
    st.markdown(
        """
        - [Instagram: como a classificação funciona](https://about.instagram.com/blog/announcements/instagram-ranking-explained)
        - [Instagram: recomendações e originalidade](https://creators.instagram.com/blog/recommendations-and-originality)
        - [TikTok: por que um vídeo é recomendado](https://newsroom.tiktok.com/en-us/learn-why-a-video-is-recommended-for-you)
        - [YouTube: alcance, impressões e tempo assistido](https://support.google.com/youtube/answer/9314486)
        - [YouTube: momentos-chave de retenção](https://support.google.com/youtube/answer/9314415)
        """
    )
    st.info(
        "Para uma conclusão forte, use métricas privadas do Insights e ao menos 10 posts comparáveis. Um link público sozinho gera confiança baixa."
    )
