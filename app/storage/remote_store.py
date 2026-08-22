"""Durable remote longitudinal store backed by the Viral Intel Cloudflare Worker."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import requests

from app.models import AnalysisEnvelope


class RemoteIntelligenceStore:
    """HTTP implementation of the longitudinal store contract.

    Requests are HMAC-signed with a short-lived timestamp. The Worker verifies the
    signature before any D1 access, so the shared secret never appears in URLs or
    persisted report payloads.
    """

    def __init__(self, base_url: str, secret: str, timeout: int = 20):
        self.base_url = base_url.strip().rstrip("/")
        self.secret = secret.strip()
        self.timeout = max(5, timeout)
        if not self.base_url.startswith("https://"):
            raise ValueError("CLOUDFLARE_MEMORY_URL deve usar HTTPS")
        if len(self.secret) < 24:
            raise ValueError("CLOUDFLARE_MEMORY_SECRET precisa ter pelo menos 24 caracteres")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))

    def _signature(self, method: str, path: str, timestamp: str, body: str) -> str:
        canonical = f"{timestamp}\n{method.upper()}\n{path}\n{body}".encode()
        return hmac.new(self.secret.encode(), canonical, hashlib.sha256).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = self._json(payload) if payload is not None else ""
        timestamp = str(int(time.time()))
        headers = {
            "Accept": "application/json",
            "X-VI-Timestamp": timestamp,
            "X-VI-Signature": self._signature(method, path, timestamp, body),
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = requests.request(
                method,
                self.base_url + path,
                data=body.encode() if payload is not None else None,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Cloudflare memory indisponível: {type(exc).__name__}: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Cloudflare memory retornou HTTP {response.status_code} sem JSON") from exc
        if response.status_code >= 400 or not data.get("ok", False):
            message = str(data.get("error") or f"HTTP {response.status_code}")[:300]
            raise RuntimeError(f"Cloudflare memory: {message}")
        return data

    def health(self) -> dict[str, Any]:
        try:
            response = requests.get(self.base_url + "/health", timeout=self.timeout)
            data = response.json()
            return data if isinstance(data, dict) else {"ok": False}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:180]}"}

    def save_report(
        self,
        report: AnalysisEnvelope,
        *,
        profile_key: str,
        post_key: str,
    ) -> None:
        if not profile_key.strip() or not post_key.strip():
            return
        self._request(
            "POST",
            "/v1/reports",
            payload={
                "report_id": report.report_id,
                "profile_key": profile_key.strip(),
                "post_key": post_key.strip(),
                "platform": report.metrics.platform.value,
                "format": report.metrics.format.value,
                "captured_at": report.metrics.captured_at.isoformat(),
                "generated_at": report.generated_at.isoformat(),
                "metrics": report.metrics.model_dump(mode="json"),
                "benchmark": report.benchmark.model_dump(mode="json"),
                "fingerprint": report.content_fingerprint,
                "envelope": report.model_dump(mode="json"),
            },
        )

    def comparable_reports(
        self,
        *,
        profile_key: str,
        platform: str,
        content_format: str,
        exclude_report_id: str = "",
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        query = urlencode(
            {
                "profile_key": profile_key,
                "platform": platform,
                "format": content_format,
                "exclude_report_id": exclude_report_id,
                "limit": max(1, min(limit, 1000)),
            }
        )
        data = self._request("GET", f"/v1/reports/comparable?{query}")
        rows = data.get("reports") or []
        return rows if isinstance(rows, list) else []

    def post_timeline(self, *, profile_key: str, post_key: str) -> list[dict[str, Any]]:
        query = urlencode({"profile_key": profile_key, "post_key": post_key})
        data = self._request("GET", f"/v1/posts/timeline?{query}")
        rows = data.get("timeline") or []
        return rows if isinstance(rows, list) else []

    def longitudinal_summary(self, *, profile_key: str, post_key: str) -> dict[str, Any]:
        timeline = self.post_timeline(profile_key=profile_key, post_key=post_key)
        if not timeline:
            return {"available": False, "snapshots": 0}
        first, last = timeline[0], timeline[-1]
        first_metrics = first.get("metrics") or {}
        last_metrics = last.get("metrics") or {}
        deltas: dict[str, float] = {}
        for name in ("views", "reach", "likes", "comments", "shares", "saves", "follows"):
            before, after = first_metrics.get(name), last_metrics.get(name)
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                deltas[name] = round(float(after) - float(before), 4)
        return {
            "available": len(timeline) >= 2,
            "snapshots": len(timeline),
            "first_captured_at": first.get("captured_at"),
            "last_captured_at": last.get("captured_at"),
            "deltas": deltas,
            "timeline": timeline[-12:],
        }

    def create_experiment(
        self,
        *,
        profile_key: str,
        hypothesis: str,
        change_one_thing: str,
        primary_metric: str,
        source_report_id: str = "",
    ) -> str:
        experiment_id = "exp_" + uuid.uuid4().hex[:12]
        data = self._request(
            "POST",
            "/v1/experiments",
            payload={
                "experiment_id": experiment_id,
                "profile_key": profile_key,
                "created_at": datetime.now(UTC).isoformat(),
                "hypothesis": hypothesis,
                "change_one_thing": change_one_thing,
                "primary_metric": primary_metric,
                "source_report_id": source_report_id or None,
            },
        )
        return str(data.get("experiment_id") or experiment_id)

    def complete_experiment(self, experiment_id: str, result: dict[str, Any]) -> None:
        self._request(
            "POST",
            f"/v1/experiments/{experiment_id}/complete",
            payload={"result": result},
        )
