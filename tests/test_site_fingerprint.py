from __future__ import annotations

import unittest

from cloud.site_fingerprint import compare_fingerprints, fingerprint_bytes


class SiteFingerprintTests(unittest.TestCase):
    def test_ignores_inline_runtime_tokens_and_query_strings(self) -> None:
        baseline = b"""<!doctype html>
        <html><head><title>Andre Almeida</title>
        <link rel='stylesheet' href='/_next/static/app.css?v=111'>
        <script>window.__NEXT_DATA__ = {'requestId':'abc','time':1}</script>
        </head><body><main><h1>Websites profissionais</h1>
        <a href='/portfolio?utm_source=a'>Portfolio</a>
        <img src='/hero.webp?v=1'></main></body></html>"""
        current = b"""<!doctype html>
        <html><head><title>Andre Almeida</title>
        <link rel='stylesheet' href='/_next/static/app.css?v=999'>
        <script>window.__NEXT_DATA__ = {'requestId':'xyz','time':2}</script>
        </head><body><main><h1>Websites profissionais</h1>
        <a href='/portfolio?utm_source=b'>Portfolio</a>
        <img src='/hero.webp?v=2'></main></body></html>"""

        baseline_fp = fingerprint_bytes(baseline, "andre-almeida.online")
        current_fp = fingerprint_bytes(current, "andre-almeida.online")

        self.assertEqual([], compare_fingerprints(baseline_fp, current_fp))

    def test_detects_visible_content_replacement(self) -> None:
        baseline = fingerprint_bytes(
            b"<html><head><title>Andre</title></head><body><h1>Original</h1></body></html>",
            "andre-almeida.online",
        )
        current = fingerprint_bytes(
            b"<html><head><title>Andre</title></head><body><h1>Replacement</h1></body></html>",
            "andre-almeida.online",
        )

        errors = compare_fingerprints(baseline, current)

        self.assertIn("visible_text_sha256 changed", errors)

    def test_detects_internal_navigation_change(self) -> None:
        baseline = fingerprint_bytes(
            b"<html><body><a href='/portfolio'>Portfolio</a></body></html>",
            "andre-almeida.online",
        )
        current = fingerprint_bytes(
            b"<html><body><a href='/loja'>Portfolio</a></body></html>",
            "andre-almeida.online",
        )

        errors = compare_fingerprints(baseline, current)

        self.assertIn("internal_links_sha256 changed", errors)

    def test_detects_structural_change_even_with_same_text(self) -> None:
        baseline = fingerprint_bytes(
            b"<html><body><main><p>Same text</p></main></body></html>",
            "andre-almeida.online",
        )
        current = fingerprint_bytes(
            b"<html><body><section><p>Same text</p></section></body></html>",
            "andre-almeida.online",
        )

        errors = compare_fingerprints(baseline, current)

        self.assertIn("tag_skeleton_sha256 changed", errors)


if __name__ == "__main__":
    unittest.main()
