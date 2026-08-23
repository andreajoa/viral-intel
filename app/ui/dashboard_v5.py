"""Viral Intel 5 production dashboard.

The interface exposes the evidence-first core, robust profile baseline, Content Twins
and longitudinal snapshots while remaining compatible with the existing evidence-package
guardrails used by the production bootstrap.
"""

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
from app.media.inspector import MediaInspector
from app.models import AnalysisEnvelope
from app.pipeline.main import analyze_content
from app.reporting.exporter import report_json, report_markdown

settings = get_settings()

st.set_page_config(
    page_title="Viral Intel 5",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --navy:#09274B; --terra:#A64B2A; --sand:#F3DED0; --cream:#FFF8F3; --ink:#16263A; }
    .stApp { background:linear-gradient(180deg,#fff8f3 0%,#fff 30%); }
    [data-testid="stSidebar"] { background:#09274B; }
    [data-testid="stSidebar"] * { color:#FFF8F3; }
    [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea { color:#09274B; }
    h1,h2,h3 { color:#09274B; letter-spacing:-.025em; }
    .vi-hero { padding:1.55rem 1.7rem; border-radius:24px; background:linear-gradient(135deg,#09274B,#123f70);
      color:#FFF8F3; box-shadow:0 20px 50px rgba(9,39,75,.18); margin-bottom:1rem; }
    .vi-hero h1 { color:#FFF8F3; margin:0; font-size:clamp(2rem,5vw,3rem); }
    .vi-hero p { color:#F3DED0; margin:.5rem 0 0; max-width:1040px; }
    .vi-chip { display:inline-block; padding:.2rem .55rem; border-radius:999px; background:#F3DED0;
      color:#09274B; font-weight:700; font-size:.78rem; margin-right:.3rem; }
    .vi-stage { border-left:5px solid #A64B2A; border-radius:12px; padding:.85rem 1rem; background:#fff;
      border-top:1px solid #eadfd9; border-right:1px solid #eadfd9; border-bottom:1px solid #eadfd9; margin:.65rem 0; }
    .vi-note { padding:.8rem 1rem; border-radius:14px; background:#FFF8F3; border:1px solid #ead8cf; }
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
    if not files:
        return []
    batch_dir = settings.inbox_dir / ("upload_" + uuid.uuid4().hex[:12])
    batch_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for upload in files:
        destination = batch_dir / safe_filename(upload.name)
        destination.write_bytes(upload.getvalue())
        paths.append(destination)
    return paths


def cleanup_runtime(paths: list[Path], report_id: str | None = None) -> None:
    """Uploads and extracted frames are temporary even when local persistence is enabled."""

    inbox = settings.inbox_dir.resolve()
    for directory in {path.resolve().parent for path in paths}:
        if directory.parent == inbox and directory.name.startswith("upload_"):
            shutil.rmtree(directory, ignore_errors=True)
    if report_id:
        shutil.rmtree(settings.temp_dir / report_id, ignore_errors=True)
        if settings.ephemeral_mode:
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


def strength_label(value: str) -> str:
    labels = {
        "FORTE": "Forte",
        "MODERADA": "Moderada",
        "FRACA": "Fraca",
        "NÃO_AVALIÁVEL": "Não avaliável",
    }
    return labels.get(value, value or "Não avaliável")


def provider_message(report: AnalysisEnvelope) -> None:
    native = bool(report.technical_analysis.get("native_video_observation"))
    if native:
        st.success(
            f"Vídeo original analisado temporalmente por {report.model}, com FFmpeg como cross-check técnico."
        )
    elif report.provider == "hybrid":
        st.success("A IA observou a mídia e o motor de evidências protegeu as conclusões estatísticas.")
    elif report.provider == "gemini":
        st.success(f"Análise estruturada concluída pela Gemini ({report.model}).")
    elif report.provider == "deterministic" and report.provider_errors:
        st.warning("A IA não respondeu nesta execução. O relatório foi preservado pelo motor de evidências.")
    elif report.provider == "deterministic":
        st.info("Relatório determinístico concluído. Configure uma IA para aprofundar a leitura criativa.")
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
            if insight.evidence_refs:
                st.caption("Evidências: " + ", ".join(insight.evidence_refs))
            if insight.limitation:
                st.caption("Limite: " + insight.limitation)


def render_benchmark(report: AnalysisEnvelope) -> None:
    benchmark = report.benchmark
    st.markdown("### Baseline robusto do próprio perfil")
    a, b, c, d = st.columns(4)
    a.metric("Classificação", benchmark.status.replace("_", " ").title())
    b.metric("Força da evidência", strength_label(benchmark.evidence_strength))
    c.metric("Percentil", fmt_number(benchmark.percentile, "%"))
    d.metric("Anomalia robusta", fmt_number(benchmark.robust_z_score, " z"))

    if benchmark.expected_low is not None and benchmark.expected_high is not None:
        st.markdown(
            f"<div class='vi-note'><strong>Faixa esperada para {benchmark.primary_metric or 'métrica principal'}:</strong> "
            f"{fmt_number(benchmark.expected_low)} – {fmt_number(benchmark.expected_high)} · "
            f"observado: {fmt_number(benchmark.target_value)}.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.info("Ainda não há amostra suficiente para calcular uma faixa esperada estável.")
    if benchmark.warnings:
        with st.expander("Limitações do baseline"):
            for warning in benchmark.warnings:
                st.write(f"• {warning}")


def render_distribution(report: AnalysisEnvelope) -> None:
    diagnosis = report.technical_analysis.get("distribution_diagnosis") or {}
    if not diagnosis:
        st.info("A trajetória de distribuição não foi calculada nesta execução.")
        return
    if not diagnosis.get("has_distribution_evidence"):
        st.warning(diagnosis.get("verdict") or "Não há evidência suficiente para reconstruir a distribuição.")
    else:
        st.write(diagnosis.get("framework") or "")
    for stage in diagnosis.get("stages") or []:
        st.markdown(
            f"""
            <div class="vi-stage">
              <strong>{stage.get("stage", "Etapa")}</strong><br>
              <small>{stage.get("status", "INCONCLUSIVO")}</small>
              <p>{stage.get("finding", "")}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if stage.get("limitation"):
            st.caption("Limite: " + str(stage["limitation"]))
    path = diagnosis.get("likely_distribution_path") or []
    if path:
        st.markdown("#### Caminho sustentado pelos dados disponíveis")
        for index, item in enumerate(path, 1):
            st.write(f"{index}. {item}")
    with st.expander("O que não pode ser descoberto com os dados atuais"):
        for item in diagnosis.get("cannot_be_known_from_current_data") or []:
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
    st.caption(str(comments.get("coverage_note") or ""))


def render_twins(report: AnalysisEnvelope) -> None:
    st.markdown("### Content Twins")
    st.write(
        "Conteúdos historicamente mais parecidos pela combinação de tema, gancho, emoção, estilo, duração e estrutura. "
        "Similaridade descreve comparabilidade; não prova causalidade."
    )
    if not report.content_twins:
        st.info(
            "A memória ainda não tem conteúdos suficientemente semelhantes. Ela melhora conforme novas análises são salvas."
        )
        return
    rows = []
    for item in report.content_twins:
        metrics = item.get("metrics") or {}
        rows.append(
            {
                "Post": item.get("post_id") or item.get("report_id"),
                "Similaridade": f"{float(item.get('similarity') or 0) * 100:.1f}%",
                "Views": metrics.get("views"),
                "Alcance": metrics.get("reach"),
                "Compartilhamentos": metrics.get("shares"),
                "Salvamentos": metrics.get("saves"),
                "Seguidores ganhos": metrics.get("follows"),
                "Captura": item.get("captured_at"),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)


def render_longitudinal(report: AnalysisEnvelope) -> None:
    st.markdown("### Linha do tempo do post")
    longitudinal = report.longitudinal or {}
    snapshots = int(longitudinal.get("snapshots") or 0)
    st.metric("Snapshots acumulados", snapshots)
    if snapshots < 2:
        st.info(
            "Este é o primeiro snapshot persistido deste post. Analise-o novamente mais tarde para medir a trajetória real."
        )
        return
    deltas = longitudinal.get("deltas") or {}
    if deltas:
        st.dataframe(
            [{"Métrica": key, "Variação desde o primeiro snapshot": value} for key, value in deltas.items()],
            width="stretch",
            hide_index=True,
        )
    timeline_rows = []
    for point in longitudinal.get("timeline") or []:
        metrics = point.get("metrics") or {}
        timeline_rows.append(
            {
                "Capturado em": point.get("captured_at"),
                "Views": metrics.get("views"),
                "Alcance": metrics.get("reach"),
                "Shares": metrics.get("shares"),
                "Saves": metrics.get("saves"),
                "Follows": metrics.get("follows"),
            }
        )
    if timeline_rows:
        st.dataframe(timeline_rows, width="stretch", hide_index=True)


def render_report(report: AnalysisEnvelope) -> None:
    strategy = StrategicReport.model_validate(report.strategy)
    st.divider()
    st.subheader("Diagnóstico final")
    labels = {
        "DADOS_INSUFICIENTES": "Sem baseline suficiente",
        "REPETIR": "Repetir",
        "ITERAR": "Iterar",
        "MUDAR": "Mudar",
    }
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Decisão", labels.get(strategy.repeat_decision, strategy.repeat_decision))
    c2.metric(
        "Qualidade dos dados", f"{report.data_quality.level} · {report.data_quality.completeness_score}/100"
    )
    c3.metric("Posts comparáveis", report.benchmark.comparable_posts)
    c4.metric("Força do baseline", strength_label(report.benchmark.evidence_strength))

    st.markdown(f"### {strategy.executive_summary}")
    st.write(strategy.performance_interpretation)
    provider_message(report)
    st.caption(
        f"Relatório {report.report_id} · schema {report.schema_version} · {report.engine_version} · {report.provider} · {report.model}"
    )

    tabs = st.tabs(
        [
            "Resumo estatístico",
            "Conteúdo",
            "Distribuição",
            "Content Twins",
            "Linha do tempo",
            "Público e comentários",
            "Próximo conteúdo",
            "Evidências",
        ]
    )

    with tabs[0]:
        render_benchmark(report)
        st.markdown("### Hipóteses")
        for hypothesis in strategy.root_cause_hypotheses:
            with st.container(border=True):
                st.markdown(f"#### {hypothesis.title}")
                st.write(hypothesis.finding)
                st.write(f"**Julgamento:** {hypothesis.judgment}")
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
            left, right = st.columns(2)
            left.info(
                "**Gancho observado**\n\n"
                + str(report.technical_analysis.get("creative_primary_hook") or "Não identificado")
            )
            right.info(
                "**CTA observado**\n\n"
                + str(report.technical_analysis.get("creative_cta_observed") or "Não identificado")
            )
            progression = report.technical_analysis.get("creative_sequence_or_progression") or []
            if progression:
                st.markdown("#### Progressão temporal/visual")
                for index, item in enumerate(progression, 1):
                    st.write(f"{index}. {item}")
        render_insights("formato", strategy.format_insights)
        with st.expander("Creative Fingerprint"):
            st.json(report.content_fingerprint)

    with tabs[2]:
        render_distribution(report)

    with tabs[3]:
        render_twins(report)

    with tabs[4]:
        render_longitudinal(report)

    with tabs[5]:
        render_comments(report)
        render_insights("público", strategy.audience_insights)

    with tabs[6]:
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
            st.markdown("#### Estrutura")
            for index, item in enumerate(plan.structure, 1):
                st.write(f"{index}. {item}")
            st.markdown("#### Alterar")
            for item in plan.change:
                st.write(f"• {item}")
        st.info(f"**Direção da legenda:** {plan.caption_direction}\n\n**CTA:** {plan.cta}")
        st.markdown("### Experimentos sugeridos")
        for index, experiment in enumerate(strategy.experiments, 1):
            with st.container(border=True):
                st.markdown(f"#### Teste {index}: {experiment.hypothesis}")
                st.write(f"**Mude apenas:** {experiment.change_one_thing}")
                st.write(f"**Mantenha constante:** {' · '.join(experiment.keep_constant)}")
                st.write(f"**Métrica principal:** {experiment.primary_metric}")
                st.write(f"**Regra:** {experiment.comparison_rule}")
                st.write(f"**Amostra mínima:** {experiment.minimum_sample}")

    with tabs[7]:
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
        with st.expander(
            "O que falta para aumentar a precisão", expanded=report.data_quality.level == "BAIXA"
        ):
            if report.data_quality.missing:
                st.write("**Dados ausentes:** " + ", ".join(report.data_quality.missing))
            for limitation in report.data_quality.limitations:
                st.write(f"• {limitation}")
            for note in report.metrics.source_notes:
                st.write(f"• {note}")

    if strategy.caveats:
        with st.expander("Limites metodológicos"):
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
            for error in report.provider_errors:
                st.code(error)


st.markdown(
    """
    <div class="vi-hero">
      <span class="vi-chip">V5</span><span class="vi-chip">EVIDENCE-FIRST</span><span class="vi-chip">LONGITUDINAL</span>
      <h1>Viral Intel</h1>
      <p>Inteligência de conteúdo baseada no histórico real do perfil: mídia, público, distribuição, faixa esperada, conteúdos gêmeos e evolução temporal — sem fingir acesso aos pesos secretos das plataformas.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Estado do sistema")
    st.write(
        ("●" if settings.google_api_key else "○")
        + " Gemini: "
        + (settings.gemini_model if settings.google_api_key else "sem chave")
    )
    st.write(
        ("●" if shutil.which("ffmpeg") else "○")
        + " FFmpeg: "
        + ("disponível" if shutil.which("ffmpeg") else "indisponível")
    )
    st.write(
        ("●" if settings.instagram_access_token else "○")
        + " Instagram API: "
        + ("configurada" if settings.instagram_access_token else "opcional")
    )
    st.write(
        ("●" if settings.persistence_active else "○")
        + " Memória longitudinal: "
        + ("ativa" if settings.persistence_active else "efêmera/desativada")
    )
    st.write("● Baseline robusto: ativo")
    st.write("● Content Twins: ativo")
    st.caption("Tokens não são gravados no relatório. Dados ausentes nunca viram zero.")
    st.divider()
    st.markdown("### Regra central")
    st.write("Fato, cálculo, comparação e hipótese permanecem separados.")

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
            help="Para vídeo, prefira o arquivo original. Para carrossel, envie todos os slides na ordem.",
        )
        url = st.text_input("Link público (opcional)", placeholder="https://www.instagram.com/p/...")
        niche = st.text_area(
            "Nicho, público e objetivo",
            placeholder="Ex.: educação inclusiva para famílias; objetivo: compartilhamentos, autoridade e seguidores.",
            height=90,
        )
        local_profile_key = st.text_input(
            "Identificador do perfil para memória local (opcional)",
            placeholder="Ex.: neuromargarethapoio",
            help="Para Instagram autenticado ele é detectado automaticamente. Use este campo para TikTok/YouTube ou análises manuais recorrentes.",
        )

        with st.expander("Acesso autorizado à conta profissional do Instagram"):
            api1, api2 = st.columns(2)
            instagram_media_id = api1.text_input("ID oficial da mídia (opcional)")
            instagram_user_id = api2.text_input("ID da conta profissional (opcional)")
            instagram_access_token = st.text_input(
                "Token de acesso da Meta (opcional)",
                type="password",
                placeholder="Deixe vazio se já estiver configurado nos Secrets",
            )
            include_instagram_history = st.checkbox("Carregar histórico recente autorizado")

        comments_file = st.file_uploader(
            "Comentários exportados em CSV ou JSON (opcional)",
            type=["csv", "json"],
            help="Campos aceitos: author/username, text/comment, likes e timestamp.",
        )
        profile_file = st.file_uploader(
            "Histórico do perfil em CSV (opcional)",
            type=["csv"],
            help="A memória longitudinal reduz a necessidade de reenviar este arquivo nas próximas análises.",
        )

        with st.expander("Contexto, elegibilidade e métricas do Insights"):
            m1, m2, m3 = st.columns(3)
            topic = m1.text_input("Tema/pilar", placeholder="Ex.: linguagem")
            hook_type = m2.text_input("Tipo de gancho", placeholder="Ex.: pergunta direta")
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
            age_hours = optional_number("Horas desde a publicação", "v5_age_hours")

            r1 = st.columns(4)
            with r1[0]:
                followers = optional_number("Seguidores", "v5_followers")
                views = optional_number("Visualizações", "v5_views")
                reach = optional_number("Alcance", "v5_reach")
                impressions = optional_number("Impressões", "v5_impressions")
            with r1[1]:
                likes = optional_number("Curtidas", "v5_likes")
                comments = optional_number("Comentários", "v5_comments")
                shares = optional_number("Compartilhamentos/envios", "v5_shares")
                reposts = optional_number("Reposts", "v5_reposts")
            with r1[2]:
                saves = optional_number("Salvamentos", "v5_saves")
                follows = optional_number("Novos seguidores", "v5_follows")
                profile_visits = optional_number("Visitas ao perfil", "v5_profile_visits")
                accounts_engaged = optional_number("Contas engajadas", "v5_accounts_engaged")
            with r1[3]:
                avg_watch = optional_number("Tempo médio assistido (s)", "v5_avg_watch")
                completion = optional_number("Conclusão (%)", "v5_completion")
                retention = optional_number("Retenção em 3s (%)", "v5_retention")
                nonfollowers = optional_number("Não seguidores (%)", "v5_nonfollowers")

            with st.expander("Origem da distribuição e métricas avançadas"):
                d1, d2, d3 = st.columns(3)
                with d1:
                    followers_reach = optional_number("Seguidores alcançados", "v5_followers_reach")
                    nonfollowers_reach = optional_number("Não seguidores alcançados", "v5_nonfollowers_reach")
                    replays = optional_number("Replays", "v5_replays")
                with d2:
                    home_impressions = optional_number("Impressões no Feed/Home", "v5_home_impressions")
                    explore_impressions = optional_number("Impressões no Explorar", "v5_explore_impressions")
                    profile_impressions = optional_number("Impressões pelo perfil", "v5_profile_impressions")
                with d3:
                    hashtag_impressions = optional_number("Impressões por hashtags", "v5_hashtag_impressions")
                    skip_rate = optional_number("Taxa de avanço/skip (%)", "v5_skip_rate")
                    profile_activity = optional_number("Atividade no perfil", "v5_profile_activity")

        submitted = st.form_submit_button("Investigar conteúdo", type="primary", width="stretch")

    if submitted:
        paths: list[Path] = []
        report: AnalysisEnvelope | None = None
        try:
            paths = persist_uploads(list(uploads or []))
            history = profile_posts_from_csv(profile_file.getvalue()) if profile_file else []
            manual_comments = (
                comments_from_file(comments_file.getvalue(), comments_file.name) if comments_file else []
            )
            now = datetime.now(UTC)
            published_at = now - timedelta(hours=float(age_hours)) if age_hours is not None else None
            eligibility = {
                "Não informado": "unknown",
                "Elegível para recomendações": "eligible",
                "Não elegível": "not_eligible",
            }[eligibility_label]
            originality = {
                "Não informado": None,
                "Conteúdo original": True,
                "Conteúdo republicado/não original": False,
            }[originality_label]
            platform_map = {
                "Instagram": "instagram",
                "TikTok": "tiktok",
                "YouTube": "youtube",
                "Threads": "threads",
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
            manual = {
                "captured_at": now,
                "published_at": published_at,
                "topic": topic or None,
                "hook_type": hook_type or None,
                "cta_type": cta_type or None,
                "recommendation_eligibility": eligibility,
                "is_original": originality,
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
            with st.spinner(
                "Investigando mídia, baseline, público, distribuição, Content Twins e trajetória..."
            ):
                report = analyze_content(
                    media_paths=paths,
                    platform=platform_map[platform_label],
                    content_format=format_map[format_label],
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
                    profile_key=local_profile_key,
                )
            st.session_state["latest_report_v5"] = report.model_dump(mode="json")
        except Exception as exc:
            st.error(f"Não foi possível concluir a análise: {type(exc).__name__}: {exc}")
            with st.expander("Detalhes técnicos"):
                st.exception(exc)
        finally:
            cleanup_runtime(paths, report.report_id if report else None)

    if st.session_state.get("latest_report_v5"):
        render_report(AnalysisEnvelope.model_validate(st.session_state["latest_report_v5"]))

with profile_tab:
    st.subheader("Auditoria do histórico")
    st.write(
        "O baseline respeita plataforma, formato e estágio de vida e passa a usar dispersão robusta do próprio perfil."
    )
    audit_file = st.file_uploader("Envie o CSV do histórico", type=["csv"], key="v5_profile_audit")
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
        "instagram,reel,exemplo-01,2026-08-01T18:30:00-03:00,2026-08-02T18:30:00-03:00,14000,32000,25000,36000,1800,90,740,520,80,120,310,1600,25,14.2,38,72,64,autismo,pergunta,compartilhar,false\n"
    )
    st.download_button("Baixar modelo de CSV", template, "historico_perfil_modelo.csv", "text/csv")

with method_tab:
    st.subheader("Como o Viral Intel 5 pensa")
    a, b, c, d = st.columns(4)
    with a:
        st.markdown("#### 1. Evidência")
        st.write("Separa observado, calculado, benchmark e hipótese. Ausência nunca vira zero.")
    with b:
        st.markdown("#### 2. Baseline")
        st.write(
            "Modela a faixa esperada do próprio perfil em vez de usar um limiar universal de viralização."
        )
    with c:
        st.markdown("#### 3. Content Twins")
        st.write("Compara com conteúdos historicamente parecidos, não apenas com todo o formato.")
    with d:
        st.markdown("#### 4. Longitudinal")
        st.write("Acumula snapshots para aprender a trajetória real do post e do perfil.")
    st.info(
        "Vídeos originais podem ser analisados temporalmente por modelo multimodal nativo, enquanto FFmpeg continua medindo duração, cortes, áudio e frames de forma determinística."
    )
    st.warning(
        "Nenhuma API revela os pesos exatos do ranking, o score de cada pessoa ou a identidade individual de quem salvou/compartilhou. O Viral Intel não inventa esses dados."
    )
