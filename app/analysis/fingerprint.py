"""Deterministic creative fingerprints and Content Twin similarity.

The fingerprint intentionally uses only observed/derived attributes. It is not an
embedding from private audience data and it does not claim causal importance. Its job
is to find historically similar content so the benchmark can become more specific than
"all Reels" as the profile accumulates analyses.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

from app.models import PostMetrics

TOKEN_RE = re.compile(r"[a-z0-9áàâãéêíóôõúç]+", re.IGNORECASE)
STOPWORDS = {
    "a",
    "as",
    "com",
    "da",
    "das",
    "de",
    "do",
    "dos",
    "e",
    "em",
    "eu",
    "mais",
    "mas",
    "na",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "ou",
    "para",
    "por",
    "pra",
    "que",
    "se",
    "sem",
    "um",
    "uma",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _tokens(*values: Any, limit: int = 40) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, (list, tuple, set)):
            texts = [str(item or "") for item in value]
        else:
            texts = [str(value or "")]
        for text in texts:
            for token in TOKEN_RE.findall(_fold(text)):
                clean = token.strip().lower()
                if len(clean) < 3 or clean in STOPWORDS or clean in seen:
                    continue
                seen.add(clean)
                found.append(clean)
                if len(found) >= limit:
                    return found
    return found


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_content_fingerprint(
    metrics: PostMetrics,
    technical: dict[str, Any] | None = None,
    transcription: str = "",
    niche: str = "",
) -> dict[str, Any]:
    technical = technical or {}
    hook = _text(technical.get("creative_primary_hook") or metrics.hook_type)
    summary = _text(technical.get("creative_content_summary") or metrics.title)
    caption = _text(technical.get("public_caption") or technical.get("manual_caption"))
    mechanisms = technical.get("creative_hook_mechanisms") or []
    emotions = technical.get("creative_emotional_triggers") or []
    styles = technical.get("creative_style_signals") or []
    progression = technical.get("creative_sequence_or_progression") or []
    if not progression:
        progression = technical.get("creative_visual_structure") or []

    duration = metrics.duration_seconds
    cuts = _number(technical.get("detected_scene_cuts"))
    cuts_per_10s = None
    if duration and duration > 0 and cuts is not None:
        cuts_per_10s = round(cuts / duration * 10, 3)

    text_blob = " ".join(part for part in (summary, hook, caption, transcription, niche) if part)
    return {
        "version": "creative-fingerprint-v1",
        "platform": metrics.platform.value,
        "format": metrics.format.value,
        "topic": _text(metrics.topic),
        "hook_type": _text(metrics.hook_type),
        "cta_type": _text(metrics.cta_type),
        "hook": hook,
        "content_tokens": _tokens(text_blob),
        "mechanisms": _tokens(mechanisms, limit=12),
        "emotions": _tokens(emotions, limit=12),
        "styles": _tokens(styles, limit=12),
        "progression": [_text(item) for item in progression if _text(item)][:10],
        "orientation": _text(technical.get("orientation")),
        "has_audio": technical.get("has_audio"),
        "duration_seconds": round(float(duration), 3) if duration is not None else None,
        "cuts_per_10s": cuts_per_10s,
        "asset_type": _text(technical.get("creative_asset_type") or technical.get("kind")),
    }


def _jaccard(left: list[str] | None, right: list[str] | None) -> float:
    a, b = set(left or []), set(right or [])
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _categorical(left: Any, right: Any) -> float:
    a, b = _fold(_text(left)), _fold(_text(right))
    return 1.0 if a and b and a == b else 0.0


def _numeric_similarity(left: Any, right: Any, scale: float) -> float:
    a, b = _number(left), _number(right)
    if a is None or b is None:
        return 0.0
    return max(0.0, 1.0 - abs(a - b) / max(scale, abs(a), abs(b), 1.0))


def fingerprint_similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    """Weighted similarity in [0, 1], designed to remain interpretable."""

    if left.get("platform") != right.get("platform") or left.get("format") != right.get("format"):
        return 0.0

    components = [
        (0.28, _jaccard(left.get("content_tokens"), right.get("content_tokens"))),
        (0.14, _jaccard(left.get("mechanisms"), right.get("mechanisms"))),
        (0.10, _jaccard(left.get("emotions"), right.get("emotions"))),
        (0.08, _jaccard(left.get("styles"), right.get("styles"))),
        (0.10, _categorical(left.get("topic"), right.get("topic"))),
        (0.08, _categorical(left.get("hook_type"), right.get("hook_type"))),
        (0.05, _categorical(left.get("cta_type"), right.get("cta_type"))),
        (0.04, _categorical(left.get("orientation"), right.get("orientation"))),
        (0.08, _numeric_similarity(left.get("duration_seconds"), right.get("duration_seconds"), 30.0)),
        (0.05, _numeric_similarity(left.get("cuts_per_10s"), right.get("cuts_per_10s"), 5.0)),
    ]
    score = sum(weight * value for weight, value in components)
    return round(min(1.0, max(0.0, score)), 4)


def rank_content_twins(
    target: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    limit: int = 8,
    minimum_score: float = 0.35,
) -> list[dict[str, Any]]:
    twins: list[dict[str, Any]] = []
    for candidate in candidates:
        fingerprint = candidate.get("fingerprint") or {}
        score = fingerprint_similarity(target, fingerprint)
        if score < minimum_score:
            continue
        twins.append(
            {
                "report_id": candidate.get("report_id"),
                "post_id": candidate.get("post_id"),
                "captured_at": candidate.get("captured_at"),
                "similarity": score,
                "metrics": candidate.get("metrics") or {},
                "benchmark": candidate.get("benchmark") or {},
                "fingerprint": fingerprint,
            }
        )
    twins.sort(
        key=lambda item: (
            item["similarity"],
            math.log1p(float((item.get("metrics") or {}).get("views") or 0)),
        ),
        reverse=True,
    )
    return twins[: max(1, limit)]
