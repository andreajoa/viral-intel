import unittest

from app.online.instagram_embed import InstagramEmbedCollector


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class InstagramEmbedCollectorTests(unittest.TestCase):
    def test_reads_compact_like_and_comment_counts_from_public_embed(self):
        document = """
        <html><head>
          <meta property="og:description" content="33.8K likes, 132 comments - perfil on Instagram" />
          <script type="application/ld+json">
          {
            "@type": "ImageObject",
            "caption": "Você não perdeu qualquer pessoa",
            "datePublished": "2026-08-01T18:30:00Z",
            "author": {"@type": "Person", "alternateName": "@perfil"}
          }
          </script>
        </head><body></body></html>
        """
        session = FakeSession([FakeResponse(document)])
        collector = InstagramEmbedCollector(session=session)

        result = collector.collect("https://www.instagram.com/p/ABC123/")

        self.assertTrue(result["source_ok"])
        self.assertEqual(result["likes"], 33800)
        self.assertEqual(result["comments_count"], 132)
        self.assertEqual(result["caption"], "Você não perdeu qualquer pessoa")
        self.assertEqual(result["uploader"], "@perfil")
        self.assertEqual(len(session.calls), 1)

    def test_reads_json_counts_when_meta_description_is_absent(self):
        document = """
        <html><body>
          <script>window.__data={"like_count":12050,"comment_count":87,"video_view_count":90500,
          "username":"perfil_publico","caption":"Legenda pública"};</script>
        </body></html>
        """
        session = FakeSession([FakeResponse(document)])
        result = InstagramEmbedCollector(session=session).collect("https://www.instagram.com/reel/XYZ789/")

        self.assertTrue(result["source_ok"])
        self.assertEqual(result["likes"], 12050)
        self.assertEqual(result["comments_count"], 87)
        self.assertEqual(result["views"], 90500)
        self.assertEqual(result["uploader"], "perfil_publico")

    def test_http_failures_are_recoverable(self):
        session = FakeSession([FakeResponse("blocked", 429), FakeResponse("blocked", 429)])
        result = InstagramEmbedCollector(session=session).collect("https://www.instagram.com/p/ABC123/")

        self.assertFalse(result["source_ok"])
        self.assertIn("429", result["error"])


if __name__ == "__main__":
    unittest.main()
