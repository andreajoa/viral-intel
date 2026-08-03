import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Settings
from app.online.ytdlp_collector import YTDLPCollector


class CollectorTests(unittest.TestCase):
    def test_supported_url(self):
        url = "https://www.instagram.com/reel/abc123/"
        self.assertEqual(YTDLPCollector.validate_url(url), url)

    def test_rejects_local_or_unknown_urls(self):
        for url in ("file:///etc/passwd", "http://127.0.0.1/test", "https://example.com/video"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                YTDLPCollector.validate_url(url)

    def test_public_metadata_is_normalized_without_private_insights(self):
        captured_options = {}

        class YoutubeDL:
            def __init__(self, options):
                captured_options.update(options)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def extract_info(_url, download=False):
                self.assertFalse(download)
                return {
                    "extractor_key": "Instagram",
                    "id": "abc123",
                    "title": "Post público",
                    "description": "Legenda observada",
                    "view_count": 2500,
                    "like_count": 300,
                    "comment_count": 20,
                    "comments": [{"author": "pessoa", "text": "Comentário", "like_count": 4}],
                    "upload_date": "20260802",
                }

        fake_module = types.ModuleType("yt_dlp")
        fake_module.YoutubeDL = YoutubeDL
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(sys.modules, {"yt_dlp": fake_module}, clear=False),
        ):
            root = Path(temp)
            settings = Settings(data_dir=root / "data", local_media_dir=root / "media")
            result = YTDLPCollector(settings=settings).fetch_metadata("https://www.instagram.com/p/abc123/")

        self.assertTrue(result["source_ok"])
        self.assertEqual(result["views"], 2500)
        self.assertEqual(result["likes"], 300)
        self.assertEqual(result["comments_sample"][0]["text"], "Comentário")
        self.assertNotIn("saves", result)
        self.assertTrue(captured_options["skip_download"])

    def test_extractor_failure_becomes_recoverable_result(self):
        class YoutubeDL:
            def __init__(self, _options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def extract_info(_url, download=False):
                raise RuntimeError("plataforma bloqueou a coleta")

        fake_module = types.ModuleType("yt_dlp")
        fake_module.YoutubeDL = YoutubeDL
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(sys.modules, {"yt_dlp": fake_module}, clear=False),
        ):
            root = Path(temp)
            settings = Settings(data_dir=root / "data", local_media_dir=root / "media")
            result = YTDLPCollector(settings=settings).fetch_metadata("https://www.instagram.com/p/abc123/")

        self.assertFalse(result["source_ok"])
        self.assertIn("RuntimeError", result["error"])
        self.assertIn("Insights", result["source_notes"][0])


if __name__ == "__main__":
    unittest.main()
