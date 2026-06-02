-- Treat all existing non-blocked users as paid/full-access Commercial customers.
-- Blocked accounts remain blocked.
UPDATE users
SET status = 'commercial'
WHERE LOWER(TRIM(COALESCE(status, ''))) != 'blocked';
