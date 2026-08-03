import unittest

from app.online.ytdlp_collector import YTDLPCollector


class CollectorTests(unittest.TestCase):
    def test_supported_url(self):
        url = "https://www.instagram.com/reel/abc123/"
        self.assertEqual(YTDLPCollector.validate_url(url), url)

    def test_rejects_local_or_unknown_urls(self):
        for url in ("file:///etc/passwd", "http://127.0.0.1/test", "https://example.com/video"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                YTDLPCollector.validate_url(url)


if __name__ == "__main__":
    unittest.main()
