"""Backward-compatible wrapper around the v2 media inspector."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.media.inspector import MediaInspector


class LocalProcessor:
    """Legacy facade retained for scripts that imported ``LocalProcessor``."""

    def __init__(self, model_size: str | None = None, device: str = "cpu"):
        self.inspector = MediaInspector()
        if model_size:
            self.inspector.settings.whisper_model = model_size

    def get_metadata(self, video_path: str) -> dict[str, Any]:
        return self.inspector._probe_video(Path(video_path).resolve())

    def inspect(self, paths: list[str], work_dir: str) -> dict[str, Any]:
        return self.inspector.inspect(paths, work_dir)
