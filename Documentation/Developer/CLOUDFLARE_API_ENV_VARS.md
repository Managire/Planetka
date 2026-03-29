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
- These are applied by the scheduled cleanup to keep `tile_request_events`, rollup tables, and legacy claim-audit tables bounded.

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
- `PROD_ALERT_COOLDOWN_SECONDS` (default: `300`)

Set a threshold to `0` to disable that metric.

## Real-Time Tile Farming Alerts

These run on tile request traffic (immediate detection), not only on cron.

- `TILE_FARM_ALERT_WINDOW_SECONDS` (default: `300`)
- `TILE_FARM_ALERT_USER_REQUEST_THRESHOLD` (default: `300`)
- `TILE_FARM_ALERT_IP_REQUEST_THRESHOLD` (default: `500`)
- `TILE_FARM_ALERT_UNIQUE_TILE_THRESHOLD` (default: `200`)
- `TILE_FARM_ALERT_UNTAGGED_MIN_REQUESTS` (default: `120`)
- `TILE_FARM_ALERT_UNTAGGED_PERCENT` (default: `90`)
- `TILE_FARM_ALERT_EMAIL_COOLDOWN_SECONDS` (default: `300`)

Alert email is sent to `SECURITY_ALERT_EMAIL` when suspicious patterns are detected, including:

- high request velocity per account
- high request velocity per IP
- high new-unique tile velocity per account
- high untagged tile ratio (many requests without `X-Planetka-Resolve-Id`)

## Download Volume Monitoring & Auto-Throttle

These controls are used for heavy-user monitoring, milestone alerts, and automatic speed throttling.

- `DOWNLOAD_MARK_STEP_GB` (default: `100`)
- `DOWNLOAD_THROTTLE_FREE_DAILY_GB` (default: `25`)
- `DOWNLOAD_THROTTLE_PRO_DAILY_GB` (default: `0`, disabled)
- `DOWNLOAD_THROTTLE_DURATION_MINUTES` (default: `1440`)
- `DOWNLOAD_THROTTLED_REQUESTS_PER_MINUTE` (default: `0`; disabled when `0`)
- `DOWNLOAD_THROTTLED_DELAY_MS` (default: `30000`)
- `DOWNLOAD_ALERT_EMAIL_COOLDOWN_SECONDS` (default: `300`)
- `DOWNLOAD_ALERT_WHITELIST_EMAILS` (default: empty; admin/permanent-pro emails are always implicitly whitelisted)

Behavior:

- Per-account counters track `lifetime`, `month`, `week`, `day`, and `hour` bytes.
- Ops milestone alerts trigger when crossing each `DOWNLOAD_MARK_STEP_GB` mark.
- If rolling 24-hour bytes exceed threshold (`DOWNLOAD_THROTTLE_FREE_DAILY_GB` for trial users, `DOWNLOAD_THROTTLE_PRO_DAILY_GB` for active Hosted Data Access users), user is automatically throttled.
- A value of `0` disables that specific threshold.
- While throttled, requests are delayed (`DOWNLOAD_THROTTLED_DELAY_MS`) to slow sustained scraping.
- Optional per-minute cap can be enabled by setting `DOWNLOAD_THROTTLED_REQUESTS_PER_MINUTE` above `0`.
- Throttled users receive an email notification; ops receives a security alert.

## Hosted Streaming Access Entitlements

- `STRIPE_ALLOWED_PRICE_IDS` (required for paid entitlement matching)
- `STRIPE_ALLOWED_PRODUCT_IDS` (required for paid entitlement matching)
- `TRIAL_INCLUDED_GB` (default: `25`)
- `HOSTED_ACCESS_DURATION_DAYS` (default: `365`)

Behavior:

- New accounts start in trial mode with `TRIAL_INCLUDED_GB` included.
- Trial and paid accounts use the same full addon functionality.
- When trial allowance reaches zero, tile delivery is denied until payment is detected.
- Paid entitlement is granted automatically from Stripe webhooks.
- Each successful paid event grants or extends Hosted Data Access by `HOSTED_ACCESS_DURATION_DAYS`.
- API-key request flow never grants paid status directly; paid status is server-side only.

## Monthly Cost Estimate Alerts (Ops)

These controls estimate monthly R2 cost and notify ops when estimate crosses threshold marks.

- `MONTHLY_COST_ALERT_BASE_USD` (default: `50`)
- `MONTHLY_COST_ALERT_STEP_USD` (default: `10`)
- `R2_ESTIMATED_STORAGE_GB` (default: `2600`)
- `R2_STORAGE_PRICE_PER_GB_MONTH_USD` (default: `0.015`)
- `R2_STORAGE_FREE_GB_MONTH` (default: `10`)
- `R2_CLASS_A_PRICE_PER_MILLION_USD` (default: `4.5`)
- `R2_CLASS_B_PRICE_PER_MILLION_USD` (default: `0.36`)
- `R2_CLASS_A_FREE_OPS_PER_MONTH` (default: `1000000`)
- `R2_CLASS_B_FREE_OPS_PER_MONTH` (default: `10000000`)
- `R2_ESTIMATED_CLASS_A_OPS_MONTH` (default: `0`)

Behavior:

- Hourly cron computes month-to-date Class B ops from `tile_request_events`.
- Storage and Class A are estimated from configured env values.
- Ops email is sent whenever estimated monthly total crosses `base + N * step` (for example: `$60`, `$70`, `$80` when base is `$50` and step is `$10`).

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

Entitlement compatibility check:

```bash
PLANETKA_BEARER_TOKEN="<admin_access_token>" \
python3 tools/worker_paid_claim_lifecycle_test.py \
  --base-url https://api.planetka.io
```
