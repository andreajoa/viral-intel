from __future__ import annotations

import unittest
from typing import Any

from app.online.instagram_graph import InstagramGraphCollector


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeSession:
    def get(self, url: str, params: dict[str, Any], timeout: int) -> FakeResponse:
        del timeout
        if url.endswith("/media-1"):
            return FakeResponse(
                {
                    "id": "media-1",
                    "caption": "Uma frase emocional",
                    "media_type": "IMAGE",
                    "media_product_type": "FEED",
                    "permalink": "https://www.instagram.com/p/teste/",
                    "timestamp": "2026-08-04T18:00:00+0000",
                    "username": "perfil_teste",
                    "like_count": 33800,
                    "comments_count": 132,
                }
            )
        if url.endswith("/user-1"):
            return FakeResponse(
                {
                    "id": "user-1",
                    "username": "perfil_teste",
                    "name": "Perfil Teste",
                    "biography": "Frases e reflexões",
                    "followers_count": 14000,
                    "follows_count": 200,
                    "media_count": 300,
                }
            )
        if url.endswith("/media-1/comments"):
            return FakeResponse(
                {
                    "data": [
                        {
                            "id": "c1",
                            "text": "Aconteceu comigo",
                            "timestamp": "2026-08-04T19:00:00+0000",
                            "like_count": 22,
                            "from": {"id": "u1", "username": "ana"},
                        }
                    ]
                }
            )
        if url.endswith("/media-1/insights"):
            metric = params.get("metric")
            values = {
                "views": 150000,
                "reach": 120000,
                "impressions": 160000,
                "likes": 33800,
                "comments": 132,
                "shares": 5400,
                "saved": 3100,
                "total_interactions": 42432,
                "follows": 640,
                "profile_visits": 4200,
            }
            if metric in values:
                return FakeResponse(
                    {"data": [{"name": metric, "values": [{"value": values[metric]}]}]}
                )
            return FakeResponse(
                {"error": {"message": "Métrica indisponível", "code": 100}},
                status_code=400,
            )
        raise AssertionError(f"URL não esperada: {url}")


class InstagramGraphCollectorTests(unittest.TestCase):
    def test_collects_owned_media_insights_account_and_comments(self):
        collector = InstagramGraphCollector(
            access_token="token-secreto",
            ig_user_id="user-1",
            session=FakeSession(),
        )

        result = collector.collect(media_id="media-1")

        self.assertTrue(result["source_ok"])
        self.assertEqual(result["collection_source"], "meta/instagram-graph-authorized")
        self.assertEqual(result["reach"], 120000)
        self.assertEqual(result["shares"], 5400)
        self.assertEqual(result["saves"], 3100)
        self.assertEqual(result["account"]["followers_count"], 14000)
        self.assertEqual(result["comments_sample"][0]["author"], "ana")
        self.assertNotIn("token-secreto", " ".join(result["source_notes"]))

    def test_missing_token_is_explicit(self):
        collector = InstagramGraphCollector(access_token="")
        result = collector.collect(media_id="media-1")
        self.assertFalse(result["source_ok"])
        self.assertIn("não configurado", result["error"])


if __name__ == "__main__":
    unittest.main()
