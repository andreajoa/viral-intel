from __future__ import annotations

import unittest

from app.analysis.fingerprint import (
    build_content_fingerprint,
    fingerprint_similarity,
    rank_content_twins,
)
from app.models import PostMetrics


class FingerprintV5Tests(unittest.TestCase):
    def _metrics(self, topic: str = "autismo") -> PostMetrics:
        return PostMetrics(
            platform="instagram",
            format="reel",
            topic=topic,
            hook_type="pergunta",
            cta_type="compartilhar",
            duration_seconds=24,
        )

    def test_similar_content_scores_higher_than_unrelated_content(self):
        base = build_content_fingerprint(
            self._metrics(),
            {
                "creative_primary_hook": "Seu filho faz isso?",
                "creative_hook_mechanisms": ["curiosidade", "identificação"],
                "creative_emotional_triggers": ["preocupação"],
                "creative_content_summary": "Sinais de comunicação no autismo",
                "orientation": "vertical",
                "detected_scene_cuts": 6,
            },
        )
        similar = build_content_fingerprint(
            self._metrics(),
            {
                "creative_primary_hook": "Você já percebeu este sinal?",
                "creative_hook_mechanisms": ["curiosidade", "identificação"],
                "creative_emotional_triggers": ["preocupação"],
                "creative_content_summary": "Sinais de comunicação em crianças autistas",
                "orientation": "vertical",
                "detected_scene_cuts": 5,
            },
        )
        unrelated = build_content_fingerprint(
            self._metrics(topic="receita"),
            {
                "creative_primary_hook": "Bolo em cinco minutos",
                "creative_hook_mechanisms": ["promessa"],
                "creative_content_summary": "Receita rápida de chocolate",
                "orientation": "horizontal",
                "detected_scene_cuts": 1,
            },
        )
        self.assertGreater(fingerprint_similarity(base, similar), fingerprint_similarity(base, unrelated))

    def test_different_platform_or_format_is_not_a_content_twin(self):
        left = {"platform": "instagram", "format": "reel", "content_tokens": ["autismo"]}
        right = {"platform": "youtube", "format": "short", "content_tokens": ["autismo"]}
        self.assertEqual(fingerprint_similarity(left, right), 0.0)

    def test_rank_twins_respects_threshold(self):
        target = {"platform": "instagram", "format": "reel", "content_tokens": ["fala", "autismo"]}
        rows = [
            {
                "report_id": "r1",
                "post_id": "p1",
                "fingerprint": {
                    "platform": "instagram",
                    "format": "reel",
                    "content_tokens": ["fala", "autismo"],
                },
                "metrics": {"views": 1000},
            },
            {
                "report_id": "r2",
                "post_id": "p2",
                "fingerprint": {
                    "platform": "instagram",
                    "format": "reel",
                    "content_tokens": ["receita"],
                },
                "metrics": {"views": 5000},
            },
        ]
        twins = rank_content_twins(target, rows, minimum_score=0.2)
        self.assertEqual(twins[0]["post_id"], "p1")


if __name__ == "__main__":
    unittest.main()
