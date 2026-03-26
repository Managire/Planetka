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

## DB Cleanup Cron

- `CLEANUP_REFRESH_SESSION_RETENTION_DAYS` (default: `30`)
- Used by the scheduled cleanup job to delete old revoked/expired `refresh_sessions`.
- `magic_links` and `device_sessions` are deleted when `expires_at` is in the past.

## Log Alert Thresholds

These control warning logs for spikes in auth/device failures. Set to `0` to disable the corresponding threshold alert.

- `LOG_ALERT_AUTH_429_THRESHOLD` (default: `10`)
- `LOG_ALERT_AUTH_429_WINDOW_SECONDS` (default: `60`)
- `LOG_ALERT_DEVICE_POLL_429_THRESHOLD` (default: `30`)
- `LOG_ALERT_DEVICE_POLL_429_WINDOW_SECONDS` (default: `60`)
- `LOG_ALERT_AUTH_ERROR_THRESHOLD` (default: `5`)
- `LOG_ALERT_AUTH_ERROR_WINDOW_SECONDS` (default: `300`)

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
