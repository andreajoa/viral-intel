import unittest

from app.ai.schema import validate_evidence_references
from app.ai.strategist import deterministic_strategy
from app.analysis.evidence import build_evidence
from app.analysis.metrics import assess_data_quality, derive_metrics
from app.analysis.profile import build_benchmark
from app.models import PostMetrics


class EvidenceGuardrailTests(unittest.TestCase):
    def test_invalid_reference_downgrades_hypothesis(self):
        metrics = PostMetrics(platform="instagram", format="reel", views=1000, likes=50)
        benchmark = build_benchmark(metrics, [])
        quality = assess_data_quality(metrics, 0)
        evidence = build_evidence(metrics, derive_metrics(metrics), benchmark, quality, {})
        report = deterministic_strategy(metrics, benchmark, quality, evidence, {}, "autismo")
        report.root_cause_hypotheses[0].evidence_refs = ["O999"]
        report.root_cause_hypotheses[0].judgment = "SUSTENTADA"
        report.root_cause_hypotheses[0].confidence = 99

        checked = validate_evidence_references(report, {item.id for item in evidence})
        hypothesis = checked.root_cause_hypotheses[0]
        self.assertEqual(hypothesis.judgment, "NÃO_AVALIÁVEL")
        self.assertEqual(hypothesis.confidence, 0)
        self.assertEqual(hypothesis.evidence_refs, [])


if __name__ == "__main__":
    unittest.main()
