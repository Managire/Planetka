-- During beta, existing installs are treated as Pro installations.
-- Explicit Free editions will only be introduced by final Free packages later.

UPDATE cloud_session_refresh_tokens
SET install_edition = 'pro'
WHERE install_edition IS NULL OR TRIM(LOWER(install_edition)) = '' OR TRIM(LOWER(install_edition)) = 'free';
