-- The current access model only uses active/blocked install status.
-- Old account/licence labels such as personal/commercial/pro/free are normalized to active.

UPDATE cloud_installs
SET status = 'active'
WHERE status IS NULL OR TRIM(LOWER(status)) NOT IN ('active', 'blocked');
