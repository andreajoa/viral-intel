from __future__ import annotations

from app.ai.evidence_observer import (
    CommentScreenshotObservation,
    ExtractedComment,
    ExtractedInsightMetric,
    InsightScreenshotObservation,
)
from app.evidence_ingestion_guardrails import (
    EXTERNAL_MODE,
    OWNER_MODE,
    PUBLIC_MODE,
    evidence_readiness,
    merge_comment_evidence,
    merge_metric_evidence,
)


def test_insight_observation_requires_an_explicit_zero() -> None:
    observation = InsightScreenshotObservation(
        observed=True,
        metrics=[
            ExtractedInsightMetric(
                metric="comments",
                value=0,
                displayed_text="",
                visual_evidence="linha de comentários cortada",
                confidence=98,
            ),
            ExtractedInsightMetric(
                metric="likes",
                value=0,
                displayed_text="0",
                visual_evidence="0 curtidas",
                confidence=98,
            ),
            ExtractedInsightMetric(
                metric="non_follower_reach_rate",
                value=64,
                displayed_text="64%",
                visual_evidence="Não seguidores 64%",
                confidence=96,
            ),
        ],
    )

    assert observation.metrics_for_merge() == {
        "likes": 0,
        "non_follower_reach_rate": 64,
    }


def test_screenshot_metrics_never_overwrite_manual_values() -> None:
    merged = merge_metric_evidence(
        {"likes": 120, "reach": None, "source_notes": ["valor conferido"]},
        {"likes": 999, "reach": 5000, "shares": 230},
    )

    assert merged["likes"] == 120
    assert merged["reach"] == 5000
    assert merged["shares"] == 230
    assert merged["source"] == "mixed"
    assert "valor conferido" in merged["source_notes"]
    assert any("reach" in note and "shares" in note for note in merged["source_notes"])


def test_comment_screenshots_are_filtered_and_deduplicated() -> None:
    observation = CommentScreenshotObservation(
        observed=True,
        comments=[
            ExtractedComment(author="ana", text="Isso aconteceu comigo", confidence=95),
            ExtractedComment(author="Ana", text="Isso aconteceu comigo", confidence=92),
            ExtractedComment(author="", text="texto ilegível", confidence=20),
        ],
    )

    extracted = observation.comments_for_merge()
    assert len(extracted) == 1

    merged = merge_comment_evidence(
        [{"author": "joao", "text": "Compartilhei com alguém"}],
        extracted,
    )
    assert len(merged) == 2
    assert {row["author"] for row in merged} == {"joao", "ana"}


def test_owner_mode_can_reach_deep_analysis_readiness() -> None:
    readiness = evidence_readiness(
        mode=OWNER_MODE,
        media_count=1,
        has_text=True,
        metric_count=8,
        comment_count=30,
        history_count=10,
        official_access=False,
    )

    assert readiness["score"] == 100
    assert readiness["level"] == "PRONTO PARA ANÁLISE PROFUNDA"
    assert "histórico comparável" in readiness["present"]


def test_external_mode_is_capped_below_owner_depth() -> None:
    readiness = evidence_readiness(
        mode=EXTERNAL_MODE,
        media_count=1,
        has_text=True,
        metric_count=6,
        comment_count=40,
        history_count=0,
        official_access=False,
    )

    assert readiness["score"] == 85
    assert readiness["level"] == "PRONTO PARA ANÁLISE PROFUNDA"
    assert any("identidade" in item.lower() for item in readiness["hard_limits"])


def test_public_link_mode_is_always_triage() -> None:
    readiness = evidence_readiness(
        mode=PUBLIC_MODE,
        media_count=0,
        has_text=True,
        metric_count=3,
        comment_count=10,
        history_count=0,
        official_access=False,
    )

    assert readiness["score"] <= 45
    assert readiness["level"] != "PRONTO PARA ANÁLISE PROFUNDA"
