# Account Tier Integrity

## Goal
Planetka account tier must be identical across all surfaces:

- `users.status` in D1 (source of truth)
- Analytics account list tier display
- Blender addon Account panel tier display

No code path is allowed to silently coerce/replace/fallback tier values.

## Canonical Field
Canonical tier field:

- `users.status`

Canonical tier values:

- `free`
- `personal`
- `commercial`

Operational non-tier status:

- `blocked` (account access state, not a licence tier)

## Read Path (DB -> Analytics/UI)
### Analytics
- Account list query reads raw normalized status with no fallback:
  - `cloudflare-api/src/worker/admin_analytics_queries.js` (`listAnalyticsUsers`)
- Tier rendering maps only known values and marks anything else as invalid:
  - `cloudflare-api/src/worker/admin_analytics_handlers.js`
  - `cloudflare-api/src/admin_analytics_page.js`

### Blender Addon
- Auth payload stores canonical stored plan/tier fields as received from API:
  - `auth.py` (`_apply_auth_payload`, `_apply_account_profile_fields`)
- UI tier label reads canonical stored tier only (no implicit free fallback):
  - `auth.py` (`get_account_tier`)
  - `ui.py` (`_draw_account_panel`)

### API Account Serialization
- Account payload uses strict tier normalization and emits empty values on invalid input (never implicit free):
  - `cloudflare-api/src/index.js` (`serializeAccountState`)
- Account state build fails on invalid user status:
  - `cloudflare-api/src/index.js` (`buildAccountState`)

## Allowed Tier Mutation Paths
Tier changes are allowed only in these paths:

1. Account creation (new user insert only)
- `cloudflare-api/src/index.js` (`upsertUserByEmail`) inserts `users.status` for new users.
- Existing users are not re-tiered in `upsertUserByEmail`.

2. Explicit manual/admin intervention
- `cloudflare-api/src/worker/admin_user_handlers.js`
  - `handleAdminUserSetPlan`
  - `handleAdminUserUnblock`
  - `handleAdminUserBlock` / `handleAdminUserHardBlock` (blocked state)

## Explicitly Disallowed
- Defaulting missing/invalid tier to `free`.
- Substituting `personal` on unblock when no explicit target tier is provided.
- UI-side tier inference that overrides API-stored tier.
- Analytics-side coercion (`COALESCE(..., 'free'/'personal')`) for user tier display.

## Runtime Guardrails
- Invalid persisted tier in auth/session paths throws `invalid_user_status`.
- Analytics tier renderers label unknown values as `Invalid` instead of remapping them.
- Addon auth now enforces a hard fail-lock:
  - any missing/invalid/mismatched canonical tier fields (`auth_stored_plan_code` / `auth_stored_account_tier`) trigger `tier_integrity_violation`
  - session tokens are cleared (API key is preserved for reconnect)
  - addon status is set to a critical integrity error and cloud operations are blocked until reconnect/fix

## Audit Queries (D1)
Run against remote D1:

```sql
SELECT COUNT(*) AS invalid_user_status_rows
FROM users
WHERE status IS NULL
   OR TRIM(status) = ''
   OR LOWER(TRIM(status)) NOT IN ('free','personal','commercial','blocked');

SELECT COUNT(*) AS invalid_api_key_plan_rows
FROM api_keys
WHERE plan_code IS NULL
   OR TRIM(plan_code) = ''
   OR LOWER(TRIM(plan_code)) NOT IN ('free','personal','commercial');

SELECT COUNT(*) AS active_api_key_user_mismatches
FROM api_keys k
JOIN users u ON u.id = k.user_id
WHERE LOWER(TRIM(k.status)) = 'active'
  AND LOWER(TRIM(u.status)) IN ('free','personal','commercial')
  AND LOWER(TRIM(k.plan_code)) != LOWER(TRIM(u.status));
```

Expected result for all counts: `0`.
