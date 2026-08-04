"""Guided Streamlit interface for Viral Intel production deployments."""

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

from app.ai.schema import StrategicReport
from app.analysis.io import parse_optional_number, profile_posts_from_csv
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
    .vi-hero p { color:#F3DED0; margin:.5rem 0 0; max-width:900px; }
    .vi-chip { display:inline-block; padding:.2rem .55rem; border-radius:999px; background:#F3DED0;
      color:#09274B; font-weight:700; font-size:.78rem; margin-right:.3rem; }
    .vi-card { border:1px solid #ead8cf; border-radius:18px; padding:1rem 1.1rem; background:#fff; }
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
        return (
            "A seleção mistura tipos de mídia ou contém mais de um vídeo. Envie um vídeo ou somente imagens."
        )
    if selected_format in {"reel", "short", "video"} and actual == "image":
        return "Captura estática aceita: a leitura criativa funcionará, mas ritmo, áudio e cortes não poderão ser medidos."
    if selected_format == "carousel" and actual == "image":
        return "Somente a capa será analisada. Para uma leitura completa, envie os slides na ordem correta."
    if selected_format == "image" and actual == "carousel":
        return "Há várias imagens; o sistema poderá reconhecer o material como carrossel."
    return None


def provider_message(report: AnalysisEnvelope) -> None:
    if report.provider == "hybrid":
        st.success("Gemini observou a mídia e o motor de evidências protegeu a conclusão estatística.")
    elif report.provider == "gemini":
        st.success(f"Análise estruturada concluída pela Gemini ({report.model}).")
    elif report.provider == "deterministic" and report.provider_errors:
        st.warning("A IA não respondeu nesta execução. O relatório foi concluído pelo motor de evidências.")
    elif report.provider == "deterministic":
        st.info("Relatório determinístico concluído. Configure a Gemini para acrescentar leitura criativa.")
    else:
        st.success(f"Análise concluída por {report.provider.title()} ({report.model}).")


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
    c2.metric(
        "Qualidade dos dados", f"{report.data_quality.level} · {report.data_quality.completeness_score}/100"
    )
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

    creative = report.technical_analysis.get("creative_content_summary")
    if creative:
        st.markdown("### O que foi realmente observado")
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
        limitations = report.technical_analysis.get("creative_observation_limitations") or []
        if limitations:
            st.caption("Limites da leitura: " + " · ".join(map(str, limitations)))

    tabs = st.tabs(["Causas prováveis", "Próximo conteúdo", "Experimentos", "Evidências"])
    with tabs[0]:
        if not strategy.root_cause_hypotheses:
            st.info("Nenhuma causa foi sustentada pelos dados disponíveis.")
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

    with tabs[2]:
        for index, experiment in enumerate(strategy.experiments, 1):
            with st.container(border=True):
                st.markdown(f"#### Teste {index}: {experiment.hypothesis}")
                st.write(f"**Mude apenas:** {experiment.change_one_thing}")
                st.write(f"**Métrica principal:** {experiment.primary_metric}")
                st.write(f"**Regra de comparação:** {experiment.comparison_rule}")
                st.write(f"**Amostra mínima:** {experiment.minimum_sample}")

    with tabs[3]:
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
        with st.expander("Sinais técnicos da mídia"):
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
            if report.benchmark.comparable_posts < 5:
                st.write(
                    "• Envie um CSV com pelo menos 10 posts do mesmo formato e no mesmo estágio de vida."
                )

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
            st.write(
                "A análise foi preservada. Estes registros mostram as rotas de IA que precisaram de recuperação:"
            )
            for error in report.provider_errors:
                st.code(error)


st.markdown(
    """
    <div class="vi-hero">
      <span class="vi-chip">EVIDENCE-FIRST</span><span class="vi-chip">MULTIMODAL</span>
      <h1>Viral Intel</h1>
      <p>Analise a execução criativa, compare o desempenho com o próprio perfil e transforme hipóteses em testes mensuráveis.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Estado do sistema")
    st.write(
        ("●" if settings.google_api_key else "○")
        + " Gemini: "
        + ("configurada" if settings.google_api_key else "sem chave")
    )
    st.write(
        ("●" if shutil.which("ffmpeg") else "○")
        + " FFmpeg: "
        + ("disponível" if shutil.which("ffmpeg") else "indisponível")
    )
    st.write("● Motor de evidências: ativo")
    st.caption("A chave nunca é exibida nem gravada no relatório.")
    st.divider()
    st.markdown("### Regra central")
    st.write("Dado ausente não vira zero. Hipótese não vira causa comprovada.")

analysis_tab, profile_tab, method_tab = st.tabs(["Analisar conteúdo", "Histórico do perfil", "Como funciona"])

with analysis_tab:
    st.write(
        "Use o arquivo original para a análise mais forte. Capturas e links também são aceitos, com os limites explicitados no relatório."
    )
    with st.form("analysis_form"):
        a, b = st.columns(2)
        platform_label = a.selectbox("Plataforma", ["Instagram", "TikTok", "YouTube", "Threads"])
        format_label = b.selectbox(
            "Formato", ["Detectar automaticamente", "Reel", "Short", "Vídeo", "Carrossel", "Imagem", "Texto"]
        )
        uploads = st.file_uploader(
            "Vídeo, imagem, captura ou slides",
            type=["mp4", "mov", "m4v", "webm", "mkv", "jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            help="Para carrossel, envie os slides na ordem correta. Para vídeo, prefira o arquivo original.",
        )
        url = st.text_input("Link público (opcional)", placeholder="https://www.instagram.com/reel/...")
        niche = st.text_area(
            "Nicho, público e objetivo",
            placeholder="Ex.: autismo e TDAH para pais; objetivo: compartilhamentos e autoridade.",
            height=90,
        )
        profile_file = st.file_uploader(
            "Histórico do perfil em CSV (recomendado)",
            type=["csv"],
            help="Use pelo menos 10 posts comparáveis.",
        )

        with st.expander("Contexto e métricas do Insights"):
            m1, m2, m3 = st.columns(3)
            topic = m1.text_input("Tema/pilar", placeholder="Ex.: sinais do autismo")
            hook_type = m2.text_input("Tipo de gancho", placeholder="Ex.: erro comum")
            cta_type = m3.text_input("Objetivo do CTA", placeholder="Ex.: compartilhar")
            is_paid = st.checkbox("Teve impulsionamento ou mídia paga")
            age_hours = optional_number("Horas desde a publicação", "v3_age_hours")
            r1 = st.columns(4)
            with r1[0]:
                followers = optional_number("Seguidores", "v3_followers")
                views = optional_number("Visualizações", "v3_views")
                reach = optional_number("Alcance", "v3_reach")
            with r1[1]:
                likes = optional_number("Curtidas", "v3_likes")
                comments = optional_number("Comentários", "v3_comments")
                shares = optional_number("Compartilhamentos", "v3_shares")
            with r1[2]:
                saves = optional_number("Salvamentos", "v3_saves")
                reposts = optional_number("Reposts", "v3_reposts")
                follows = optional_number("Novos seguidores", "v3_follows")
            with r1[3]:
                avg_watch = optional_number("Tempo médio assistido (s)", "v3_avg_watch")
                completion = optional_number("Conclusão (%)", "v3_completion")
                retention = optional_number("Retenção em 3s (%)", "v3_retention")
                nonfollowers = optional_number("Não seguidores (%)", "v3_nonfollowers")
        submitted = st.form_submit_button("Analisar agora", type="primary", width="stretch")

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

    if submitted:
        st.session_state.pop("latest_report_v3", None)
        selected_format = format_map[format_label]
        if selected_format is None and not uploads:
            selected_format = guess_format_from_url(url)
        warning = format_warning([item.name for item in (uploads or [])], selected_format)
        if warning and "mistura" in warning:
            st.error(warning)
        elif not uploads and not url.strip():
            st.error("Envie uma mídia ou informe o link público do conteúdo.")
        else:
            if warning:
                st.warning(warning)
            paths: list[Path] = []
            report: AnalysisEnvelope | None = None
            try:
                paths = persist_uploads(list(uploads or []))
                history = profile_posts_from_csv(profile_file.getvalue()) if profile_file else []
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
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "saves": saves,
                    "reposts": reposts,
                    "follows": follows,
                    "average_watch_time_seconds": avg_watch,
                    "completion_rate": completion,
                    "retention_3s_rate": retention,
                    "non_follower_reach_rate": nonfollowers,
                }
                with st.spinner("Observando a mídia, calculando o baseline e validando hipóteses..."):
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

    template = "platform,format,post_id,published_at,captured_at,followers,views,reach,likes,comments,shares,saves,follows,duration_seconds,average_watch_time_seconds,completion_rate,retention_3s_rate,non_follower_reach_rate,topic,hook_type,cta_type,is_paid\ninstagram,reel,exemplo-01,2026-08-01T18:30:00-03:00,2026-08-02T18:30:00-03:00,14000,32000,25000,1800,90,740,520,120,25,14.2,38,72,64,autismo,erro_comum,compartilhar,false\n"
    st.download_button("Baixar modelo de CSV", template, "historico_perfil_modelo.csv", "text/csv")

with method_tab:
    st.subheader("O que esta análise pode afirmar")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Fatos e cálculos")
        st.write(
            "Métricas fornecidas, propriedades técnicas e fórmulas transparentes entram no ledger com IDs próprios."
        )
        st.write("O post é comparado ao histórico compatível do próprio perfil.")
    with right:
        st.markdown("#### Hipóteses testáveis")
        st.write(
            "Gancho, emoção, edição e promessa recebem confiança, limite e dado necessário para confirmação."
        )
        st.write("O sistema não afirma conhecer o código interno do algoritmo.")
    st.info(
        "A análise mais forte combina arquivo original, Insights privados e pelo menos 10 posts comparáveis."
    )
