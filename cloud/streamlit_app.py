"""Unified production bootstrap for the link-only Viral Intel laboratory."""

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
    # Native Gemini video inspection handles audio/temporal understanding in cloud;
    # local Whisper remains an optional fallback rather than a deployment requirement.
    os.environ.setdefault("ENABLE_TRANSCRIPTION", "false")
    os.environ.setdefault("EPHEMERAL_MODE", "true")
    remote_memory = bool(
        os.getenv("CLOUDFLARE_MEMORY_URL", "").strip()
        and os.getenv("CLOUDFLARE_MEMORY_SECRET", "").strip()
    )
    os.environ.setdefault("ENABLE_PERSISTENCE", "true" if remote_memory else "false")
    os.environ.setdefault("MAX_UPLOAD_MB", "100")
    os.environ.setdefault("COMMAND_TIMEOUT_SECONDS", "120")
    os.environ.setdefault("AUTO_DOWNLOAD_PUBLIC_MEDIA", "true")
    os.environ.setdefault("PUBLIC_CREATOR_HISTORY_LIMIT", "30")
    os.environ.setdefault("MAX_PUBLIC_MEDIA_MB", "200")
    os.environ.setdefault("AI_PROVIDER", "auto")

try:
    runpy.run_path(str(ROOT / "app" / "ui" / "dashboard_link_only.py"), run_name="__main__")
except Exception as exc:
    import streamlit as st

    st.error(
        "O Viral Intel encontrou uma falha de inicialização, mas o painel de diagnóstico permaneceu ativo."
    )
    st.write(f"**Erro:** {type(exc).__name__}: {exc}")
    st.info(
        "Confirme `cloud/streamlit_app.py`, Python 3.12 e pelo menos uma chave de IA válida. "
        "Para scraping robusto de Instagram público, configure APIFY_API_TOKEN. "
        "Para memória durável, configure CLOUDFLARE_MEMORY_URL e CLOUDFLARE_MEMORY_SECRET."
    )
    with st.expander("Detalhes técnicos"):
        st.code(traceback.format_exc())
