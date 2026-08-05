"""Production entrypoint for Streamlit Community Cloud."""

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

os.environ.setdefault("ENABLE_TRANSCRIPTION", "false")
os.environ.setdefault("EPHEMERAL_MODE", "true")
os.environ.setdefault("MAX_UPLOAD_MB", "100")
os.environ.setdefault("COMMAND_TIMEOUT_SECONDS", "120")
os.environ.setdefault("AI_PROVIDER", "auto")

try:
    from app.runtime_guardrails import install_production_guardrails

    install_production_guardrails()
    runpy.run_path(str(ROOT / "app" / "ui" / "dashboard_v3.py"), run_name="__main__")
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
