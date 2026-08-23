# ruff: noqa: I001

import pathlib
import tempfile
import unittest
import unittest.mock

import app.models as models
import app.pipeline.public_link as public_link


STRATEGY = {
    "executive_summary": "Breakout público com mecanismos criativos observáveis.",
    "performance_interpretation": "O post ficou acima do padrão público recente.",
    "repeat_decision": "ITERAR",
    "root_cause_hypotheses": [],
    "format_insights": [],
    "profile_insights": [],
    "audience_insights": [],
    "next_content": {
        "format": "Reel",
        "objective": "Compartilhamentos",
        "hook_options": ["Gancho A", "Gancho B"],
        "structure": ["Gancho", "Tensão", "Payoff"],
        "caption_direction": "Curta e específica",
        "cta": "Compartilhe",
        "preserve": ["curiosidade", "ritmo"],
        "change": ["tema", "exemplo"],
        "based_on_refs": [],
    },
    "experiments": [
        {
            "hypothesis": "Testar gancho",
            "change_one_thing": "gancho",
            "keep_constant": ["tema"],
            "primary_metric": "views",
            "comparison_rule": "comparar mediana",
            "minimum_sample": "3 posts",
            "based_on_refs": [],
        }
    ],
    "caveats": [],
}


class FakePackageCollector:
    def __init__(self, settings):
        self.settings = settings

    def collect(self, url, destination):
        return {
            "source_ok": True,
            "collection_source": "apify/instagram-public",
            "platform": "Instagram",
            "post_id": "viral",
            "webpage_url": url,
            "caption": "Legenda pública",
            "uploader": "criador",
            "followers": 50000,
            "views": 220000,
            "likes": 18000,
            "comments_count": 800,
            "comments_sample": [{"author": "a", "text": "@b olha isso", "likes": 3}],
            "downloaded_media_paths": [str(destination / "viral.mp4")],
            "creator_history": [
                {
                    "id": f"old-{index}",
                    "url": f"https://www.instagram.com/reel/old-{index}/",
                    "videoPlayCount": views,
                    "likesCount": views // 20,
                    "commentsCount": max(1, views // 500),
                    "timestamp": "2026-08-01T12:00:00Z",
                    "productType": "clips",
                }
                for index, views in enumerate([10000, 12000, 9000, 15000, 11000, 13000], 1)
            ],
            "auto_collection": {
                "metadata": True,
                "media_downloaded": True,
                "media_files": 1,
                "comments": 1,
                "creator_history": 6,
            },
            "account": {"username": "criador", "id": "creator-1"},
            "source_notes": [],
        }


def fake_analyze_content(**kwargs):
    metrics = models.PostMetrics(
        platform="instagram",
        format="reel",
        post_id="viral",
        post_url=kwargs["url"],
        followers=50000,
        views=220000,
        likes=18000,
        comments=800,
        source="public",
    )
    return models.AnalysisEnvelope(
        report_id="vi_test",
        metrics=metrics,
        derived_metrics={},
        benchmark=models.BenchmarkResult(),
        data_quality=models.DataQuality(level="MÉDIA", completeness_score=60),
        evidence=[],
        technical_analysis={
            "comment_intelligence": {
                "available": True,
                "sample_size": 1,
                "mention_rate_pct": 100.0,
                "question_rate_pct": 0.0,
                "intent_distribution": [
                    {"intent": "marcação ou envio", "share_of_sample_pct": 100.0}
                ],
            },
            "creative_content_summary": "Vídeo curto com payoff.",
            "creative_primary_hook": "Pare de fazer isso",
            "creative_hook_mechanisms": ["contraste"],
            "creative_sequence_or_progression": ["gancho", "tensão", "payoff"],
        },
        strategy=STRATEGY,
    )


class PublicLinkPipelineTests(unittest.TestCase):
    def test_url_only_enriches_report_with_breakout_dna_and_ai_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            settings = public_link.Settings(data_dir=root, local_media_dir=root / "inbox")
            settings.ensure_dirs()
            with (
                unittest.mock.patch.object(
                    public_link,
                    "PublicPostPackageCollector",
                    FakePackageCollector,
                ),
                unittest.mock.patch.object(
                    public_link,
                    "analyze_content",
                    fake_analyze_content,
                ),
            ):
                report = public_link.analyze_public_link(
                    "https://www.instagram.com/reel/viral/",
                    niche="educação inclusiva",
                    settings=settings,
                )

            self.assertTrue(report.technical_analysis["link_only_mode"])
            self.assertEqual(
                report.technical_analysis["public_creator_baseline"]["status"],
                "BREAKOUT_FORTE",
            )
            self.assertTrue(report.technical_analysis["viral_dna"]["mechanics"])
            prompt = report.technical_analysis["replication_blueprint"]["ai_prompt"]
            self.assertIn("ORIGINAL", prompt)
            self.assertIn("educação inclusiva", prompt)
            self.assertEqual(report.technical_analysis["auto_collection"]["coverage_score"], 100)


if __name__ == "__main__":
    unittest.main()
