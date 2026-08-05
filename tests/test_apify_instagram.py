import unittest

from app.online.apify_instagram import ApifyInstagramCollector


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class ApifyInstagramCollectorTests(unittest.TestCase):
    def test_collects_public_post_metrics_account_and_comments(self):
        session = FakeSession(
            [
                FakeResponse(
                    [
                        {
                            "id": "post-1",
                            "shortCode": "ABC123",
                            "url": "https://www.instagram.com/p/ABC123/",
                            "caption": "Legenda pública",
                            "likesCount": 33800,
                            "commentsCount": 132,
                            "repostsCount": 5400,
                            "timestamp": "2026-08-01T18:30:00.000Z",
                            "ownerUsername": "perfil_publico",
                            "ownerFullName": "Perfil Público",
                            "ownerId": "owner-1",
                            "ownerFollowersCount": 250000,
                        }
                    ]
                ),
                FakeResponse(
                    [
                        {
                            "id": "comment-1",
                            "text": "Isso aconteceu comigo",
                            "likesCount": 18,
                            "timestamp": "2026-08-02T10:00:00.000Z",
                            "owner": {"id": "person-1", "username": "pessoa"},
                        }
                    ]
                ),
            ]
        )
        collector = ApifyInstagramCollector(
            api_token="token",
            max_comments=50,
            session=session,
        )

        result = collector.collect("https://www.instagram.com/p/ABC123/")

        self.assertTrue(result["source_ok"])
        self.assertEqual(result["likes"], 33800)
        self.assertEqual(result["comments_count"], 132)
        self.assertEqual(result["reposts"], 5400)
        self.assertEqual(result["followers"], 250000)
        self.assertEqual(result["comments_sample"][0]["author"], "pessoa")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0][1]["json"]["resultsType"], "posts")
        self.assertEqual(session.calls[1][1]["json"]["resultsType"], "comments")

    def test_missing_token_is_explicit(self):
        result = ApifyInstagramCollector(api_token="").collect("https://www.instagram.com/p/ABC123/")
        self.assertFalse(result["source_ok"])
        self.assertIn("APIFY_API_TOKEN", result["error"])

    def test_rejects_profile_url_when_post_is_required(self):
        collector = ApifyInstagramCollector(api_token="token")
        with self.assertRaises(ValueError):
            collector.validate_url("https://www.instagram.com/perfil/")


if __name__ == "__main__":
    unittest.main()
