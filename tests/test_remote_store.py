from __future__ import annotations

import hashlib
import hmac
import unittest
from unittest.mock import Mock, patch

from app.storage.remote_store import RemoteIntelligenceStore


class RemoteStoreTests(unittest.TestCase):
    def setUp(self):
        self.secret = "test-secret-that-is-definitely-long-enough"
        self.store = RemoteIntelligenceStore(
            "https://memory.example.workers.dev",
            self.secret,
        )

    def test_signature_matches_canonical_hmac(self):
        timestamp = "1787428800"
        path = "/v1/reports/comparable?profile_key=p1"
        canonical = f"{timestamp}\nGET\n{path}\n".encode()
        expected = hmac.new(self.secret.encode(), canonical, hashlib.sha256).hexdigest()
        actual = self.store._signature("GET", path, timestamp, "")
        self.assertEqual(actual, expected)

    def test_rejects_insecure_memory_url(self):
        with self.assertRaises(ValueError):
            RemoteIntelligenceStore("http://localhost:8787", self.secret)

    @patch("app.storage.remote_store.requests.request")
    def test_comparable_reports_returns_remote_rows(self, request: Mock):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "ok": True,
            "reports": [{"report_id": "vi_1", "metrics": {"views": 1000}}],
        }
        request.return_value = response

        rows = self.store.comparable_reports(
            profile_key="instagram:@teste",
            platform="instagram",
            content_format="reel",
        )

        self.assertEqual(rows[0]["report_id"], "vi_1")
        headers = request.call_args.kwargs["headers"]
        self.assertIn("X-VI-Timestamp", headers)
        self.assertRegex(headers["X-VI-Signature"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
