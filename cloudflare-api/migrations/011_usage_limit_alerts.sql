CREATE TABLE IF NOT EXISTS usage_limit_alerts (
  key TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  install_id TEXT NOT NULL,
  install_email TEXT,
  install_edition TEXT NOT NULL,
  alert_kind TEXT NOT NULL,
  period_start_unix INTEGER NOT NULL,
  used_bytes INTEGER NOT NULL,
  limit_bytes INTEGER NOT NULL,
  blocked INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_usage_limit_alerts_install_created
ON usage_limit_alerts(install_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_usage_limit_alerts_kind_created
ON usage_limit_alerts(alert_kind, created_at DESC);
