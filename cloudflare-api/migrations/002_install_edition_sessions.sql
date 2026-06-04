-- Add package edition metadata to refresh sessions.
-- The addon has two distributable editions, Free and Pro. The install/session token
-- carries this edition so backend catalogue/data routes can branch by package later.

ALTER TABLE cloud_session_refresh_tokens ADD COLUMN install_edition TEXT NOT NULL DEFAULT 'free';
ALTER TABLE cloud_session_refresh_tokens ADD COLUMN edition_signature TEXT;
CREATE INDEX IF NOT EXISTS idx_cloud_session_refresh_tokens_edition ON cloud_session_refresh_tokens(install_edition);
