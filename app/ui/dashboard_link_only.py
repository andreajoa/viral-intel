"""Link-only Viral Intel dashboard for reverse engineering public viral posts."""

from __future__ import annotations

import json
import shutil
from typing import Any

import streamlit as st

from app.config import get_settings
from app.media.inspector import MediaInspector
from app.models import AnalysisEnvelope
from app.pipeline.public_link import analyze_public_link
from app.reporting.exporter import report_json, report_markdown

settings = get_settings()

st.set_page_config(
    page_title="Viral Intel — Laboratório Viral",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --navy:#09274B; --terra:#A64B2A; --sand:#F3DED0; --cream:#FFF8F3; --ink:#16263A; }
    .stApp { background:linear-gradient(180deg,#fff8f3 0%,#fff 32%); }
    [data-testid="stSidebar"] { background:#09274B; }
    [data-testid="stSidebar"] * { color:#FFF8F3; }
    h1,h2,h3 { color:#09274B; letter-spacing:-.025em; }
    .vi-hero { padding:1.55rem 1.7rem; border-radius:24px; background:linear-gradient(135deg,#09274B,#123f70);
      color:#FFF8F3; box-shadow:0 20px 50px rgba(9,39,75,.18); margin-bottom:1rem; }
    .vi-hero h1 { color:#FFF8F3; margin:0; font-size:clamp(2rem,5vw,3rem); }
    .vi-hero p { color:#F3DED0; margin:.55rem 0 0; max-width:1040px; }
    .vi-chip { display:inline-block; padding:.2rem .55rem; border-radius:999px; background:#F3DED0;
      color:#09274B; font-weight:700; font-size:.78rem; margin-right:.3rem; }
    .vi-card { padding:1rem 1.1rem; border-radius:16px; background:#fff; border:1px solid #eadfd9; margin:.5rem 0; }
    .vi-proof { border-left:5px solid #A64B2A; }
    .vi-muted { color:#5f6d7d; font-size:.92rem; }
    div.stButton > button[kind="primary"], div.stDownloadButton > button[kind="primary"] {
      background:#A64B2A; border-color:#A64B2A; color:#fff; border-radius:12px; font-weight:750; }
    div[data-testid="stTextInput"] input { border-radius:12px; }
    @media (max-width:720px) { .vi-hero { padding:1.15rem; border-radius:18px; } }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def cached_inspector() -> MediaInspector:
    return MediaInspector(settings=settings)


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "Indisponível"
    if isinstance(value, float):
        if value.is_integer():
            text = f"{int(value):,}"
        else:
            text = f"{value:,.2f}"
    elif isinstance(value, int):
        text = f"{value:,}"
    else:
        return str(value)
    return text.replace(",", ".") + suffix


def _status_label(status: str) -> str:
    return {
        "BREAKOUT_FORTE": "Breakout forte",
        "BREAKOUT": "Breakout",
        "ACIMA_DO_PADRÃO": "Acima do padrão",
        "DENTRO_DO_PADRÃO": "Dentro do padrão",
        "ABAIXO_DO_PADRÃO": "Abaixo do padrão",
        "INCONCLUSIVO": "Inconclusivo",
    }.get(status, status.replace("_", " ").title())


def _render_collection(report: AnalysisEnvelope) -> None:
    auto = report.technical_analysis.get("auto_collection") or {}
    st.subheader("1. O que foi extraído automaticamente")
    score = auto.get("coverage_score")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cobertura automática", _fmt(score, "%") if score is not None else "Indisponível")
    c2.metric("Arquivos de mídia", auto.get("media_files", 0))
    c3.metric("Comentários coletados", auto.get("comments", 0))
    c4.metric("Posts do criador", auto.get("creator_history", 0))

    signals = auto.get("signals") or {}
    labels = {
        "metadata": "metadados públicos",
        "media": "mídia original",
        "creator_history": "histórico do criador",
        "comments": "comentários",
        "views": "views",
        "likes": "likes",
    }
    if signals:
        st.write(
            " · ".join(("✓" if value else "○") + " " + labels.get(key, key) for key, value in signals.items())
        )
    source = report.technical_analysis.get("public_collection_source")
    if source:
        st.caption(f"Fonte principal desta coleta: {source}")


def _render_breakout(report: AnalysisEnvelope) -> None:
    baseline = report.technical_analysis.get("public_creator_baseline") or {}
    st.subheader("2. É realmente um breakout?")
    a, b, c, d = st.columns(4)
    a.metric("Veredito", _status_label(str(baseline.get("status") or "INCONCLUSIVO")))
    b.metric("Amostra do criador", baseline.get("sample_size", 0))
    multiple = baseline.get("breakout_multiple")
    b_multiple = f"{multiple:.2f}×" if isinstance(multiple, (int, float)) else "Indisponível"
    c.metric("Vs. mediana do criador", b_multiple)
    percentile = baseline.get("percentile")
    d.metric(
        "Percentil público", f"{percentile:.1f}" if isinstance(percentile, (int, float)) else "Indisponível"
    )

    if baseline.get("available"):
        st.markdown(
            f"<div class='vi-card vi-proof'><strong>Prova pública de breakout:</strong> "
            f"o post registrou {_fmt(baseline.get('target_value'))} em {baseline.get('metric')}, "
            f"contra mediana de {_fmt(baseline.get('median_value'))} nos posts comparáveis coletados.</div>",
            unsafe_allow_html=True,
        )
    else:
        st.warning(
            "Ainda não foi possível provar o breakout contra o histórico do criador. A análise criativa continua, mas esse ponto fica inconclusivo."
        )


def _render_viral_dna(report: AnalysisEnvelope) -> None:
    dna = report.technical_analysis.get("viral_dna") or {}
    st.subheader("3. DNA do viral: por que este post provavelmente funcionou")
    st.caption(
        "O Viral Intel separa mecanismo observado de causalidade. Ele não afirma conhecer o algoritmo ou métricas privadas do concorrente."
    )

    proof = dna.get("public_proof") or []
    if proof:
        with st.container(border=True):
            st.markdown("#### Evidência pública de desempenho")
            for item in proof:
                st.write(f"• {item}")

    mechanics = dna.get("mechanics") or []
    if not mechanics:
        st.info("A mídia ou os sinais criativos não ficaram disponíveis o suficiente para decompor o post.")
    for item in mechanics:
        with st.container(border=True):
            st.markdown(f"#### {item.get('mechanism', 'Mecanismo')}")
            observed = item.get("observed")
            if isinstance(observed, list):
                for value in observed:
                    st.write(f"• {value}")
            elif observed:
                st.write(observed)
            if item.get("why_it_can_help"):
                st.write("**Por que pode ajudar:** " + str(item["why_it_can_help"]))
            if item.get("causality"):
                st.caption("Nível da afirmação: " + str(item["causality"]))


def _render_piece(report: AnalysisEnvelope) -> None:
    technical = report.technical_analysis
    st.subheader("4. Anatomia da peça")
    summary = technical.get("creative_content_summary")
    if summary:
        st.write(summary)
    left, right = st.columns(2)
    with left:
        st.markdown("#### Gancho")
        st.write(technical.get("creative_primary_hook") or "Não identificado")
        for item in technical.get("creative_hook_mechanisms") or []:
            st.write(f"• {item}")
        st.markdown("#### Promessa ao público")
        st.write(technical.get("creative_audience_promise") or "Não identificada")
    with right:
        st.markdown("#### Emoção e tensão")
        for item in technical.get("creative_emotional_triggers") or []:
            st.write(f"• {item}")
        if technical.get("creative_curiosity_or_tension"):
            st.write(technical["creative_curiosity_or_tension"])
        st.markdown("#### CTA observado")
        st.write(technical.get("creative_cta_observed") or "Não identificado")

    progression = technical.get("creative_sequence_or_progression") or []
    if progression:
        st.markdown("#### Sequência temporal/visual")
        for index, item in enumerate(progression, 1):
            st.write(f"{index}. {item}")


def _render_comments(report: AnalysisEnvelope) -> None:
    comments = report.technical_analysis.get("comment_intelligence") or {}
    st.subheader("5. O que os comentários revelam")
    if not comments.get("available"):
        st.info(comments.get("coverage_note") or "Nenhuma amostra pública de comentários foi obtida.")
        return
    a, b, c = st.columns(3)
    a.metric("Amostra", comments.get("sample_size", 0))
    b.metric("Com marcações", _fmt(comments.get("mention_rate_pct"), "%"))
    c.metric("Com perguntas", _fmt(comments.get("question_rate_pct"), "%"))
    intents = comments.get("intent_distribution") or []
    if intents:
        st.dataframe(intents, width="stretch", hide_index=True)
    terms = comments.get("top_terms") or []
    if terms:
        st.markdown("#### Termos recorrentes")
        st.dataframe(terms, width="stretch", hide_index=True)


def _render_blueprint(report: AnalysisEnvelope) -> None:
    blueprint = report.technical_analysis.get("replication_blueprint") or {}
    st.subheader("6. Blueprint para criar uma versão sua")
    st.warning(
        "A meta é reproduzir a mecânica de atenção e engajamento, não copiar texto, cenas, identidade ou propriedade criativa do autor original."
    )
    left, right = st.columns(2)
    with left:
        st.markdown("#### Preservar como mecanismo")
        for item in blueprint.get("preserve") or []:
            st.write(f"• {item}")
        st.markdown("#### Ganchos para adaptar")
        for item in blueprint.get("hook_options") or []:
            st.write(f"• {item}")
    with right:
        st.markdown("#### Alterar para ficar original")
        for item in blueprint.get("change") or []:
            st.write(f"• {item}")
        st.markdown("#### CTA")
        st.write(blueprint.get("cta") or "Não definido")

    structure = blueprint.get("structure") or []
    if structure:
        st.markdown("#### Estrutura recomendada")
        for index, item in enumerate(structure, 1):
            st.write(f"{index}. {item}")

    st.markdown("### Prompt pronto para enviar a uma IA")
    prompt = str(blueprint.get("ai_prompt") or "")
    if prompt:
        st.code(prompt, language=None)
    else:
        st.info("O prompt de recriação não pôde ser gerado nesta análise.")


def _render_evidence(report: AnalysisEnvelope) -> None:
    with st.expander("Evidências, limitações e dados técnicos"):
        rows = [
            {
                "Tipo": item.kind,
                "Evidência": item.label,
                "Valor": json.dumps(item.value, ensure_ascii=False, default=str)
                if isinstance(item.value, (dict, list))
                else item.value,
                "Fonte": item.source,
            }
            for item in report.evidence
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
        unavailable = report.technical_analysis.get("third_party_private_metrics_unavailable") or []
        if unavailable:
            st.write(
                "**Métricas privadas de terceiros que permanecem indisponíveis:** " + ", ".join(unavailable)
            )
        for limitation in report.data_quality.limitations:
            st.write(f"• {limitation}")
        if report.provider_errors:
            st.markdown("#### Recuperações técnicas")
            for error in report.provider_errors:
                st.code(error)


def render_report(report: AnalysisEnvelope) -> None:
    st.divider()
    _render_collection(report)
    _render_breakout(report)
    _render_viral_dna(report)
    _render_piece(report)
    _render_comments(report)
    _render_blueprint(report)
    _render_evidence(report)

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


st.markdown(
    """
    <div class="vi-hero">
      <span class="vi-chip">LINK-ONLY</span><span class="vi-chip">VIRAL REVERSE ENGINEERING</span><span class="vi-chip">EVIDENCE-FIRST</span>
      <h1>Viral Intel</h1>
      <p>Cole um post viral de outra pessoa. O sistema tenta extrair a mídia, métricas públicas, comentários e histórico do criador; mede o breakout, desmonta a peça e entrega um blueprint original para você recriar a mecânica.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Estado do sistema")
    st.write(
        ("●" if settings.google_api_key else "○")
        + " IA multimodal: "
        + (settings.gemini_model if settings.google_api_key else "sem chave")
    )
    st.write(
        ("●" if shutil.which("ffmpeg") else "○")
        + " FFmpeg: "
        + ("disponível" if shutil.which("ffmpeg") else "indisponível")
    )
    st.write(
        ("●" if settings.apify_api_token else "◐")
        + " Coleta pública: "
        + ("Apify + fallbacks" if settings.apify_api_token else "Embed + yt-dlp")
    )
    st.write(("●" if settings.auto_download_public_media else "○") + " Download automático da mídia")
    st.write(
        ("●" if settings.persistence_active else "○")
        + " Memória longitudinal: "
        + (settings.persistence_backend if settings.persistence_active else "desativada")
    )
    st.divider()
    st.markdown("### Regra central")
    st.write(
        "O sistema copia mecanismos testáveis, não conteúdo autoral. Métrica privada ausente nunca vira estimativa factual."
    )

st.markdown("## Cole o link do post viral")
with st.form("public_viral_link_form"):
    link = st.text_input(
        "Link público",
        placeholder="https://www.instagram.com/reel/...",
        help="Instagram, TikTok, YouTube, Threads ou Facebook. Para Instagram, Apify aumenta muito a robustez da coleta em cloud.",
    )
    adaptation_context = st.text_input(
        "Seu nicho/público para adaptar (opcional)",
        placeholder="Ex.: educação inclusiva para famílias e professores",
    )
    submitted = st.form_submit_button("Descobrir por que viralizou", type="primary", width="stretch")

st.caption(
    "Você não precisa preencher views, likes, comentários, duração ou histórico manualmente. O sistema tenta coletar tudo que for público a partir do link."
)

if submitted:
    try:
        with st.spinner(
            "Extraindo post, mídia, comentários, histórico do criador e desmontando a mecânica viral..."
        ):
            report = analyze_public_link(
                link,
                niche=adaptation_context,
                settings=settings,
                inspector=cached_inspector(),
            )
        st.session_state["latest_public_viral_report"] = report.model_dump(mode="json")
        st.success("Investigação concluída. Abaixo está o DNA público e o blueprint de recriação.")
    except Exception as exc:
        st.error(f"Não foi possível investigar o link automaticamente: {type(exc).__name__}: {exc}")
        st.info(
            "Se for Instagram e isso ocorrer repetidamente, confirme que APIFY_API_TOKEN está configurado nos Secrets do Streamlit."
        )

if st.session_state.get("latest_public_viral_report"):
    render_report(AnalysisEnvelope.model_validate(st.session_state["latest_public_viral_report"]))
