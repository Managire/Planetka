-- Remove legacy refresh session mirror triggers.
-- They do not carry install_edition and reset beta Pro sessions back to Free.

DROP TRIGGER IF EXISTS trg_refresh_sessions_to_cloud_tokens_insert;
DROP TRIGGER IF EXISTS trg_refresh_sessions_to_cloud_tokens_update;
DROP TRIGGER IF EXISTS trg_cloud_tokens_to_refresh_sessions_insert;
DROP TRIGGER IF EXISTS trg_cloud_tokens_to_refresh_sessions_update;

UPDATE cloud_session_refresh_tokens
SET install_edition = 'pro'
WHERE install_edition IS NULL OR TRIM(LOWER(install_edition)) = '' OR TRIM(LOWER(install_edition)) = 'free';
