"""Evidence-producing video, image, and carousel inspection.

FFmpeg is used for deterministic technical measurements.  Speech recognition is
loaded lazily so the dashboard still starts on machines where the optional model has
not yet been downloaded.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, ImageStat

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def media_kind(paths: list[Path]) -> str:
    if len(paths) > 1 and all(path.suffix.lower() in IMAGE_EXTS for path in paths):
        return "carousel"
    if len(paths) == 1 and paths[0].suffix.lower() in VIDEO_EXTS:
        return "video"
    if len(paths) == 1 and paths[0].suffix.lower() in IMAGE_EXTS:
        return "image"
    return "unknown"


def validate_media_selection(paths: list[Path], content_format: str) -> str | None:
    """Return a user-facing error when upload type contradicts the selected format."""

    if not paths:
        return None
    actual = media_kind(paths)
    expected = str(content_format).strip().lower()

    if actual == "unknown":
        return (
            "A seleção mistura tipos de mídia ou contém mais de um vídeo. Envie um vídeo ou somente imagens."
        )
    if expected in {"reel", "short", "video"} and actual != "video":
        return (
            f"O formato selecionado é “{expected}”, mas o upload contém {actual}. "
            "Envie o arquivo de vídeo (MP4, MOV ou WEBM) para analisar gancho, ritmo e retenção."
        )
    if expected == "carousel" and actual not in {"carousel", "image"}:
        return "Para analisar um carrossel, envie a captura da capa ou os slides na ordem correta."
    if expected == "image" and actual != "image":
        return "Para o formato “image”, envie exatamente uma imagem."
    if expected == "text" and actual not in {"image"}:
        return "Para conteúdo de texto, envie uma captura única do post ou use somente o link público."
    return None


class MediaInspectionError(RuntimeError):
    pass


class MediaInspector:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._whisper = None

    def _run(self, command: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout or self.settings.command_timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise MediaInspectionError(f"Comando obrigatório não encontrado: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaInspectionError(
                f"Processamento excedeu {timeout or self.settings.command_timeout_seconds}s"
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "erro desconhecido")[-700:]
            raise MediaInspectionError(f"{command[0]} falhou: {detail}") from exc

    def inspect(self, paths: list[str | Path], work_dir: str | Path) -> dict[str, Any]:
        media_paths = [Path(path).expanduser().resolve() for path in paths]
        if not media_paths:
            return {"kind": "none", "technical": {}, "frames": [], "transcription": "", "warnings": []}
        for path in media_paths:
            if not path.is_file():
                raise MediaInspectionError(f"Arquivo não encontrado: {path.name}")
            if path.stat().st_size > self.settings.max_upload_mb * 1024 * 1024:
                raise MediaInspectionError(
                    f"{path.name} excede o limite configurado de {self.settings.max_upload_mb} MB"
                )

        kind = media_kind(media_paths)
        destination = Path(work_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        if kind == "video":
            return self._inspect_video(media_paths[0], destination)
        if kind in {"image", "carousel"}:
            return self._inspect_images(media_paths, destination, kind)
        raise MediaInspectionError("Formato não suportado. Use MP4, MOV, WEBM, JPG, PNG ou WEBP.")

    def _probe_video(self, path: Path) -> dict[str, Any]:
        result = self._run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ]
        )
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        duration = video.get("duration") or (payload.get("format") or {}).get("duration")
        fps_value = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        try:
            fps = float(Fraction(fps_value))
        except (ValueError, ZeroDivisionError):
            fps = 0.0
        width, height = int(video.get("width") or 0), int(video.get("height") or 0)
        return {
            "duration_seconds": round(float(duration or 0), 3),
            "width": width,
            "height": height,
            "aspect_ratio": round(width / height, 4) if height else None,
            "fps": round(fps, 3),
            "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name"),
            "has_audio": bool(audio),
            "file_size_mb": round(path.stat().st_size / (1024 * 1024), 2),
        }

    def _timestamps(self, duration: float) -> list[float]:
        if duration <= 0:
            return [0.0]
        hook = [0.0, 0.5, 1.0, min(self.settings.hook_seconds, duration * 0.2)]
        body = [duration * 0.25, duration * 0.5, duration * 0.75]
        end = [max(0.0, duration - 2.0), max(0.0, duration - 0.25)]
        values = sorted(
            {round(min(max(value, 0.0), max(0.0, duration - 0.05)), 2) for value in hook + body + end}
        )
        if len(values) <= self.settings.max_frames:
            return values
        hook_values = [value for value in values if value <= self.settings.hook_seconds]
        remaining = [value for value in values if value > self.settings.hook_seconds]
        return (hook_values + remaining)[: self.settings.max_frames]

    def _extract_frames(
        self, path: Path, destination: Path, duration: float
    ) -> tuple[list[bytes], list[float]]:
        frames: list[bytes] = []
        successful_timestamps: list[float] = []
        for index, timestamp in enumerate(self._timestamps(duration), start=1):
            output = destination / f"frame_{index:02d}.jpg"
            self._run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    str(timestamp),
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale='min(1280,iw)':-2",
                    "-q:v",
                    "3",
                    "-y",
                    str(output),
                ]
            )
            if output.exists() and output.stat().st_size:
                frames.append(output.read_bytes())
                successful_timestamps.append(timestamp)
        return frames, successful_timestamps

    def _scene_cuts(self, path: Path) -> list[float]:
        try:
            result = self._run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-i",
                    str(path),
                    "-filter:v",
                    "select='gt(scene,0.35)',showinfo",
                    "-an",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=max(self.settings.command_timeout_seconds, 300),
            )
            return [round(float(value), 2) for value in re.findall(r"pts_time:([0-9.]+)", result.stderr)]
        except MediaInspectionError as exc:
            logger.info("Scene detection unavailable: %s", exc)
            return []

    def _audio_loudness(self, path: Path) -> dict[str, float]:
        try:
            result = self._run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-i",
                    str(path),
                    "-vn",
                    "-af",
                    "loudnorm=print_format=json",
                    "-f",
                    "null",
                    "-",
                ]
            )
            blocks = re.findall(r"\{\s*\"input_i\"[\s\S]*?\}", result.stderr)
            if not blocks:
                return {}
            raw = json.loads(blocks[-1])
            mapping = {
                "input_i": "integrated_loudness_lufs",
                "input_tp": "true_peak_db",
                "input_lra": "loudness_range_lu",
            }
            return {
                mapping[key]: round(float(raw[key]), 2)
                for key in mapping
                if raw.get(key) not in (None, "-inf")
            }
        except (MediaInspectionError, ValueError, json.JSONDecodeError):
            return {}

    def _transcribe(self, path: Path, destination: Path) -> tuple[str, list[dict[str, Any]], str | None]:
        if not self.settings.enable_transcription:
            return "", [], "Transcrição desativada na configuração."
        wav = destination / "audio.wav"
        try:
            self._run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-y",
                    str(wav),
                ]
            )
            if self._whisper is None:
                from faster_whisper import WhisperModel

                self._whisper = WhisperModel(
                    self.settings.whisper_model,
                    device="cpu",
                    compute_type="int8",
                )
            segments, _ = self._whisper.transcribe(
                str(wav),
                beam_size=5,
                language=self.settings.transcription_language or None,
                vad_filter=True,
            )
            rows = [
                {"start": round(segment.start, 2), "end": round(segment.end, 2), "text": segment.text.strip()}
                for segment in segments
                if segment.text.strip()
            ]
            return " ".join(row["text"] for row in rows), rows, None
        except (ImportError, MediaInspectionError, RuntimeError) as exc:
            return "", [], f"Transcrição indisponível: {type(exc).__name__}: {str(exc)[:180]}"

    def _inspect_video(self, path: Path, destination: Path) -> dict[str, Any]:
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise MediaInspectionError("FFmpeg e ffprobe precisam estar instalados.")
        metadata = self._probe_video(path)
        frames, timestamps = self._extract_frames(path, destination, metadata["duration_seconds"])
        cuts = self._scene_cuts(path)
        loudness = self._audio_loudness(path) if metadata["has_audio"] else {}
        transcription, segments, transcription_warning = self._transcribe(path, destination)

        duration = metadata["duration_seconds"]
        technical: dict[str, Any] = dict(metadata)
        technical.update(loudness)
        technical["sampled_frame_timestamps_seconds"] = timestamps
        technical["detected_scene_cuts"] = len(cuts)
        technical["average_seconds_per_cut"] = round(duration / len(cuts), 2) if cuts else None
        technical["orientation"] = (
            "vertical"
            if (metadata.get("aspect_ratio") or 1) < 0.9
            else "horizontal"
            if (metadata.get("aspect_ratio") or 1) > 1.1
            else "square"
        )
        warnings = [transcription_warning] if transcription_warning else []
        return {
            "kind": "video",
            "technical": technical,
            "frames": frames,
            "transcription": transcription,
            "transcription_segments": segments,
            "warnings": warnings,
        }

    def _inspect_images(self, paths: list[Path], destination: Path, kind: str) -> dict[str, Any]:
        frames: list[bytes] = []
        slides: list[dict[str, Any]] = []
        warnings: list[str] = []
        for index, path in enumerate(paths[: self.settings.max_frames], start=1):
            try:
                with Image.open(path) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                    width, height = image.size
                    stat = ImageStat.Stat(image.resize((64, 64)))
                    brightness = round(sum(stat.mean) / 3, 2)
                    entropy = round(float(image.entropy()), 2)
                    preview = image.copy()
                    preview.thumbnail((1440, 1440), Image.Resampling.LANCZOS)
                    output = destination / f"slide_{index:02d}.jpg"
                    preview.save(output, "JPEG", quality=88, optimize=True)
                    frames.append(output.read_bytes())
                    slides.append(
                        {
                            "slide": index,
                            "width": width,
                            "height": height,
                            "aspect_ratio": round(width / height, 4) if height else None,
                            "brightness_0_255": brightness,
                            "visual_entropy": entropy,
                        }
                    )
            except Exception as exc:
                warnings.append(f"Não foi possível ler {path.name}: {type(exc).__name__}")
        if not frames:
            raise MediaInspectionError("Nenhuma imagem válida foi encontrada.")
        return {
            "kind": kind,
            "technical": {
                "slide_count": len(paths),
                "slides_inspected": len(frames),
                "slide_properties": slides,
            },
            "frames": frames,
            "transcription": "",
            "transcription_segments": [],
            "warnings": warnings,
        }
