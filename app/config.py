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


def _tuple(name: str, default: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in os.getenv(name, default).split(",") if part.strip())


@dataclass(slots=True)
class Settings:
    root: Path = ROOT
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", ROOT / "data"))
    local_media_dir: Path = field(default_factory=lambda: _path("LOCAL_MEDIA_DIR", ROOT / "data" / "inbox"))

    ai_provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "auto").strip().lower())
    provider_order: tuple[str, ...] = field(
        default_factory=lambda: _tuple("AI_PROVIDER_ORDER", "gemini,openai,anthropic")
    )
    google_api_key: str = field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
    )
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.7-flash"))
    gemini_fallback_models: tuple[str, ...] = field(
        default_factory=lambda: _tuple(
            "GEMINI_FALLBACK_MODELS",
            "gemini-3.6-flash,gemini-3.5-flash-lite",
        )
    )
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5.6-terra"))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"))
    openai_reasoning_effort: str = field(
        default_factory=lambda: os.getenv("OPENAI_REASONING_EFFORT", "medium")
    )
    max_ai_output_tokens: int = field(default_factory=lambda: _int("MAX_AI_OUTPUT_TOKENS", 24000, 4000))

    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "gemini-embedding-2"))
    embedding_dimensions: int = field(default_factory=lambda: _int("EMBEDDING_DIMENSIONS", 768, 128))
    enable_semantic_comments: bool = field(default_factory=lambda: _bool("ENABLE_SEMANTIC_COMMENTS", True))
    semantic_comment_limit: int = field(default_factory=lambda: _int("SEMANTIC_COMMENT_LIMIT", 40, 3))
    semantic_cluster_threshold: float = field(
        default_factory=lambda: _float("SEMANTIC_CLUSTER_THRESHOLD", 0.78, 0.1)
    )

    max_frames: int = field(default_factory=lambda: _int("MAX_FRAMES", 16, 3))
    max_upload_mb: int = field(default_factory=lambda: _int("MAX_UPLOAD_MB", 500, 10))
    hook_seconds: float = field(default_factory=lambda: _float("HOOK_SECONDS", 3.0, 0.5))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small"))
    transcription_language: str = field(default_factory=lambda: os.getenv("TRANSCRIPTION_LANGUAGE", "pt"))
    enable_transcription: bool = field(default_factory=lambda: _bool("ENABLE_TRANSCRIPTION", True))
    enable_native_video_ai: bool = field(default_factory=lambda: _bool("ENABLE_NATIVE_VIDEO_AI", True))
    native_video_max_mb: int = field(default_factory=lambda: _int("NATIVE_VIDEO_MAX_MB", 200, 5))
    native_video_poll_seconds: int = field(default_factory=lambda: _int("NATIVE_VIDEO_POLL_SECONDS", 2, 1))
    native_video_timeout_seconds: int = field(
        default_factory=lambda: _int("NATIVE_VIDEO_TIMEOUT_SECONDS", 120, 15)
    )
    enable_public_collection: bool = field(default_factory=lambda: _bool("ENABLE_PUBLIC_COLLECTION", True))
    enable_instagram_embed: bool = field(default_factory=lambda: _bool("ENABLE_INSTAGRAM_EMBED", True))
    auto_download_public_media: bool = field(
        default_factory=lambda: _bool("AUTO_DOWNLOAD_PUBLIC_MEDIA", True)
    )
    max_public_media_mb: int = field(default_factory=lambda: _int("MAX_PUBLIC_MEDIA_MB", 200, 10))
    public_creator_history_limit: int = field(
        default_factory=lambda: _int("PUBLIC_CREATOR_HISTORY_LIMIT", 30, 5)
    )
    ephemeral_mode: bool = field(default_factory=lambda: _bool("EPHEMERAL_MODE", False))
    enable_persistence: bool = field(default_factory=lambda: _bool("ENABLE_PERSISTENCE", True))
    cookies_file: str = field(default_factory=lambda: os.getenv("COOKIES_FILE", ""))
    command_timeout_seconds: int = field(default_factory=lambda: _int("COMMAND_TIMEOUT_SECONDS", 180, 10))

    cloudflare_memory_url: str = field(
        default_factory=lambda: os.getenv("CLOUDFLARE_MEMORY_URL", "").strip().rstrip("/")
    )
    cloudflare_memory_secret: str = field(
        default_factory=lambda: os.getenv("CLOUDFLARE_MEMORY_SECRET", "").strip()
    )
    cloudflare_memory_timeout_seconds: int = field(
        default_factory=lambda: _int("CLOUDFLARE_MEMORY_TIMEOUT_SECONDS", 20, 5)
    )

    apify_api_token: str = field(default_factory=lambda: os.getenv("APIFY_API_TOKEN", ""))
    apify_instagram_actor: str = field(
        default_factory=lambda: os.getenv("APIFY_INSTAGRAM_ACTOR", "apify~instagram-scraper")
    )
    max_public_comments: int = field(default_factory=lambda: _int("MAX_PUBLIC_COMMENTS", 100, 1))

    enable_instagram_graph: bool = field(default_factory=lambda: _bool("ENABLE_INSTAGRAM_GRAPH", True))
    instagram_access_token: str = field(default_factory=lambda: os.getenv("INSTAGRAM_ACCESS_TOKEN", ""))
    instagram_user_id: str = field(default_factory=lambda: os.getenv("INSTAGRAM_USER_ID", ""))
    instagram_api_version: str = field(default_factory=lambda: os.getenv("INSTAGRAM_API_VERSION", "v25.0"))
    max_instagram_comments: int = field(default_factory=lambda: _int("MAX_INSTAGRAM_COMMENTS", 500, 10))
    instagram_history_limit: int = field(default_factory=lambda: _int("INSTAGRAM_HISTORY_LIMIT", 50, 5))
    instagram_max_retries: int = field(default_factory=lambda: _int("INSTAGRAM_MAX_RETRIES", 3, 1))
    instagram_backoff_seconds: float = field(
        default_factory=lambda: _float("INSTAGRAM_BACKOFF_SECONDS", 1.0, 0.1)
    )

    tiktok_access_token: str = field(default_factory=lambda: os.getenv("TIKTOK_ACCESS_TOKEN", ""))
    tiktok_history_limit: int = field(default_factory=lambda: _int("TIKTOK_HISTORY_LIMIT", 20, 1))
    youtube_access_token: str = field(default_factory=lambda: os.getenv("YOUTUBE_ACCESS_TOKEN", ""))
    youtube_history_limit: int = field(default_factory=lambda: _int("YOUTUBE_HISTORY_LIMIT", 25, 1))

    content_twin_limit: int = field(default_factory=lambda: _int("CONTENT_TWIN_LIMIT", 8, 1))
    content_twin_min_score: float = field(default_factory=lambda: _float("CONTENT_TWIN_MIN_SCORE", 0.35, 0.0))

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

    @property
    def intelligence_db(self) -> Path:
        return _path("INTELLIGENCE_DB", self.data_dir / "viral_intel.sqlite3")

    @property
    def remote_persistence_configured(self) -> bool:
        return bool(self.cloudflare_memory_url and self.cloudflare_memory_secret)

    @property
    def persistence_active(self) -> bool:
        return self.enable_persistence and (self.remote_persistence_configured or not self.ephemeral_mode)

    @property
    def persistence_backend(self) -> str:
        if not self.persistence_active:
            return "disabled"
        return "cloudflare_d1" if self.remote_persistence_configured else "sqlite"

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
