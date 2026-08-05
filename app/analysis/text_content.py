"""Deterministic reading of captions and post text when original media is unavailable."""

from __future__ import annotations

import re
from typing import Any

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_SPACE_RE = re.compile(r"\s+")

_EMOTION_TERMS: dict[str, tuple[str, ...]] = {
    "traição": ("traição", "traiu", "amante", "mentira", "enganou", "infiel"),
    "rejeição": ("rejeitou", "abandono", "abandonou", "não me quer", "desprezo", "trocou"),
    "saudade": ("saudade", "falta", "lembrança", "perder", "perdeu", "distância"),
    "medo": ("medo", "receio", "assust", "pânico", "insegurança"),
    "raiva": ("raiva", "ódio", "revolta", "indign", "furioso", "furiosa"),
    "afeto": ("amor", "amo", "carinho", "cuidado", "abraço", "coração"),
    "esperança": ("esperança", "recomeço", "superar", "vai passar", "vencer", "conseguir"),
    "culpa": ("culpa", "arrepend", "desculpa", "perdão", "falhei"),
}

_CTA_TERMS = (
    "comente",
    "conte nos comentários",
    "compartilhe",
    "envie",
    "salve",
    "siga",
    "marque",
    "clique",
    "toque no link",
    "acesse",
)


def _clean(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip())


def _sentences(text: str) -> list[str]:
    rows = [_clean(item) for item in _SENTENCE_RE.split(str(text or ""))]
    return [item for item in rows if item]


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _shorten(text: str, limit: int = 180) -> str:
    cleaned = _clean(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip(" ,;:") + "…"


def analyze_text_content(text: str) -> dict[str, Any]:
    """Return creative fields compatible with the evidence-first strategy pipeline."""

    cleaned = _clean(text)
    if not cleaned:
        return {}

    lowered = cleaned.lower()
    sentences = _sentences(text)
    hook = _shorten(sentences[0] if sentences else cleaned)

    mechanisms: list[str] = []
    if "?" in cleaned:
        mechanisms.append("pergunta que abre uma lacuna de curiosidade")
    if _contains_any(lowered, (" mas ", " porém ", " só que ", " enquanto ", " até que ")):
        mechanisms.append("contraste ou quebra de expectativa")
    if _contains_any(
        lowered,
        ("eu ", "meu ", "minha ", "você", "seu ", "sua ", "nós ", "a gente"),
    ):
        mechanisms.append("identificação em primeira ou segunda pessoa")
    if _contains_any(
        lowered,
        ("trai", "amante", "mentira", "segredo", "termin", "separ", "relacionamento"),
    ):
        mechanisms.append("conflito de relacionamento")
    if '"' in cleaned or "“" in cleaned or ":”" in cleaned or ":" in cleaned:
        mechanisms.append("fala direta ou cena dramatizada")
    if re.search(r"\b\d+\b", cleaned):
        mechanisms.append("detalhe concreto")
    if not mechanisms:
        mechanisms.append("afirmação direta com leitura imediata")

    emotions = [
        label for label, terms in _EMOTION_TERMS.items() if _contains_any(lowered, terms)
    ][:5]
    if not emotions:
        emotions = ["curiosidade"] if "?" in cleaned else ["identificação"]

    cta = "Não identificado"
    for sentence in reversed(sentences or [cleaned]):
        if _contains_any(sentence.lower(), _CTA_TERMS):
            cta = _shorten(sentence, 220)
            break

    tension_bits: list[str] = []
    if "?" in cleaned:
        tension_bits.append("o texto abre uma pergunta que exige continuação")
    if "conflito de relacionamento" in mechanisms:
        tension_bits.append("há um conflito afetivo reconhecível")
    if "contraste ou quebra de expectativa" in mechanisms:
        tension_bits.append("a progressão muda a leitura inicial")
    tension = (
        "; ".join(tension_bits).capitalize() + "."
        if tension_bits
        else "A tensão depende da identificação do público com a situação apresentada."
    )

    sequence: list[str] = []
    labels = ("abertura", "desenvolvimento", "fechamento")
    for index, sentence in enumerate(sentences[:3]):
        sequence.append(f"{labels[index]}: {_shorten(sentence, 150)}")
    if len(sequence) == 1:
        sequence.append("desenvolvimento: a própria frase concentra contexto e conflito")
        sequence.append("fechamento: a interpretação fica a cargo do público")
    elif len(sequence) == 2:
        sequence.append("fechamento: a última ideia encerra ou deixa a tensão em aberto")

    risks: list[str] = []
    if cta == "Não identificado":
        risks.append("não há uma ação explícita para medir a resposta desejada")
    if len(cleaned) > 1_200:
        risks.append("o texto é longo e pode diluir a ideia principal")
    if len(sentences) <= 1:
        risks.append("a estrutura depende de uma única frase e oferece pouca progressão")

    summary = (
        "Leitura textual de uma publicação que apresenta "
        + ", ".join(mechanisms[:3])
        + "."
    )
    promise = (
        "reconhecimento emocional e interpretação de uma situação vivida"
        if any(item in emotions for item in ("traição", "rejeição", "saudade", "afeto"))
        else "uma ideia rápida e reconhecível sobre a situação apresentada"
    )

    return {
        "creative_analysis_source": "text_input",
        "creative_content_summary": summary,
        "creative_primary_hook": hook,
        "creative_hook_mechanisms": mechanisms[:5],
        "creative_emotional_triggers": emotions,
        "creative_curiosity_or_tension": tension,
        "creative_audience_promise": promise,
        "creative_cta_observed": cta,
        "creative_sequence_or_progression": sequence[:6],
        "creative_visual_structure": [],
        "creative_style_signals": [],
        "creative_risks_or_ambiguities": risks[:4],
    }
