from __future__ import annotations

import unittest

from app.online.tiktok_authorized import TikTokAuthorizedCollector


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeTikTokSession:
    def request(self, method, url, *, params, json, headers, timeout):
        del method, params, headers, timeout
        if url.endswith("/video/query/"):
            return FakeResponse(
                {
                    "data": {
                        "videos": [
                            {
                                "id": "123",
                                "share_url": "https://www.tiktok.com/@teste/video/123",
                                "video_description": "Teste",
                                "duration": 22,
                                "view_count": 5000,
                                "like_count": 400,
                                "comment_count": 30,
                                "share_count": 90,
                                "create_time": 1787420000,
                            }
                        ]
                    },
                    "error": {"code": "ok"},
                }
            )
        if url.endswith("/video/list/"):
            self.assert_max_count(json)
            return FakeResponse({"data": {"videos": [], "has_more": False}, "error": {"code": "ok"}})
        if url.endswith("/user/info/"):
            return FakeResponse(
                {
                    "data": {
                        "user": {
                            "open_id": "user-1",
                            "username": "teste",
                            "follower_count": 12000,
                        }
                    },
                    "error": {"code": "ok"},
                }
            )
        raise AssertionError(f"URL inesperada: {url}")

    @staticmethod
    def assert_max_count(payload):
        if not isinstance(payload, dict) or payload.get("max_count", 0) < 1:
            raise AssertionError("max_count ausente")


class TikTokAuthorizedCollectorTests(unittest.TestCase):
    def test_collect_maps_authorized_public_metrics(self):
        collector = TikTokAuthorizedCollector(
            "token-seguro",
            session=FakeTikTokSession(),
        )
        result = collector.collect(video_id="123")

        self.assertTrue(result["source_ok"])
        self.assertEqual(result["views"], 5000)
        self.assertEqual(result["shares"], 90)
        self.assertEqual(result["followers"], 12000)
        self.assertNotIn("average_watch_time_seconds", result)


if __name__ == "__main__":
    unittest.main()
