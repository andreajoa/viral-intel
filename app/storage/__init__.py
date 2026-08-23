"""Persistent longitudinal intelligence backends for Viral Intel."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.storage.intelligence_store import IntelligenceStore as SQLiteIntelligenceStore
from app.storage.remote_store import RemoteIntelligenceStore


def create_intelligence_store(settings: Settings, path: str | Path | None = None) -> Any:
    """Return the configured durable backend using one stable analysis contract."""

    if settings.remote_persistence_configured:
        return RemoteIntelligenceStore(
            settings.cloudflare_memory_url,
            settings.cloudflare_memory_secret,
            timeout=settings.cloudflare_memory_timeout_seconds,
        )
    return SQLiteIntelligenceStore(path or settings.intelligence_db)


class IntelligenceStore:
    """Backward-compatible facade used by the existing pipeline."""

    def __new__(cls, path: str | Path) -> Any:
        return create_intelligence_store(get_settings(), path)


__all__ = [
    "IntelligenceStore",
    "SQLiteIntelligenceStore",
    "RemoteIntelligenceStore",
    "create_intelligence_store",
]
