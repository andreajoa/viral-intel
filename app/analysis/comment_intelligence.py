"""Privacy-conscious, deterministic analysis of available Instagram comments.

The module analyses only comment text and metadata explicitly supplied by an official
API, a public collector or a user upload. It does not infer demographics, sensitive
traits or private relationships from usernames.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

WORD_RE = re.compile(r"[\wÀ-ÿ']+", re.UNICODE)
MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z0-9._]+")
QUESTION_RE = re.compile(r"\?")

STOPWORDS = {
    "a",
    "agora",
    "ainda",
    "ao",
    "aos",
    "as",
    "assim",
    "até",
    "com",
    "como",
    "da",
    "das",
    "de",
    "dela",
    "dele",
    "do",
    "dos",
    "e",
    "ela",
    "ele",
    "em",
    "essa",
    "esse",
    "esta",
    "este",
    "eu",
    "foi",
    "isso",
    "já",
    "mais",
    "mas",
    "me",
    "mesmo",
    "meu",
    "minha",
    "muito",
    "na",
    "não",
    "nas",
    "no",
    "nos",
    "o",
    "os",
    "ou",
    "para",
    "pela",
    "pelo",
    "por",
    "porque",
    "pra",
    "que",
    "se",
    "sem",
    "ser",
    "só",
    "também",
    "te",
    "tem",
    "ter",
    "tu",
    "um",
    "uma",
    "você",
    "vocês",
}

INTENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "identificação pessoal": (
        "aconteceu comigo",
        "eu passei",
        "eu vivi",
        "me identifiquei",
        "parece comigo",
        "sou eu",
        "minha história",
        "senti isso",
        "estou vivendo",
        "já vivi",
    ),
    "saudade ou luto": (
        "saudade",
        "sinto falta",
        "perdi",
        "luto",
        "faleceu",
        "morreu",
        "nunca mais",
        "partiu",
    ),
    "relacionamento ou término": (
        "ex",
        "término",
        "terminou",
        "separação",
        "relacionamento",
        "amor",
        "casamento",
        "namoro",
    ),
    "marcação ou envio": (
        "manda pra",
        "envia pra",
        "lembrei de você",
        "olha isso",
        "precisava ler",
        "você precisa ver",
    ),
    "concordância ou validação": (
        "verdade",
        "exatamente",
        "é isso",
        "sim",
        "perfeito",
        "falou tudo",
        "concordo",
    ),
    "discordância ou resistência": (
        "discordo",
        "não é assim",
        "nada a ver",
        "depende",
        "mentira",
        "exagero",
    ),
    "pedido de orientação": (
        "como faço",
        "o que fazer",
        "me ajuda",
        "algum conselho",
        "como superar",
        "como lidar",
    ),
}

POSITIVE_MARKERS = {
    "amor",
    "amei",
    "bonito",
    "emocionante",
    "esperança",
    "gratidão",
    "lindo",
    "perfeito",
    "verdade",
}
NEGATIVE_MARKERS = {
    "dor",
    "doeu",
    "ódio",
    "raiva",
    "triste",
    "tristeza",
    "sofrimento",
    "saudade",
    "perda",
}
SPAM_MARKERS = {
    "ganhe dinheiro",
    "me chama no direct",
    "promoção",
    "renda extra",
    "sigam",
    "siga de volta",
    "link na bio",
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _text(comment: dict[str, Any]) -> str:
    return str(comment.get("text") or comment.get("comment") or "").strip()


def _author(comment: dict[str, Any]) -> str:
    value = comment.get("author") or comment.get("username") or comment.get("from")
    if isinstance(value, dict):
        value = value.get("username") or value.get("id")
    return str(value or "").strip()


def _likes(comment: dict[str, Any]) -> int:
    value = comment.get("likes")
    if value is None:
        value = comment.get("like_count")
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_comments(comments: list[dict[str, Any]] | None, limit: int = 500) -> list[dict[str, Any]]:
    """Return a compact, serialisable comment representation."""

    normalized: list[dict[str, Any]] = []
    for raw in comments or []:
        if not isinstance(raw, dict):
            continue
        text = _text(raw)
        if not text:
            continue
        normalized.append(
            {
                "author": _author(raw) or None,
                "text": text[:2000],
                "likes": _likes(raw),
                "timestamp": raw.get("timestamp") or raw.get("published_at"),
                "id": raw.get("id"),
            }
        )
        if len(normalized) >= limit:
            break
    return normalized


def _intent_hits(text: str) -> set[str]:
    folded = _fold(text)
    hits = {
        label
        for label, patterns in INTENT_PATTERNS.items()
        if any(_fold(pattern) in folded for pattern in patterns)
    }
    if MENTION_RE.search(text):
        hits.add("marcação ou envio")
    if QUESTION_RE.search(text):
        hits.add("pergunta")
    return hits


def _keywords(comments: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for comment in comments:
        for token in WORD_RE.findall(comment["text"].lower()):
            clean = token.strip("_'’")
            if len(clean) < 3 or clean in STOPWORDS or clean.startswith("http"):
                continue
            counts[clean] += 1
    return [{"term": term, "count": count} for term, count in counts.most_common(limit)]


def analyze_comments(comments: list[dict[str, Any]] | None, limit: int = 500) -> dict[str, Any]:
    """Summarise available comments without pretending they represent all viewers."""

    rows = normalize_comments(comments, limit=limit)
    if not rows:
        return {
            "available": False,
            "sample_size": 0,
            "unique_commenters": 0,
            "coverage_note": "Nenhum texto de comentário foi fornecido ou retornado pela fonte.",
            "privacy_note": (
                "O Viral Intel não tenta descobrir identidades de pessoas que curtiram ou compartilharam."
            ),
        }

    unique_commenters = {row["author"].lower() for row in rows if row.get("author")}
    intent_counts: Counter[str] = Counter()
    positive = negative = neutral = spam = mention_comments = question_comments = 0

    for row in rows:
        text = row["text"]
        folded = _fold(text)
        hits = _intent_hits(text)
        intent_counts.update(hits)
        mention_comments += int(bool(MENTION_RE.search(text)))
        question_comments += int(bool(QUESTION_RE.search(text)))
        is_spam = any(_fold(marker) in folded for marker in SPAM_MARKERS)
        spam += int(is_spam)
        pos_hits = sum(_fold(marker) in folded for marker in POSITIVE_MARKERS)
        neg_hits = sum(_fold(marker) in folded for marker in NEGATIVE_MARKERS)
        if pos_hits > neg_hits:
            positive += 1
        elif neg_hits > pos_hits:
            negative += 1
        else:
            neutral += 1

    denominator = len(rows)
    top_comments = sorted(rows, key=lambda row: (row["likes"], len(row["text"])), reverse=True)[:8]
    intent_rows = [
        {
            "intent": label,
            "count": count,
            "share_of_sample_pct": round(count / denominator * 100, 1),
        }
        for label, count in intent_counts.most_common()
    ]

    return {
        "available": True,
        "sample_size": denominator,
        "unique_commenters": len(unique_commenters),
        "comments_with_mentions": mention_comments,
        "mention_rate_pct": round(mention_comments / denominator * 100, 1),
        "questions": question_comments,
        "question_rate_pct": round(question_comments / denominator * 100, 1),
        "sentiment_direction": {
            "positive_or_approving": positive,
            "pain_or_negative_emotion": negative,
            "neutral_or_unclear": neutral,
        },
        "possible_spam": spam,
        "intent_distribution": intent_rows,
        "top_terms": _keywords(rows),
        "top_comments_by_visible_likes": top_comments,
        "coverage_note": (
            "A amostra descreve apenas os comentários recebidos pela fonte; não representa pessoas que "
            "viram, curtiram, salvaram ou compartilharam sem comentar."
        ),
        "privacy_note": (
            "Usernames são mantidos somente quando já vieram da fonte autorizada. Nenhuma característica "
            "demográfica ou sensível é inferida a partir deles."
        ),
    }
