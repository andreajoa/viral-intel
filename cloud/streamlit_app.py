"""Unified production bootstrap for Viral Intel 5.

Streamlit Community Cloud uses conservative ephemeral defaults. The local launcher sets
``VIRAL_INTEL_EXECUTION=local`` so `.env` and the normal Settings defaults remain
authoritative while the exact same bootstrap and guardrails are exercised.
"""

from __future__ import annotations

import os
import runpy
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

is_local_execution = os.getenv("VIRAL_INTEL_EXECUTION", "").strip().lower() == "local"
if not is_local_execution:
    # Community Cloud storage is ephemeral. Persistent longitudinal intelligence should
    # use an external durable backend before being enabled in hosted production.
    os.environ.setdefault("ENABLE_TRANSCRIPTION", "false")
    os.environ.setdefault("EPHEMERAL_MODE", "true")
    os.environ.setdefault("ENABLE_PERSISTENCE", "false")
    os.environ.setdefault("MAX_UPLOAD_MB", "100")
    os.environ.setdefault("COMMAND_TIMEOUT_SECONDS", "120")
    os.environ.setdefault("AI_PROVIDER", "auto")

try:
    from app.evidence_ingestion_guardrails import install_evidence_ingestion_guardrails
    from app.instagram_fallback_guardrails import install_instagram_fallback_guardrails
    from app.link_content_guardrails import install_link_content_guardrails
    from app.runtime_guardrails import install_production_guardrails

    install_production_guardrails()
    install_link_content_guardrails()
    install_instagram_fallback_guardrails()
    install_evidence_ingestion_guardrails()
    runpy.run_path(str(ROOT / "app" / "ui" / "dashboard_v5.py"), run_name="__main__")
except Exception as exc:
    import streamlit as st

    st.error(
        "O Viral Intel encontrou uma falha de inicialização, mas o painel de diagnóstico permaneceu ativo."
    )
    st.write(f"**Erro:** {type(exc).__name__}: {exc}")
    st.info(
        "Confirme se o arquivo principal do app é `cloud/streamlit_app.py`, se o Python é 3.12 "
        "e se `GOOGLE_API_KEY` foi cadastrado nos Secrets do Streamlit."
    )
    with st.expander("Detalhes técnicos"):
        st.code(traceback.format_exc())
