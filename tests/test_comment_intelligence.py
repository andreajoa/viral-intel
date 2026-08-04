from __future__ import annotations

import unittest

from app.analysis.comment_intelligence import analyze_comments


class CommentIntelligenceTests(unittest.TestCase):
    def test_extracts_intentions_mentions_questions_and_terms(self):
        comments = [
            {
                "author": "ana",
                "text": "Aconteceu comigo. Sinto muita saudade dele.",
                "likes": 18,
            },
            {
                "author": "bia",
                "text": "@carla você precisava ler isso. É exatamente assim!",
                "likes": 12,
            },
            {
                "author": "davi",
                "text": "Como superar um término assim? Me ajuda.",
                "likes": 5,
            },
            {
                "author": "ana",
                "text": "Eu já vivi essa dor.",
                "likes": 3,
            },
        ]

        result = analyze_comments(comments)

        self.assertTrue(result["available"])
        self.assertEqual(result["sample_size"], 4)
        self.assertEqual(result["unique_commenters"], 3)
        self.assertEqual(result["comments_with_mentions"], 1)
        self.assertEqual(result["questions"], 1)
        intents = {item["intent"]: item["count"] for item in result["intent_distribution"]}
        self.assertGreaterEqual(intents["identificação pessoal"], 2)
        self.assertGreaterEqual(intents["saudade ou luto"], 1)
        self.assertGreaterEqual(intents["pedido de orientação"], 1)
        self.assertEqual(result["top_comments_by_visible_likes"][0]["author"], "ana")

    def test_empty_sample_is_explicitly_unavailable(self):
        result = analyze_comments([])
        self.assertFalse(result["available"])
        self.assertEqual(result["sample_size"], 0)
        self.assertIn("não tenta descobrir identidades", result["privacy_note"])


if __name__ == "__main__":
    unittest.main()
