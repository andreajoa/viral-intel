"""Guided Streamlit interface for deep content and distribution forensics."""

from __future__ import annotations

import json
import re
import shutil
import statistics
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st

from app.ai.schema import GroundedInsight, StrategicReport
from app.analysis.io import comments_from_file, parse_optional_number, profile_posts_from_csv
from app.analysis.profile import summarize_profile
from app.config import get_settings
from app.media.inspector import MediaInspector, media_kind
from app.models import AnalysisEnvelope, Platform
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
    .stApp { background:linear-gradient(180deg,#fff8f3 0%,#fff 32%); }
    [data-testid="stSidebar"] { background:#09274B; }
    [data-testid="stSidebar"] * { color:#FFF8F3; }
    [data-testid="stSidebar"] input { color:#09274B; }
    h1,h2,h3 { color:#09274B; letter-spacing:-.025em; }
    .vi-hero { padding:1.55rem 1.7rem; border-radius:24px; background:linear-gradient(135deg,#09274B,#123f70);
      color:#FFF8F3; box-shadow:0 20px 50px rgba(9,39,75,.18); margin-bottom:1rem; }
    .vi-hero h1 { color:#FFF8F3; margin:0; font-size:clamp(2rem,5vw,3rem); }
    .vi-hero p { color:#F3DED0; margin:.5rem 0 0; max-width:980px; }
    .vi-chip { display:inline-block; padding:.2rem .55rem; border-radius:999px; background:#F3DED0;
      color:#09274B; font-weight:700; font-size:.78rem; margin-right:.3rem; }
    .vi-card { border:1px solid #ead8cf; border-radius:18px; padding:1rem 1.1rem; background:#fff; }
    .vi-stage { border-left:5px solid #A64B2A; border-radius:12px; padding:.85rem 1rem;
      background:#fff; border-top:1px solid #eadfd9; border-right:1px solid #eadfd9;
      border-bottom:1px solid #eadfd9; margin:.65rem 0; }
    [data-testid="stMetric"] { background:#fff; border:1px solid #eadfd9; border-radius:16px; padding:.85rem; }
    div.stButton > button[kind="primary"], div.stDownloadButton > button[kind="primary"] {
      background:#A64B2A; border-color:#A64B2A; color:#fff; border-radius:12px; font-weight:750; }
    @media (max-width:720px) { .vi-hero { padding:1.15rem; border-radius:18px; } }
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
    except (TypeError, ValueError):
        st.error(f"Valor inválido em “{label}”. Use apenas números.")
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


def cleanup_runtime(paths: list[Path], report_id: str | None = None) -> None:
    inbox = settings.inbox_dir.resolve()
    for directory in {path.resolve().parent for path in paths}:
        if directory.parent == inbox and directory.name.startswith("upload_"):
            shutil.rmtree(directory, ignore_errors=True)
    if report_id:
        shutil.rmtree(settings.temp_dir / report_id, ignore_errors=True)
        for suffix in (".json", ".md"):
            (settings.exports_dir / f"{report_id}{suffix}").unlink(missing_ok=True)


def fmt_number(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "Indisponível"
    if isinstance(value, float) and not value.is_integer():
        text = f"{value:,.2f}"
    else:
        text = f"{int(value):,}"
    return text.replace(",", ".") + suffix


def scalar(value: Any) -> str:
    if value is None:
        return "INDISPONÍVEL"
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    return str(value)


def guess_format_from_url(url: str) -> str | None:
    lowered = url.lower()
    if "/reel/" in lowered or "tiktok.com/" in lowered:
        return "reel"
    if "youtube.com/shorts/" in lowered or "youtu.be/" in lowered:
        return "short"
    if "/p/" in lowered:
        return "image"
    return None


def format_warning(upload_names: list[str], selected_format: str | None) -> str | None:
    if not upload_names:
        return None
    actual = media_kind([Path(name) for name in upload_names])
    if actual == "unknown":
        return "A seleção mistura tipos de mídia ou contém mais de um vídeo. Envie um vídeo ou somente imagens."
    if selected_format in {"reel", "short", "video"} and actual == "image":
        return "Captura estática aceita: a leitura criativa funcionará, mas ritmo, áudio e cortes não poderão ser medidos."
    if selected_format == "carousel" and actual == "image":
        return "Somente a capa será analisada. Para uma leitura completa, envie os slides na ordem correta."
    if selected_format == "image" and actual == "carousel":
        return "Há várias imagens; o sistema poderá reconhecer o material como carrossel."
    return None


def provider_message(report: AnalysisEnvelope) -> None:
    if report.provider == "hybrid":
        st.success("A IA observou a mídia e o motor de evidências protegeu as conclusões estatísticas.")
    elif report.provider == "gemini":
        st.success(f"Análise estruturada concluída pela Gemini ({report.model}).")
    elif report.provider == "deterministic" and report.provider_errors:
        st.warning("A IA não respondeu nesta execução. O relatório foi concluído pelo motor de evidências.")
    elif report.provider == "deterministic":
        st.info("Relatório determinístico concluído. Configure uma IA para aprofundar a interpretação criativa.")
    else:
        st.success(f"Análise concluída por {report.provider.title()} ({report.model}).")


def render_insights(title: str, insights: list[GroundedInsight]) -> None:
    if not insights:
        st.info(f"Nenhum insight de {title.lower()} foi sustentado pelos dados disponíveis.")
        return
    for insight in insights:
        with st.container(border=True):
            st.markdown(f"#### {insight.title}")
            st.write(insight.finding)
            st.caption(f"Confiança: {insight.confidence}%")
            if insight.evidence_refs:
                st.caption("Evidências: " + ", ".join(insight.evidence_refs))
            if insight.limitation:
                st.caption("Limite: " + insight.limitation)


def render_data_access(report: AnalysisEnvelope) -> None:
    access = report.technical_analysis.get("data_access_report") or {}
    if not access:
        return
    labels = {
        "official_private_insights": "Insights privados autorizados",
        "account_metadata": "Dados da conta profissional",
        "comment_texts": "Textos dos comentários",
        "commenter_usernames": "Usernames dos comentadores disponíveis",
        "profile_history": "Histórico comparável",
        "individual_liker_identities": "Identidade de quem curtiu",
        "individual_sharer_identities": "Identidade de quem compartilhou",
        "individual_saver_identities": "Identidade de quem salvou",
        "ranking_model_weights": "Pesos internos do ranking",
    }
    st.markdown("### Nível real de acesso aos dados")
    st.caption(f"Modo desta execução: {access.get('level', 'não informado')}")
    rows = [
        {"Dado": label, "Disponível": "Sim" if access.get(key) else "Não"}
        for key, label in labels.items()
    ]
    st.dataframe(rows, width="stretch", hide_index=True)
    st.info(str(access.get("note") or ""))


def render_distribution(report: AnalysisEnvelope) -> None:
    diagnosis = report.technical_analysis.get("distribution_diagnosis") or {}
    if not diagnosis:
        st.info("A trajetória de distribuição não foi calculada nesta execução.")
        return
    st.markdown("### Reconstrução da distribuição")
    st.write(diagnosis.get("framework") or "")
    st.caption("Superfícies relevantes: " + str(diagnosis.get("relevant_surfaces") or "não determinadas"))
    for stage in diagnosis.get("stages") or []:
        status = stage.get("status") or "INCONCLUSIVO"
        confidence = stage.get("confidence") or 0
        st.markdown(
            f"""
            <div class="vi-stage">
              <strong>{stage.get('stage', 'Etapa')}</strong><br>
              <small>{status} · confiança {confidence}%</small>
              <p>{stage.get('finding', '')}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if stage.get("limitation"):
            st.caption("Limite: " + str(stage["limitation"]))

    path = diagnosis.get("likely_distribution_path") or []
    if path:
        st.markdown("#### Caminho mais provável")
        for index, item in enumerate(path, 1):
            st.write(f"{index}. {item}")

    left, right = st.columns(2)
    with left:
        st.markdown("#### Sinais mais fortes")
        for item in diagnosis.get("strongest_observed_signals") or []:
            st.write(f"• {item}")
    with right:
        st.markdown("#### Riscos ou sinais contrários")
        risks = diagnosis.get("counter_signals_or_risks") or []
        if risks:
            for item in risks:
                st.write(f"• {item}")
        else:
            st.write("Nenhum sinal contrário mensurável foi fornecido.")

    with st.expander("O que não pode ser descoberto com os dados atuais"):
        for item in diagnosis.get("cannot_be_known_from_current_data") or []:
            st.write(f"• {item}")
    with st.expander("Menor conjunto de dados para aprofundar a conclusão"):
        for item in diagnosis.get("minimum_data_to_improve") or []:
            st.write(f"• {item}")


def render_comments(report: AnalysisEnvelope) -> None:
    comments = report.technical_analysis.get("comment_intelligence") or {}
    if not comments.get("available"):
        st.info(comments.get("coverage_note") or "Não há textos de comentários disponíveis.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Comentários analisados", comments.get("sample_size", 0))
    c2.metric("Comentadores únicos", comments.get("unique_commenters", 0))
    c3.metric("Com marcações", fmt_number(comments.get("mention_rate_pct"), "%"))
    c4.metric("Com perguntas", fmt_number(comments.get("question_rate_pct"), "%"))

    intents = comments.get("intent_distribution") or []
    if intents:
        st.markdown("#### O que as pessoas estavam fazendo nos comentários")
        st.dataframe(intents, width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.markdown("#### Termos recorrentes")
        st.dataframe(comments.get("top_terms") or [], width="stretch", hide_index=True)
    with right:
        st.markdown("#### Direção emocional da amostra")
        sentiment = comments.get("sentiment_direction") or {}
        st.dataframe(
            [{"Direção": key, "Comentários": value} for key, value in sentiment.items()],
            width="stretch",
            hide_index=True,
        )

    top_comments = comments.get("top_comments_by_visible_likes") or []
    if top_comments:
        with st.expander("Comentários com mais curtidas visíveis na amostra"):
            st.dataframe(top_comments, width="stretch", hide_index=True)
    st.caption(str(comments.get("coverage_note") or ""))
    st.caption(str(comments.get("privacy_note") or ""))


def render_report(report: AnalysisEnvelope) -> None:
    strategy = StrategicReport.model_validate(report.strategy)
    st.divider()
    st.subheader("Diagnóstico final")

    labels = {
        "DADOS_INSUFICIENTES": "Dados insuficientes",
        "REPETIR": "Repetir",
        "ITERAR": "Iterar",
        "MUDAR": "Mudar",
    }
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Decisão", labels.get(strategy.repeat_decision, strategy.repeat_decision))
    c2.metric("Qualidade dos dados", f"{report.data_quality.level} · {report.data_quality.completeness_score}/100")
    c3.metric("Posts comparáveis", report.benchmark.comparable_posts)
    c4.metric(
        "Vs. mediana",
        fmt_number(report.benchmark.ratio_to_median, "×")
        if report.benchmark.ratio_to_median is not None
        else "Inconclusivo",
    )

    st.markdown(f"### {strategy.executive_summary}")
    st.write(strategy.performance_interpretation)
    provider_message(report)
    st.caption(f"Relatório {report.report_id} · {report.provider} · {report.model}")
    render_data_access(report)

    tabs = st.tabs(
        [
            "Distribuição e algoritmo",
            "Conteúdo",
            "Público e comentários",
            "Conta e histórico",
            "Próximo conteúdo",
            "Experimentos",
            "Evidências",
        ]
    )

    with tabs[0]:
        render_distribution(report)
        st.markdown("### Hipóteses causais")
        for hypothesis in strategy.root_cause_hypotheses:
            with st.container(border=True):
                st.markdown(f"#### {hypothesis.title}")
                st.write(hypothesis.finding)
                a, b = st.columns(2)
                a.write(f"**Julgamento:** {hypothesis.judgment}")
                b.write(f"**Confiança:** {hypothesis.confidence}%")
                if hypothesis.evidence_refs:
                    st.caption("Evidências: " + ", ".join(hypothesis.evidence_refs))
                if hypothesis.limitation:
                    st.caption("Limite: " + hypothesis.limitation)
                if hypothesis.needed_to_confirm:
                    st.write("**Para confirmar:** " + " · ".join(hypothesis.needed_to_confirm))

    with tabs[1]:
        creative = report.technical_analysis.get("creative_content_summary")
        if creative:
            st.markdown("### O que foi observado na peça")
            st.write(creative)
            hook, cta = st.columns(2)
            hook.info(
                "**Gancho observado**\n\n"
                + str(report.technical_analysis.get("creative_primary_hook") or "Não identificado")
            )
            cta.info(
                "**CTA observado**\n\n"
                + str(report.technical_analysis.get("creative_cta_observed") or "Não identificado")
            )
            mechanisms = report.technical_analysis.get("creative_hook_mechanisms") or []
            if mechanisms:
                st.write("**Mecanismos criativos:** " + " · ".join(map(str, mechanisms)))
        render_insights("formato", strategy.format_insights)

    with tabs[2]:
        render_comments(report)
        st.markdown("### Insights sobre a resposta do público")
        render_insights("público", strategy.audience_insights)

    with tabs[3]:
        account = report.technical_analysis.get("official_account") or {}
        if account:
            st.markdown("### Conta profissional autenticada")
            safe_account = {
                key: value
                for key, value in account.items()
                if key in {"username", "name", "biography", "website", "followers_count", "follows_count", "media_count"}
            }
            st.json(safe_account)
        render_insights("perfil", strategy.profile_insights)
        profile_summary = report.technical_analysis.get("profile_history_summary") or {}
        if profile_summary:
            with st.expander("Resumo do histórico comparável"):
                st.json(profile_summary)

    with tabs[4]:
        plan = strategy.next_content
        st.markdown(f"### Objetivo: {plan.objective}")
        left, right = st.columns(2)
        with left:
            st.markdown("#### Ganchos para testar")
            for item in plan.hook_options:
                st.write(f"• {item}")
            st.markdown("#### Manter")
            for item in plan.preserve:
                st.write(f"• {item}")
        with right:
            st.markdown("#### Estrutura sugerida")
            for index, item in enumerate(plan.structure, 1):
                st.write(f"{index}. {item}")
            st.markdown("#### Alterar")
            for item in plan.change:
                st.write(f"• {item}")
        st.info(f"**Direção da legenda:** {plan.caption_direction}\n\n**CTA:** {plan.cta}")

    with tabs[5]:
        for index, experiment in enumerate(strategy.experiments, 1):
            with st.container(border=True):
                st.markdown(f"#### Teste {index}: {experiment.hypothesis}")
                st.write(f"**Mude apenas:** {experiment.change_one_thing}")
                st.write(f"**Mantenha constante:** {' · '.join(experiment.keep_constant)}")
                st.write(f"**Métrica principal:** {experiment.primary_metric}")
                st.write(f"**Regra de comparação:** {experiment.comparison_rule}")
                st.write(f"**Amostra mínima:** {experiment.minimum_sample}")

    with tabs[6]:
        rows = [
            {
                "ID": item.id,
                "Tipo": item.kind,
                "Evidência": item.label,
                "Valor": scalar(item.value),
                "Fonte": item.source,
                "Fórmula ou limite": item.formula or item.note or "",
            }
            for item in report.evidence
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
        with st.expander("Contexto técnico completo"):
            st.json(report.technical_analysis)

    if report.data_quality.missing or report.metrics.source_notes:
        with st.expander("O que falta para aumentar a precisão", expanded=report.data_quality.level == "BAIXA"):
            if report.data_quality.missing:
                st.write("**Dados ausentes:** " + ", ".join(report.data_quality.missing))
            for limitation in report.data_quality.limitations:
                st.write(f"• {limitation}")
            for note in report.metrics.source_notes:
                st.write(f"• {note}")
            if report.benchmark.comparable_posts < 5:
                st.write("• Envie ou autorize pelo menos 10 posts do mesmo formato e estágio de vida.")

    if strategy.caveats:
        with st.expander("Limites metodológicos do diagnóstico"):
            for caveat in strategy.caveats:
                st.write(f"• {caveat}")

    d1, d2 = st.columns(2)
    d1.download_button(
        "Baixar relatório completo (.json)",
        report_json(report),
        file_name=f"{report.report_id}.json",
        mime="application/json",
        width="stretch",
    )
    d2.download_button(
        "Baixar relatório para leitura (.md)",
        report_markdown(report),
        file_name=f"{report.report_id}.md",
        mime="text/markdown",
        width="stretch",
    )

    if report.provider_errors:
        with st.expander("Diagnóstico técnico da recuperação"):
            st.write("A análise foi preservada. Estas rotas precisaram de recuperação:")
            for error in report.provider_errors:
                st.code(error)


st.markdown(
    """
    <div class="vi-hero">
      <span class="vi-chip">EVIDENCE-FIRST</span><span class="vi-chip">DISTRIBUTION FORENSICS</span>
      <h1>Viral Intel</h1>
      <p>Investigue a peça, a resposta do público, os comentários, a conta e a trajetória provável de distribuição — sem fingir acesso ao código interno do Instagram.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Estado do sistema")
    st.write(("●" if settings.google_api_key else "○") + " Gemini: " + ("configurada" if settings.google_api_key else "sem chave"))
    st.write(("●" if shutil.which("ffmpeg") else "○") + " FFmpeg: " + ("disponível" if shutil.which("ffmpeg") else "indisponível"))
    st.write(("●" if settings.instagram_access_token else "○") + " Instagram API: " + ("configurada" if settings.instagram_access_token else "opcional"))
    st.write("● Motor de evidências: ativo")
    st.caption("Chaves e tokens nunca são exibidos nem gravados no relatório.")
    st.divider()
    st.markdown("### Regra central")
    st.write("Dado ausente não vira zero. Hipótese não vira causa comprovada.")
    st.caption("A API não fornece a lista de pessoas que curtiram, salvaram ou compartilharam.")

analysis_tab, profile_tab, method_tab = st.tabs(["Analisar conteúdo", "Histórico do perfil", "Como funciona"])

with analysis_tab:
    st.write(
        "A análise mais profunda combina mídia original, Insights autorizados, comentários e histórico do próprio perfil."
    )
    with st.form("analysis_form"):
        a, b = st.columns(2)
        platform_label = a.selectbox("Plataforma", ["Instagram", "TikTok", "YouTube", "Threads"])
        format_label = b.selectbox(
            "Formato",
            ["Detectar automaticamente", "Reel", "Short", "Vídeo", "Carrossel", "Imagem", "Texto"],
        )
        uploads = st.file_uploader(
            "Vídeo, imagem, captura ou slides",
            type=["mp4", "mov", "m4v", "webm", "mkv", "jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help="Para carrossel, envie os slides na ordem. Para vídeo, prefira o original.",
        )
        url = st.text_input("Link público (opcional)", placeholder="https://www.instagram.com/p/...")
        niche = st.text_area(
            "Nicho, público e objetivo",
            placeholder="Ex.: autismo para pais; objetivo: compartilhamentos, autoridade e seguidores.",
            height=90,
        )

        with st.expander("Acesso autorizado à conta profissional do Instagram"):
            st.caption(
                "Use apenas uma conta profissional que você administra. O token é usado nesta execução e não entra no relatório."
            )
            api1, api2 = st.columns(2)
            instagram_media_id = api1.text_input("ID oficial da mídia (opcional)")
            instagram_user_id = api2.text_input("ID da conta profissional (opcional)")
            instagram_access_token = st.text_input(
                "Token de acesso da Meta (opcional)",
                type="password",
                placeholder="Deixe vazio se já estiver configurado nos Secrets",
            )
            include_instagram_history = st.checkbox(
                "Carregar publicações recentes autorizadas para criar o benchmark"
            )

        comments_file = st.file_uploader(
            "Comentários exportados em CSV ou JSON (opcional)",
            type=["csv", "json"],
            help="Campos aceitos: author/username, text/comment, likes e timestamp.",
        )
        profile_file = st.file_uploader(
            "Histórico do perfil em CSV (recomendado)",
            type=["csv"],
            help="Use pelo menos 10 posts comparáveis ou autorize o histórico pela API.",
        )

        with st.expander("Contexto, elegibilidade e métricas do Insights"):
            m1, m2, m3 = st.columns(3)
            topic = m1.text_input("Tema/pilar", placeholder="Ex.: término e superação")
            hook_type = m2.text_input("Tipo de gancho", placeholder="Ex.: virada emocional")
            cta_type = m3.text_input("Objetivo do CTA", placeholder="Ex.: compartilhar")
            eligibility_label = st.selectbox(
                "Elegibilidade informada no Status da Conta",
                ["Não informado", "Elegível para recomendações", "Não elegível"],
            )
            originality_label = st.selectbox(
                "Originalidade da publicação",
                ["Não informado", "Conteúdo original", "Conteúdo republicado/não original"],
            )
            is_paid = st.checkbox("Teve impulsionamento ou mídia paga")
            age_hours = optional_number("Horas desde a publicação", "v3_age_hours")

            r1 = st.columns(4)
            with r1[0]:
                followers = optional_number("Seguidores", "v3_followers")
                views = optional_number("Visualizações", "v3_views")
                reach = optional_number("Alcance", "v3_reach")
                impressions = optional_number("Impressões", "v3_impressions")
            with r1[1]:
                likes = optional_number("Curtidas", "v3_likes")
                comments = optional_number("Comentários", "v3_comments")
                shares = optional_number("Compartilhamentos/envios", "v3_shares")
                reposts = optional_number("Reposts", "v3_reposts")
            with r1[2]:
                saves = optional_number("Salvamentos", "v3_saves")
                follows = optional_number("Novos seguidores", "v3_follows")
                profile_visits = optional_number("Visitas ao perfil", "v3_profile_visits")
                accounts_engaged = optional_number("Contas engajadas", "v3_accounts_engaged")
            with r1[3]:
                avg_watch = optional_number("Tempo médio assistido (s)", "v3_avg_watch")
                completion = optional_number("Conclusão (%)", "v3_completion")
                retention = optional_number("Retenção em 3s (%)", "v3_retention")
                nonfollowers = optional_number("Não seguidores (%)", "v3_nonfollowers")

            with st.expander("Origem da distribuição e métricas avançadas"):
                d1, d2, d3 = st.columns(3)
                with d1:
                    followers_reach = optional_number("Seguidores alcançados", "v3_followers_reach")
                    nonfollowers_reach = optional_number("Não seguidores alcançados", "v3_nonfollowers_reach")
                    replays = optional_number("Replays", "v3_replays")
                with d2:
                    home_impressions = optional_number("Impressões no Feed/Home", "v3_home_impressions")
                    explore_impressions = optional_number("Impressões no Explorar", "v3_explore_impressions")
                    profile_impressions = optional_number("Impressões pelo perfil", "v3_profile_impressions")
                with d3:
                    hashtag_impressions = optional_number("Impressões por hashtags", "v3_hashtag_impressions")
                    skip_rate = optional_number("Taxa de avanço/skip (%)", "v3_skip_rate")
                    profile_activity = optional_number("Atividade no perfil", "v3_profile_activity")

        submitted = st.form_submit_button("Investigar agora", type="primary", width="stretch")

    platform_map = {
        "Instagram": Platform.INSTAGRAM.value,
        "TikTok": Platform.TIKTOK.value,
        "YouTube": Platform.YOUTUBE.value,
        "Threads": Platform.THREADS.value,
    }
    format_map = {
        "Detectar automaticamente": None,
        "Reel": "reel",
        "Short": "short",
        "Vídeo": "video",
        "Carrossel": "carousel",
        "Imagem": "image",
        "Texto": "text",
    }
    eligibility_map = {
        "Não informado": "unknown",
        "Elegível para recomendações": "eligible",
        "Não elegível": "not_eligible",
    }
    originality_map = {
        "Não informado": None,
        "Conteúdo original": True,
        "Conteúdo republicado/não original": False,
    }

    if submitted:
        st.session_state.pop("latest_report_v3", None)
        selected_format = format_map[format_label]
        if selected_format is None and not uploads:
            selected_format = guess_format_from_url(url)
        warning = format_warning([item.name for item in (uploads or [])], selected_format)
        has_official_input = bool(
            instagram_media_id.strip()
            or instagram_access_token.strip()
            or settings.instagram_access_token
        )
        if warning and "mistura" in warning:
            st.error(warning)
        elif not uploads and not url.strip() and not has_official_input:
            st.error("Envie uma mídia, informe um link ou configure o acesso oficial à publicação.")
        else:
            if warning:
                st.warning(warning)
            paths: list[Path] = []
            report: AnalysisEnvelope | None = None
            try:
                paths = persist_uploads(list(uploads or []))
                history = profile_posts_from_csv(profile_file.getvalue()) if profile_file else []
                manual_comments = (
                    comments_from_file(comments_file.getvalue(), comments_file.name)
                    if comments_file
                    else []
                )
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
                    "is_original": originality_map[originality_label],
                    "recommendation_eligibility": eligibility_map[eligibility_label],
                    "followers": followers,
                    "views": views,
                    "reach": reach,
                    "impressions": impressions,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "saves": saves,
                    "reposts": reposts,
                    "follows": follows,
                    "profile_visits": profile_visits,
                    "profile_activity": profile_activity,
                    "accounts_engaged": accounts_engaged,
                    "followers_reach": followers_reach,
                    "non_followers_reach": nonfollowers_reach,
                    "home_impressions": home_impressions,
                    "explore_impressions": explore_impressions,
                    "profile_impressions": profile_impressions,
                    "hashtag_impressions": hashtag_impressions,
                    "average_watch_time_seconds": avg_watch,
                    "completion_rate": completion,
                    "retention_3s_rate": retention,
                    "non_follower_reach_rate": nonfollowers,
                    "replays": replays,
                    "skip_rate": skip_rate,
                }
                with st.spinner("Investigando mídia, público, conta, baseline e trajetória de distribuição..."):
                    report = analyze_content(
                        media_paths=paths,
                        platform=platform_map[platform_label],
                        content_format=selected_format,
                        manual_metrics=manual,
                        profile_history=history,
                        url=url,
                        niche=niche,
                        settings=settings,
                        inspector=cached_inspector(),
                        instagram_media_id=instagram_media_id,
                        instagram_access_token=instagram_access_token,
                        instagram_user_id=instagram_user_id,
                        include_instagram_history=include_instagram_history,
                        manual_comments=manual_comments,
                    )
                st.session_state["latest_report_v3"] = report.model_dump(mode="json")
            except Exception as exc:
                st.error(f"Não foi possível concluir a análise: {type(exc).__name__}: {exc}")
                with st.expander("Detalhes técnicos"):
                    st.exception(exc)
            finally:
                if settings.ephemeral_mode:
                    cleanup_runtime(paths, report.report_id if report else None)

    if st.session_state.get("latest_report_v3"):
        render_report(AnalysisEnvelope.model_validate(st.session_state["latest_report_v3"]))

with profile_tab:
    st.subheader("Auditoria do histórico")
    st.write("O baseline precisa respeitar plataforma, formato e estágio de vida do post.")
    audit_file = st.file_uploader("Envie o CSV do histórico", type=["csv"], key="v3_profile_audit")
    if audit_file:
        try:
            posts = profile_posts_from_csv(audit_file.getvalue())
            summary = summarize_profile(posts)
            st.success(f"{len(posts)} posts válidos carregados.")
            groups: dict[tuple[str, str], list[Any]] = {}
            for post in posts:
                groups.setdefault((post.platform.value, post.format.value), []).append(post)
            rows = []
            for (platform_name, format_name), group in sorted(groups.items()):
                views_values = [post.views for post in group if post.views is not None]
                reach_values = [post.reach for post in group if post.reach is not None]
                rows.append(
                    {
                        "Plataforma": platform_name,
                        "Formato": format_name,
                        "Posts": len(group),
                        "Mediana de views": statistics.median(views_values) if views_values else None,
                        "Mediana de alcance": statistics.median(reach_values) if reach_values else None,
                    }
                )
            st.dataframe(rows, width="stretch", hide_index=True)
            t1, t2, t3, t4 = st.tabs(["Temas", "Ganchos", "CTAs", "Top posts"])
            with t1:
                st.dataframe(summary.get("topics") or [], width="stretch", hide_index=True)
            with t2:
                st.dataframe(summary.get("hook_types") or [], width="stretch", hide_index=True)
            with t3:
                st.dataframe(summary.get("cta_types") or [], width="stretch", hide_index=True)
            with t4:
                st.dataframe(summary.get("top_posts_by_views") or [], width="stretch", hide_index=True)
        except Exception as exc:
            st.error(str(exc))

    template = (
        "platform,format,post_id,published_at,captured_at,followers,views,reach,impressions,likes,comments,shares,saves,reposts,follows,profile_visits,accounts_engaged,duration_seconds,average_watch_time_seconds,completion_rate,retention_3s_rate,non_follower_reach_rate,topic,hook_type,cta_type,is_paid\n"
        "instagram,reel,exemplo-01,2026-08-01T18:30:00-03:00,2026-08-02T18:30:00-03:00,14000,32000,25000,36000,1800,90,740,520,80,120,310,1600,25,14.2,38,72,64,autismo,erro_comum,compartilhar,false\n"
    )
    st.download_button("Baixar modelo de CSV", template, "historico_perfil_modelo.csv", "text/csv")

with method_tab:
    st.subheader("Como a investigação funciona")
    left, middle, right = st.columns(3)
    with left:
        st.markdown("#### 1. Peça")
        st.write("Gancho, promessa, emoção, texto, visual, áudio, ritmo e CTA observáveis.")
    with middle:
        st.markdown("#### 2. Público e conta")
        st.write("Comentários disponíveis, histórico da conta, baseline e conversão.")
    with right:
        st.markdown("#### 3. Distribuição")
        st.write("Elegibilidade, resposta inicial, circulação, não seguidores e superfícies de descoberta.")

    st.warning(
        "O Instagram não fornece ao aplicativo o peso exato dos sinais, o score de cada pessoa nem a identidade de quem compartilhou, salvou ou curtiu."
    )
    st.info(
        "A investigação mais forte combina conta profissional autorizada, Insights, comentários, arquivo original e pelo menos 10 posts comparáveis."
    )
