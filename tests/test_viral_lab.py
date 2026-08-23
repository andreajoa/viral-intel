from __future__ import annotations

import unittest

from app.ai.schema import NextContentPlan, StrategicReport
from app.analysis.viral_lab import (
    build_public_creator_baseline,
    build_replication_blueprint,
    build_viral_dna,
    public_history_to_posts,
)
from app.models import ContentFormat, Platform, PostMetrics


class ViralLabTests(unittest.TestCase):
    def test_public_history_proves_creator_relative_breakout(self):
        history = public_history_to_posts(
            [
                {
                    "id": f"p-{index}",
                    "url": f"https://www.instagram.com/reel/{index}/",
                    "videoPlayCount": views,
                    "likesCount": max(1, views // 20),
                    "commentsCount": max(1, views // 500),
                    "timestamp": "2026-08-01T12:00:00Z",
                    "productType": "clips",
                }
                for index, views in enumerate([10000, 12000, 9000, 15000, 11000, 13000, 14000, 10000], 1)
            ],
            platform=Platform.INSTAGRAM,
            followers=50000,
        )
        target = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.REEL,
            post_id="viral",
            followers=50000,
            views=220000,
            likes=18000,
            comments=800,
            source="public",
        )

        baseline = build_public_creator_baseline(target, history)

        self.assertTrue(baseline["available"])
        self.assertEqual(baseline["status"], "BREAKOUT_FORTE")
        self.assertGreater(baseline["breakout_multiple"], 10)
        self.assertGreaterEqual(baseline["sample_size"], 8)

    def test_viral_dna_separates_observation_from_causality(self):
        target = PostMetrics(
            platform=Platform.INSTAGRAM,
            format=ContentFormat.REEL,
            followers=10000,
            views=100000,
            likes=9000,
            comments=500,
            source="public",
        )
        dna = build_viral_dna(
            metrics=target,
            technical={
                "creative_primary_hook": "Você está fazendo isso errado",
                "creative_hook_mechanisms": ["contraste", "curiosidade"],
                "creative_sequence_or_progression": ["problema", "demonstração", "payoff"],
                "creative_emotional_triggers": ["identificação"],
                "creative_cta_observed": "marque alguém",
                "creative_content_summary": "Reel curto com demonstração.",
            },
            creator_baseline={
                "available": True,
                "status": "BREAKOUT_FORTE",
                "breakout_multiple": 8.0,
                "percentile": 100.0,
                "metric": "views",
            },
            comments={
                "available": True,
                "sample_size": 20,
                "mention_rate_pct": 30.0,
                "question_rate_pct": 15.0,
                "intent_distribution": [{"intent": "marcação ou envio", "share_of_sample_pct": 30.0}],
            },
        )

        self.assertEqual(dna["status"], "BREAKOUT_FORTE")
        self.assertTrue(any(item["mechanism"] == "Gancho" for item in dna["mechanics"]))
        self.assertIn("não prova causal", str(dna["mechanics"][0]["causality"]))
        self.assertTrue(dna["public_proof"])

    def test_replication_prompt_demands_original_adaptation(self):
        strategy = StrategicReport(
            executive_summary="O post apresenta um padrão forte.",
            performance_interpretation="Há sinais públicos e criativos úteis.",
            repeat_decision="ITERAR",
            root_cause_hypotheses=[],
            format_insights=[],
            profile_insights=[],
            audience_insights=[],
            next_content=NextContentPlan(
                format="Reel",
                objective="Compartilhamentos",
                hook_options=["Gancho A", "Gancho B"],
                structure=["Gancho", "Tensão", "Payoff"],
                caption_direction="Legenda curta",
                cta="Marque alguém",
                preserve=["open loop", "ritmo rápido"],
                change=["tema", "exemplos"],
                based_on_refs=[],
            ),
            experiments=[
                {
                    "hypothesis": "Gancho direto aumenta retenção inicial",
                    "change_one_thing": "gancho",
                    "keep_constant": ["tema"],
                    "primary_metric": "views",
                    "comparison_rule": "comparar mediana",
                    "minimum_sample": "3 posts",
                    "based_on_refs": [],
                }
            ],
            caveats=[],
        )

        blueprint = build_replication_blueprint(
            strategy=strategy,
            technical={},
            creator_baseline={"limitations": ["dados públicos"]},
            niche="educação inclusiva",
        )

        self.assertIn("ORIGINAL", blueprint["ai_prompt"])
        self.assertIn("educação inclusiva", blueprint["ai_prompt"])
        self.assertIn("Não copiar", blueprint["ai_prompt"])
        self.assertEqual(blueprint["cta"], "Marque alguém")


if __name__ == "__main__":
    unittest.main()
