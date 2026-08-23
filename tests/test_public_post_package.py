from __future__ import annotations

import unittest

from app.online.public_post_package import _media_candidates


class PublicPostPackageTests(unittest.TestCase):
    def test_prefers_video_and_preserves_carousel_order(self):
        raw = {
            "childPosts": [
                {"displayUrl": "https://cdn.example/slide1.jpg"},
                {
                    "videoUrl": "https://cdn.example/slide2.mp4",
                    "displayUrl": "https://cdn.example/slide2.jpg",
                },
                {"displayUrl": "https://cdn.example/slide3.webp"},
            ]
        }

        self.assertEqual(
            _media_candidates(raw),
            [
                "https://cdn.example/slide1.jpg",
                "https://cdn.example/slide2.mp4",
                "https://cdn.example/slide3.webp",
            ],
        )

    def test_single_reel_uses_video_url(self):
        raw = {
            "videoUrl": "https://cdn.example/reel.mp4",
            "displayUrl": "https://cdn.example/cover.jpg",
        }
        self.assertEqual(_media_candidates(raw), ["https://cdn.example/reel.mp4"])


if __name__ == "__main__":
    unittest.main()
