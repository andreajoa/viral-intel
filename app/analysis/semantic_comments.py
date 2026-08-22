"""Semantic comment clustering with Gemini embeddings and deterministic grouping."""

from __future__ import annotations

import math
from typing import Any

from app.config import Settings


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    width = min(len(vector) for vector in vectors)
    if not width:
        return []
    return _normalize([sum(vector[index] for vector in vectors) / len(vectors) for index in range(width)])


def _cluster(vectors: list[list[float]], threshold: float) -> list[list[int]]:
    clusters: list[list[int]] = []
    centroids: list[list[float]] = []
    for index, vector in enumerate(vectors):
        normalized = _normalize(vector)
        if not normalized:
            continue
        similarities = [_cosine(normalized, centroid) for centroid in centroids]
        if similarities and max(similarities) >= threshold:
            target = max(range(len(similarities)), key=similarities.__getitem__)
            clusters[target].append(index)
            centroids[target] = _centroid([vectors[item] for item in clusters[target]])
        else:
            clusters.append([index])
            centroids.append(normalized)
    return clusters


def _cluster_summary(cluster: list[int], texts: list[str], vectors: list[list[float]], total: int) -> dict[str, Any]:
    center = _centroid([vectors[index] for index in cluster])
    ranked = sorted(cluster, key=lambda index: _cosine(_normalize(vectors[index]), center), reverse=True)
    representative = texts[ranked[0]] if ranked else ""
    cohesion_values = [_cosine(_normalize(vectors[index]), center) for index in cluster]
    return {
        "size": len(cluster),
        "share_of_semantic_sample_pct": round(len(cluster) / total * 100, 1),
        "representative_comment": representative[:500],
        "examples": [texts[index][:500] for index in ranked[:3]],
        "cohesion": round(sum(cohesion_values) / len(cohesion_values), 3) if cohesion_values else None,
    }


def enrich_comment_intelligence(
    summary: dict[str, Any],
    comments: list[dict[str, Any]],
    settings: Settings,
) -> dict[str, Any]:
    """Add semantic clusters without making demographic or sensitive-trait inferences."""

    if not settings.enable_semantic_comments:
        return {**summary, "semantic": {"available": False, "reason": "desativado"}}
    if not settings.google_api_key:
        return {**summary, "semantic": {"available": False, "reason": "GOOGLE_API_KEY ausente"}}

    texts = [str(row.get("text") or "").strip() for row in comments]
    texts = [text for text in texts if text][: settings.semantic_comment_limit]
    if len(texts) < 3:
        return {
            **summary,
            "semantic": {"available": False, "reason": "amostra menor que 3 comentários", "sample_size": len(texts)},
        }

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.google_api_key)
    try:
        response = client.models.embed_content(
            model=settings.embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(output_dimensionality=settings.embedding_dimensions),
        )
        embeddings = getattr(response, "embeddings", None) or []
        vectors = [list(getattr(item, "values", None) or []) for item in embeddings]
        if len(vectors) != len(texts) or any(not vector for vector in vectors):
            raise RuntimeError("quantidade de embeddings diferente da amostra de comentários")
        clusters = _cluster(vectors, settings.semantic_cluster_threshold)
        clusters = sorted(clusters, key=len, reverse=True)
        return {
            **summary,
            "semantic": {
                "available": True,
                "model": settings.embedding_model,
                "dimensions": settings.embedding_dimensions,
                "sample_size": len(texts),
                "cluster_count": len(clusters),
                "similarity_threshold": settings.semantic_cluster_threshold,
                "clusters": [
                    _cluster_summary(cluster, texts, vectors, len(texts)) for cluster in clusters[:8]
                ],
                "coverage_note": (
                    "Clusters representam proximidade semântica apenas na amostra de comentários recebida. "
                    "Não inferem demografia, diagnóstico, identidade ou intenção privada do autor."
                ),
            },
        }
    except Exception as exc:
        detail = str(exc).replace(settings.google_api_key, "[CHAVE_OCULTA]")
        return {
            **summary,
            "semantic": {
                "available": False,
                "reason": f"{type(exc).__name__}: {detail[:220]}",
                "sample_size": len(texts),
            },
        }
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
