from __future__ import annotations

import unittest

from app.analysis.semantic_comments import _cluster, _cosine, _normalize


class SemanticCommentTests(unittest.TestCase):
    def test_cosine_normalization_is_deterministic(self):
        left = _normalize([3.0, 4.0])
        right = _normalize([6.0, 8.0])
        self.assertAlmostEqual(_cosine(left, right), 1.0, places=6)

    def test_cluster_separates_semantically_distant_vectors(self):
        vectors = [
            [1.0, 0.0, 0.0],
            [0.98, 0.02, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.97, 0.03],
        ]
        clusters = _cluster(vectors, threshold=0.9)
        sizes = sorted(len(cluster) for cluster in clusters)
        self.assertEqual(sizes, [2, 2])


if __name__ == "__main__":
    unittest.main()
