from __future__ import annotations

import unittest

from app.online.youtube_analytics import YouTubeAnalyticsCollector


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeYouTubeSession:
    def get(self, url, *, params, headers, timeout):
        del headers, timeout
        if url.endswith("/youtube/v3/videos"):
            return FakeResponse(
                {
                    "items": [
                        {
                            "id": "abc123",
                            "snippet": {
                                "title": "Teste YouTube",
                                "description": "Descrição",
                                "channelTitle": "Canal Teste",
                                "publishedAt": "2026-08-20T12:00:00Z",
                            },
                            "contentDetails": {"duration": "PT1M5S"},
                            "statistics": {},
                        }
                    ]
                }
            )
        if url.endswith("/youtube/v3/channels"):
            return FakeResponse(
                {
                    "items": [
                        {
                            "id": "channel-1",
                            "snippet": {"title": "Canal Teste", "customUrl": "@canalteste"},
                            "statistics": {"subscriberCount": "8000", "videoCount": "40"},
                        }
                    ]
                }
            )
        if url.endswith("/youtubeanalytics.googleapis.com/v2/reports"):
            metrics = str(params.get("metrics") or "")
            if "videoThumbnailImpressions" in metrics:
                return FakeResponse(
                    {
                        "columnHeaders": [
                            {"name": "videoThumbnailImpressions"},
                            {"name": "videoThumbnailImpressionsClickRate"},
                        ],
                        "rows": [[12000, 5.4]],
                    }
                )
            return FakeResponse(
                {
                    "columnHeaders": [
                        {"name": "views"},
                        {"name": "likes"},
                        {"name": "comments"},
                        {"name": "shares"},
                        {"name": "averageViewDuration"},
                        {"name": "averageViewPercentage"},
                        {"name": "subscribersGained"},
                    ],
                    "rows": [[9000, 700, 60, 110, 41.2, 63.4, 35]],
                }
            )
        raise AssertionError(f"URL inesperada: {url}")


class YouTubeAnalyticsCollectorTests(unittest.TestCase):
    def test_collect_maps_watch_time_and_conversion(self):
        collector = YouTubeAnalyticsCollector(
            "oauth-token",
            session=FakeYouTubeSession(),
        )
        result = collector.collect(video_id="abc123")

        self.assertTrue(result["source_ok"])
        self.assertEqual(result["views"], 9000)
        self.assertEqual(result["average_watch_time_seconds"], 41.2)
        self.assertEqual(result["average_view_percentage"], 63.4)
        self.assertEqual(result["follows"], 35)
        self.assertEqual(result["duration_seconds"], 65.0)
        self.assertEqual(result["impressions"], 12000)


if __name__ == "__main__":
    unittest.main()
