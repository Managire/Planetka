-- Canonical licence migration: old account names -> Personal / Commercial.
-- Run before deploying workers that no longer accept old licence codes.

UPDATE users
SET status = 'commercial'
WHERE LOWER(TRIM(COALESCE(status, ''))) IN ('pro', 'professional', 'paid', 'unlimited');

UPDATE users
SET status = 'personal'
WHERE LOWER(TRIM(COALESCE(status, ''))) IN ('free', '') OR status IS NULL;

UPDATE api_keys
SET plan_code = 'commercial'
WHERE LOWER(TRIM(COALESCE(plan_code, ''))) IN ('pro', 'professional', 'paid', 'unlimited');

UPDATE api_keys
SET plan_code = 'personal'
WHERE LOWER(TRIM(COALESCE(plan_code, ''))) IN ('free', '') OR plan_code IS NULL;

UPDATE api_key_requests
SET requested_plan = 'commercial'
WHERE LOWER(TRIM(COALESCE(requested_plan, ''))) IN ('pro', 'professional', 'paid', 'unlimited');

UPDATE api_key_requests
SET requested_plan = 'personal'
WHERE LOWER(TRIM(COALESCE(requested_plan, ''))) IN ('free', '') OR requested_plan IS NULL;
