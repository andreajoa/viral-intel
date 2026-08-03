"""Compatibility alias for the evidence-safe public collector.

The old implementation scraped private-looking profile details with Instaloader and
was not used by the main pipeline.  Profile analysis now uses an explicit CSV of the
owner's Insights, while this class returns only public, best-effort metadata.
"""

from __future__ import annotations

from app.online.ytdlp_collector import YTDLPCollector


class DeepCollector(YTDLPCollector):
    def collect(self, url: str):
        return self.fetch_metadata(url)
