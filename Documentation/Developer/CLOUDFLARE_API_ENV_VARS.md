# Cloudflare API Environment Variables

This document lists runtime environment variables used by `cloudflare-api/src/index.js` for auth/device protection and cleanup behavior.

## Rate Limiting

Defaults are applied when a variable is missing or invalid.

- `RATE_LIMIT_AUTH_START_IP_LIMIT` (default: `20`)
- `RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS` (default: `60`)
- `RATE_LIMIT_AUTH_START_EMAIL_LIMIT` (default: `6`)
- `RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS` (default: `900`)
- `RATE_LIMIT_DEVICE_POLL_IP_LIMIT` (default: `300`)
- `RATE_LIMIT_DEVICE_POLL_IP_WINDOW_SECONDS` (default: `60`)
- `RATE_LIMIT_DEVICE_POLL_CODE_LIMIT` (default: `120`)
- `RATE_LIMIT_DEVICE_POLL_CODE_WINDOW_SECONDS` (default: `60`)
- `RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT` (default: `20`)
- `RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS` (default: `300`)

## Admin Dashboard Login

- `ADMIN_DASHBOARD_PASSWORD` (secret, optional if hash is used)
- `ADMIN_DASHBOARD_PASSWORD_HASH` (secret, SHA-256 hex of password; recommended)
- `ADMIN_LOGIN_EMAIL` (default: `tom.griger@gmail.com`)

Notes:
- Set either `ADMIN_DASHBOARD_PASSWORD` or `ADMIN_DASHBOARD_PASSWORD_HASH`.
- `ADMIN_LOGIN_EMAIL` must also be included in `ANALYTICS_ADMIN_EMAILS`.
- Login endpoint is available at `/admin/login` and sets the same admin cookie used by `/admin/analytics`.

## DB Cleanup Cron

- `CLEANUP_REFRESH_SESSION_RETENTION_DAYS` (default: `30`)
- Used by the scheduled cleanup job to delete old revoked/expired `refresh_sessions`.
- `magic_links` and `device_sessions` are deleted when `expires_at` is in the past.
- `CLEANUP_TILE_EVENT_RETENTION_DAYS` (default: `30`)
- `CLEANUP_TILE_ROLLUP_RETENTION_DAYS` (default: `365`)
- `PAID_CLAIM_RETENTION_DAYS` (default: `180`)
- These are applied by the scheduled cleanup to keep `tile_request_events`, rollup tables, and claim audit tables bounded.

## Log Alert Thresholds

These control warning logs for spikes in auth/device failures. Set to `0` to disable the corresponding threshold alert.

- `LOG_ALERT_AUTH_429_THRESHOLD` (default: `10`)
- `LOG_ALERT_AUTH_429_WINDOW_SECONDS` (default: `60`)
- `LOG_ALERT_DEVICE_POLL_429_THRESHOLD` (default: `30`)
- `LOG_ALERT_DEVICE_POLL_429_WINDOW_SECONDS` (default: `60`)
- `LOG_ALERT_AUTH_ERROR_THRESHOLD` (default: `5`)
- `LOG_ALERT_AUTH_ERROR_WINDOW_SECONDS` (default: `300`)

## Production Email Alert Thresholds

These are checked by the Worker scheduled job and notify `SECURITY_ALERT_EMAIL`.

- `PROD_ALERT_403_THRESHOLD` (default: `25`)
- `PROD_ALERT_403_WINDOW_SECONDS` (default: `300`)
- `PROD_ALERT_429_THRESHOLD` (default: `25`)
- `PROD_ALERT_429_WINDOW_SECONDS` (default: `300`)
- `PROD_ALERT_TILE_MISS_THRESHOLD` (default: `25`)
- `PROD_ALERT_TILE_MISS_WINDOW_SECONDS` (default: `300`)
- `PROD_ALERT_TILE_ERROR_THRESHOLD` (default: `10`)
- `PROD_ALERT_TILE_ERROR_WINDOW_SECONDS` (default: `300`)
- `PROD_ALERT_CLAIM_REJECTION_THRESHOLD` (default: `5`)
- `PROD_ALERT_CLAIM_REJECTION_WINDOW_SECONDS` (default: `3600`)
- `PROD_ALERT_COOLDOWN_SECONDS` (default: `900`)

Set a threshold to `0` to disable that metric.

## Related Test Script

Run:

```bash
python3 tools/worker_auth_integration_test.py
```

Optional tuning:

```bash
python3 tools/worker_auth_integration_test.py \
  --base-url https://api.planetka.io \
  --auth-rate-limit-attempts 8 \
  --device-poll-rate-limit-attempts 140
```

Paid-claim lifecycle check:

```bash
PLANETKA_BEARER_TOKEN="<admin_access_token>" \
python3 tools/worker_paid_claim_lifecycle_test.py \
  --base-url https://api.planetka.io
```
