CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR REPLACE INTO metadata(key, value) VALUES ('schema_version', '1');

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
