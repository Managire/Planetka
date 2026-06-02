-- Current Planetka Cloud identity model: anonymous installs + refresh-token sessions.
-- This migration creates clean table names while keeping the previous table names
-- available during deployment cutover. Historical event columns such as user_id
-- are intentionally left unchanged.

CREATE TABLE IF NOT EXISTS cloud_installs (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  last_login_at TEXT,
  terms_accepted_at TEXT,
  privacy_accepted_at TEXT,
  terms_version TEXT,
  privacy_version TEXT,
  preview_fair_usage_hold_at TEXT,
  preview_fair_usage_hold_reason TEXT,
  preview_fair_usage_hold_details_json TEXT
);

INSERT OR IGNORE INTO cloud_installs (
  id, email, status, created_at, last_login_at,
  terms_accepted_at, privacy_accepted_at, terms_version, privacy_version,
  preview_fair_usage_hold_at, preview_fair_usage_hold_reason, preview_fair_usage_hold_details_json
)
SELECT
  id, email, status, created_at, last_login_at,
  terms_accepted_at, privacy_accepted_at, terms_version, privacy_version,
  preview_fair_usage_hold_at, preview_fair_usage_hold_reason, preview_fair_usage_hold_details_json
FROM users;

CREATE INDEX IF NOT EXISTS idx_cloud_installs_email ON cloud_installs(email);
CREATE INDEX IF NOT EXISTS idx_cloud_installs_status ON cloud_installs(status);
CREATE INDEX IF NOT EXISTS idx_cloud_installs_last_login ON cloud_installs(last_login_at DESC);

CREATE TABLE IF NOT EXISTS cloud_session_refresh_tokens (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  refresh_token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  created_at TEXT NOT NULL,
  auth_method TEXT,
  device_id TEXT,
  client_ip_scope TEXT
);

INSERT OR IGNORE INTO cloud_session_refresh_tokens (
  id, user_id, refresh_token_hash, expires_at, revoked_at, created_at,
  auth_method, device_id, client_ip_scope
)
SELECT
  id, user_id, refresh_token_hash, expires_at, revoked_at, created_at,
  auth_method, device_id, client_ip_scope
FROM refresh_sessions;

CREATE INDEX IF NOT EXISTS idx_cloud_session_refresh_tokens_user ON cloud_session_refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_cloud_session_refresh_tokens_hash ON cloud_session_refresh_tokens(refresh_token_hash);
CREATE INDEX IF NOT EXISTS idx_cloud_session_refresh_tokens_device ON cloud_session_refresh_tokens(device_id);

CREATE TRIGGER IF NOT EXISTS trg_users_to_cloud_installs_insert
AFTER INSERT ON users
BEGIN
  INSERT OR REPLACE INTO cloud_installs (
    id, email, status, created_at, last_login_at,
    terms_accepted_at, privacy_accepted_at, terms_version, privacy_version,
    preview_fair_usage_hold_at, preview_fair_usage_hold_reason, preview_fair_usage_hold_details_json
  ) VALUES (
    NEW.id, NEW.email, NEW.status, NEW.created_at, NEW.last_login_at,
    NEW.terms_accepted_at, NEW.privacy_accepted_at, NEW.terms_version, NEW.privacy_version,
    NEW.preview_fair_usage_hold_at, NEW.preview_fair_usage_hold_reason, NEW.preview_fair_usage_hold_details_json
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_users_to_cloud_installs_update
AFTER UPDATE ON users
BEGIN
  INSERT OR REPLACE INTO cloud_installs (
    id, email, status, created_at, last_login_at,
    terms_accepted_at, privacy_accepted_at, terms_version, privacy_version,
    preview_fair_usage_hold_at, preview_fair_usage_hold_reason, preview_fair_usage_hold_details_json
  ) VALUES (
    NEW.id, NEW.email, NEW.status, NEW.created_at, NEW.last_login_at,
    NEW.terms_accepted_at, NEW.privacy_accepted_at, NEW.terms_version, NEW.privacy_version,
    NEW.preview_fair_usage_hold_at, NEW.preview_fair_usage_hold_reason, NEW.preview_fair_usage_hold_details_json
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_cloud_installs_to_users_insert
AFTER INSERT ON cloud_installs
BEGIN
  INSERT OR REPLACE INTO users (
    id, email, status, created_at, last_login_at,
    terms_accepted_at, privacy_accepted_at, terms_version, privacy_version,
    preview_fair_usage_hold_at, preview_fair_usage_hold_reason, preview_fair_usage_hold_details_json
  ) VALUES (
    NEW.id, NEW.email, NEW.status, NEW.created_at, NEW.last_login_at,
    NEW.terms_accepted_at, NEW.privacy_accepted_at, NEW.terms_version, NEW.privacy_version,
    NEW.preview_fair_usage_hold_at, NEW.preview_fair_usage_hold_reason, NEW.preview_fair_usage_hold_details_json
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_cloud_installs_to_users_update
AFTER UPDATE ON cloud_installs
BEGIN
  INSERT OR REPLACE INTO users (
    id, email, status, created_at, last_login_at,
    terms_accepted_at, privacy_accepted_at, terms_version, privacy_version,
    preview_fair_usage_hold_at, preview_fair_usage_hold_reason, preview_fair_usage_hold_details_json
  ) VALUES (
    NEW.id, NEW.email, NEW.status, NEW.created_at, NEW.last_login_at,
    NEW.terms_accepted_at, NEW.privacy_accepted_at, NEW.terms_version, NEW.privacy_version,
    NEW.preview_fair_usage_hold_at, NEW.preview_fair_usage_hold_reason, NEW.preview_fair_usage_hold_details_json
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_refresh_sessions_to_cloud_tokens_insert
AFTER INSERT ON refresh_sessions
BEGIN
  INSERT OR REPLACE INTO cloud_session_refresh_tokens (
    id, user_id, refresh_token_hash, expires_at, revoked_at, created_at,
    auth_method, device_id, client_ip_scope
  ) VALUES (
    NEW.id, NEW.user_id, NEW.refresh_token_hash, NEW.expires_at, NEW.revoked_at, NEW.created_at,
    NEW.auth_method, NEW.device_id, NEW.client_ip_scope
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_refresh_sessions_to_cloud_tokens_update
AFTER UPDATE ON refresh_sessions
BEGIN
  INSERT OR REPLACE INTO cloud_session_refresh_tokens (
    id, user_id, refresh_token_hash, expires_at, revoked_at, created_at,
    auth_method, device_id, client_ip_scope
  ) VALUES (
    NEW.id, NEW.user_id, NEW.refresh_token_hash, NEW.expires_at, NEW.revoked_at, NEW.created_at,
    NEW.auth_method, NEW.device_id, NEW.client_ip_scope
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_cloud_tokens_to_refresh_sessions_insert
AFTER INSERT ON cloud_session_refresh_tokens
BEGIN
  INSERT OR REPLACE INTO refresh_sessions (
    id, user_id, refresh_token_hash, expires_at, revoked_at, created_at,
    auth_method, device_id, client_ip_scope
  ) VALUES (
    NEW.id, NEW.user_id, NEW.refresh_token_hash, NEW.expires_at, NEW.revoked_at, NEW.created_at,
    NEW.auth_method, NEW.device_id, NEW.client_ip_scope
  );
END;

CREATE TRIGGER IF NOT EXISTS trg_cloud_tokens_to_refresh_sessions_update
AFTER UPDATE ON cloud_session_refresh_tokens
BEGIN
  INSERT OR REPLACE INTO refresh_sessions (
    id, user_id, refresh_token_hash, expires_at, revoked_at, created_at,
    auth_method, device_id, client_ip_scope
  ) VALUES (
    NEW.id, NEW.user_id, NEW.refresh_token_hash, NEW.expires_at, NEW.revoked_at, NEW.created_at,
    NEW.auth_method, NEW.device_id, NEW.client_ip_scope
  );
END;

CREATE TABLE IF NOT EXISTS tile_request_rollup_hourly_account (
  bucket_start_unix INTEGER NOT NULL,
  bucket_start TEXT NOT NULL,
  user_id TEXT NOT NULL,
  user_email TEXT,
  request_count INTEGER NOT NULL DEFAULT 0,
  bytes_served INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  cache_hit_count INTEGER NOT NULL DEFAULT 0,
  tagged_request_count INTEGER NOT NULL DEFAULT 0,
  last_event_unix INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket_start_unix, user_id)
);

CREATE TABLE IF NOT EXISTS tile_request_rollup_hourly_install (
  bucket_start_unix INTEGER NOT NULL,
  bucket_start TEXT NOT NULL,
  user_id TEXT NOT NULL,
  user_email TEXT,
  request_count INTEGER NOT NULL DEFAULT 0,
  bytes_served INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  cache_hit_count INTEGER NOT NULL DEFAULT 0,
  tagged_request_count INTEGER NOT NULL DEFAULT 0,
  last_event_unix INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (bucket_start_unix, user_id)
);

INSERT OR IGNORE INTO tile_request_rollup_hourly_install (
  bucket_start_unix, bucket_start, user_id, user_email, request_count, bytes_served,
  error_count, cache_hit_count, tagged_request_count, last_event_unix
)
SELECT
  bucket_start_unix, bucket_start, user_id, user_email, request_count, bytes_served,
  error_count, cache_hit_count, tagged_request_count, last_event_unix
FROM tile_request_rollup_hourly_account;

CREATE TABLE IF NOT EXISTS tile_request_rollup_daily_account (
  day_start_unix INTEGER NOT NULL,
  day_start TEXT NOT NULL,
  user_id TEXT NOT NULL,
  user_email TEXT,
  request_count INTEGER NOT NULL DEFAULT 0,
  bytes_served INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  cache_hit_count INTEGER NOT NULL DEFAULT 0,
  tagged_request_count INTEGER NOT NULL DEFAULT 0,
  last_event_unix INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day_start_unix, user_id)
);

CREATE TABLE IF NOT EXISTS tile_request_rollup_daily_install (
  day_start_unix INTEGER NOT NULL,
  day_start TEXT NOT NULL,
  user_id TEXT NOT NULL,
  user_email TEXT,
  request_count INTEGER NOT NULL DEFAULT 0,
  bytes_served INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  cache_hit_count INTEGER NOT NULL DEFAULT 0,
  tagged_request_count INTEGER NOT NULL DEFAULT 0,
  last_event_unix INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day_start_unix, user_id)
);

INSERT OR IGNORE INTO tile_request_rollup_daily_install (
  day_start_unix, day_start, user_id, user_email, request_count, bytes_served,
  error_count, cache_hit_count, tagged_request_count, last_event_unix
)
SELECT
  day_start_unix, day_start, user_id, user_email, request_count, bytes_served,
  error_count, cache_hit_count, tagged_request_count, last_event_unix
FROM tile_request_rollup_daily_account;
