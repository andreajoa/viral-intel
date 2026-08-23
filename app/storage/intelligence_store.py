"""SQLite-backed longitudinal intelligence store.

The store is deliberately dependency-free so Viral Intel remains runnable on a Mac and
in tests. It persists only when Settings.persistence_active is true; ephemeral cloud
runs never write durable profile history. The schema is versioned and can later be
migrated to Postgres without changing the analysis interfaces.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.models import AnalysisEnvelope

SCHEMA_VERSION = 1


class IntelligenceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=20000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    profile_key TEXT NOT NULL,
                    post_key TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    format TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    benchmark_json TEXT NOT NULL,
                    fingerprint_json TEXT NOT NULL,
                    envelope_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_reports_profile_format
                    ON reports(profile_key, platform, format, captured_at DESC);
                CREATE INDEX IF NOT EXISTS idx_reports_post
                    ON reports(profile_key, post_key, captured_at ASC);

                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    profile_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    change_one_thing TEXT NOT NULL,
                    primary_metric TEXT NOT NULL,
                    source_report_id TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_experiments_profile
                    ON experiments(profile_key, created_at DESC);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))

    def save_report(
        self,
        report: AnalysisEnvelope,
        *,
        profile_key: str,
        post_key: str,
    ) -> None:
        if not profile_key.strip() or not post_key.strip():
            return
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO reports(
                    report_id, profile_key, post_key, platform, format, captured_at,
                    generated_at, metrics_json, benchmark_json, fingerprint_json, envelope_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    profile_key.strip(),
                    post_key.strip(),
                    report.metrics.platform.value,
                    report.metrics.format.value,
                    report.metrics.captured_at.isoformat(),
                    report.generated_at.isoformat(),
                    self._json(report.metrics.model_dump(mode="json")),
                    self._json(report.benchmark.model_dump(mode="json")),
                    self._json(report.content_fingerprint),
                    report.model_dump_json(),
                ),
            )
            connection.commit()

    def comparable_reports(
        self,
        *,
        profile_key: str,
        platform: str,
        content_format: str,
        exclude_report_id: str = "",
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT report_id, post_key, captured_at, metrics_json, benchmark_json, fingerprint_json "
            "FROM reports WHERE profile_key=? AND platform=? AND format=?"
        )
        params: list[Any] = [profile_key, platform, content_format]
        if exclude_report_id:
            query += " AND report_id<>?"
            params.append(exclude_report_id)
        query += " ORDER BY captured_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with closing(self._connect()) as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "report_id": row["report_id"],
                "post_id": row["post_key"],
                "captured_at": row["captured_at"],
                "metrics": json.loads(row["metrics_json"]),
                "benchmark": json.loads(row["benchmark_json"]),
                "fingerprint": json.loads(row["fingerprint_json"]),
            }
            for row in rows
        ]

    def post_timeline(self, *, profile_key: str, post_key: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT report_id, captured_at, metrics_json, benchmark_json
                FROM reports
                WHERE profile_key=? AND post_key=?
                ORDER BY captured_at ASC
                """,
                (profile_key, post_key),
            ).fetchall()
        return [
            {
                "report_id": row["report_id"],
                "captured_at": row["captured_at"],
                "metrics": json.loads(row["metrics_json"]),
                "benchmark": json.loads(row["benchmark_json"]),
            }
            for row in rows
        ]

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
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO experiments(
                    experiment_id, profile_key, created_at, status, hypothesis,
                    change_one_thing, primary_metric, source_report_id, result_json
                ) VALUES (?, ?, ?, 'PLANNED', ?, ?, ?, ?, '{}')
                """,
                (
                    experiment_id,
                    profile_key,
                    datetime.now(UTC).isoformat(),
                    hypothesis,
                    change_one_thing,
                    primary_metric,
                    source_report_id or None,
                ),
            )
            connection.commit()
        return experiment_id

    def complete_experiment(self, experiment_id: str, result: dict[str, Any]) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE experiments SET status='COMPLETED', result_json=? WHERE experiment_id=?",
                (self._json(result), experiment_id),
            )
            connection.commit()
