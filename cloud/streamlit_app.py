"""Unified production bootstrap for the link-only Viral Intel laboratory."""

from __future__ import annotations

import importlib
import os
import runpy
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_EXPECTED_SETTINGS_FIELDS = {
    "auto_download_public_media",
    "cloudflare_memory_url",
    "apify_api_token",
}


def _purge_stale_app_modules() -> bool:
    """Reload app modules when Streamlit hot-reload keeps an older Settings class alive."""

    cached_config = sys.modules.get("app.config")
    if cached_config is None:
        return False

    settings_type = getattr(cached_config, "Settings", None)
    dataclass_fields = getattr(settings_type, "__dataclass_fields__", {})
    if _EXPECTED_SETTINGS_FIELDS.issubset(dataclass_fields):
        return False

    for module_name in tuple(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)
    importlib.invalidate_caches()
    return True


def _refresh_settings_cache() -> None:
    """Force settings to reread environment/secrets on every Streamlit rerun."""

    try:
        from app.config import get_settings
    except Exception:
        return
    get_settings.cache_clear()


_purge_stale_app_modules()

is_local_execution = os.getenv("VIRAL_INTEL_EXECUTION", "").strip().lower() == "local"
if not is_local_execution:
    # Native Gemini video inspection handles audio/temporal understanding in cloud;
    # local Whisper remains an optional fallback rather than a deployment requirement.
    os.environ.setdefault("ENABLE_TRANSCRIPTION", "false")
    os.environ.setdefault("EPHEMERAL_MODE", "true")
    remote_memory = bool(
        os.getenv("CLOUDFLARE_MEMORY_URL", "").strip() and os.getenv("CLOUDFLARE_MEMORY_SECRET", "").strip()
    )
    # This must be recomputed on every rerun. Streamlit can update Secrets without
    # replacing the Python process, so setdefault would preserve a stale false value.
    os.environ["ENABLE_PERSISTENCE"] = "true" if remote_memory else "false"
    os.environ.setdefault("MAX_UPLOAD_MB", "100")
    os.environ.setdefault("COMMAND_TIMEOUT_SECONDS", "120")
    os.environ.setdefault("AUTO_DOWNLOAD_PUBLIC_MEDIA", "true")
    os.environ.setdefault("PUBLIC_CREATOR_HISTORY_LIMIT", "30")
    os.environ.setdefault("MAX_PUBLIC_MEDIA_MB", "200")
    os.environ.setdefault("AI_PROVIDER", "auto")

_refresh_settings_cache()

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
