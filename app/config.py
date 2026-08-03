"""Central, runtime-safe settings for Viral Intel."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # allows deterministic tests before optional dependencies are installed

    def load_dotenv(*args, **kwargs):
        return False


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


def _path(name: str, default: Path) -> Path:
    return Path(os.getenv(name, str(default))).expanduser().resolve()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", ROOT / "data"))
    local_media_dir: Path = field(default_factory=lambda: _path("LOCAL_MEDIA_DIR", ROOT / "data" / "inbox"))

    ai_provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "auto").strip().lower())
    provider_order: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            part.strip().lower()
            for part in os.getenv("AI_PROVIDER_ORDER", "gemini,openai,anthropic").split(",")
            if part.strip()
        )
    )
    google_api_key: str = field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    )
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5.6-terra"))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"))
    openai_reasoning_effort: str = field(
        default_factory=lambda: os.getenv("OPENAI_REASONING_EFFORT", "medium")
    )
    max_ai_output_tokens: int = field(default_factory=lambda: _int("MAX_AI_OUTPUT_TOKENS", 24000, 4000))

    max_frames: int = field(default_factory=lambda: _int("MAX_FRAMES", 12, 3))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 500, 10))
    hook_seconds: float = field(default_factory=lambda: _float("HOOK_SECONDS", 3.0, 0.5))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small"))
    transcription_language: str = field(default_factory=lambda: os.getenv("TRANSCRIPTION_LANGUAGE", "pt"))
    enable_transcription: bool = field(default_factory=lambda: _bool("ENABLE_TRANSCRIPTION", True))
    enable_public_collection: bool = field(default_factory=lambda: _bool("ENABLE_PUBLIC_COLLECTION", True))
    ephemeral_mode: bool = field(default_factory=lambda: _bool("EPHEMERAL_MODE", False))
    cookies_file: str = field(default_factory=lambda: os.getenv("COOKIES_FILE", ""))
    command_timeout_seconds: int = field(default_factory=lambda: _int("COMMAND_TIMEOUT_SECONDS", 180, 10))

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"

    def ensure_dirs(self) -> None:
        for directory in (
            self.data_dir,
            self.exports_dir,
            self.jobs_dir,
            self.temp_dir,
            self.inbox_dir,
            self.profiles_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
