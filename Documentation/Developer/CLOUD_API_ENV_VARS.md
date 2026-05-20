# Cloud API Environment Variables

This document lists the runtime environment variables used by the Planetka Worker.

The 0.7.0 public-release model is:
- auth is API-key based;
- Preview access is free for authenticated add-on use;
- Full Quality access is granted through direct purchase, promotion, or explicit entitlement;
- Standard/Balanced, prepaid balance, monthly billing, and unrestricted quality access are not public-release products.

## Rate Limiting

Defaults are applied when a variable is missing or invalid.

These limits protect the public API-key request flow and admin login.

- `RATE_LIMIT_AUTH_START_IP_LIMIT` (default: `20`)
- `RATE_LIMIT_AUTH_START_IP_WINDOW_SECONDS` (default: `60`)
- `RATE_LIMIT_AUTH_START_EMAIL_LIMIT` (default: `6`)
- `RATE_LIMIT_AUTH_START_EMAIL_WINDOW_SECONDS` (default: `900`)
- `RATE_LIMIT_ADMIN_LOGIN_IP_LIMIT` (default: `20`)
- `RATE_LIMIT_ADMIN_LOGIN_IP_WINDOW_SECONDS` (default: `300`)

## Legal Document Versions

- `LEGAL_VERSION` (recommended current value: `2026-05-12`)
- `TERMS_VERSION` (recommended current value: `2026-05-12`)
- `PRIVACY_VERSION` (recommended current value: `2026-05-12`)
- `LEGAL_TERMS_KEY` (default R2 key: `legal/terms-of-service.pdf`)
- `LEGAL_PRIVACY_KEY` (default R2 key: `legal/privacy-policy.pdf`)

## Admin Dashboard Login

- `ADMIN_DASHBOARD_PASSWORD` (secret, optional if hash is used)
- `ADMIN_DASHBOARD_PASSWORD_HASH` (secret, SHA-256 hex of password; recommended)
- `ADMIN_LOGIN_EMAIL` (default: `tom.griger@gmail.com`)
- `ANALYTICS_ADMIN_EMAILS` (comma-separated admin email allowlist)

Notes:
- Set either `ADMIN_DASHBOARD_PASSWORD` or `ADMIN_DASHBOARD_PASSWORD_HASH`.
- `ADMIN_LOGIN_EMAIL` must also be included in `ANALYTICS_ADMIN_EMAILS`.
- Login endpoint is available at `/admin/login` and sets the same admin cookie used by `/admin/analytics`.

## DB Cleanup Cron

- `CLEANUP_REFRESH_SESSION_RETENTION_DAYS` (default: `30`)
- `CLEANUP_AUTH_REFRESH_EVENT_RETENTION_DAYS` (default: `30`)
- `CLEANUP_TILE_EVENT_RETENTION_DAYS` (default: `30`)
- `CLEANUP_TILE_ROLLUP_RETENTION_DAYS` (default: `365`)
- `API_KEY_DEVICE_ACTIVE_WINDOW_SECONDS` (default: `900`)

Scheduled cleanup keeps these tables bounded:
- `refresh_sessions`
- `api_key_requests`
- `api_key_device_activity`
- `auth_refresh_events`
- `tile_request_events`
- `tile_request_rollup_hourly_account`
- `tile_request_rollup_daily_account`
- `monthly_cost_alert_state`

## Log Alert Thresholds

These control warning logs for spikes in auth failures. Set a threshold to `0` to disable it.

- `LOG_ALERT_AUTH_429_THRESHOLD` (default: `10`)
- `LOG_ALERT_AUTH_429_WINDOW_SECONDS` (default: `60`)
- `LOG_ALERT_AUTH_ERROR_THRESHOLD` (default: `5`)
- `LOG_ALERT_AUTH_ERROR_WINDOW_SECONDS` (default: `300`)

## Production Email Alert Thresholds

These are checked by the scheduled Worker job and notify `SECURITY_ALERT_EMAIL`.

- `PROD_ALERT_403_THRESHOLD` (default: `25`)
- `PROD_ALERT_403_WINDOW_SECONDS` (default: `300`)
- `PROD_ALERT_429_THRESHOLD` (default: `25`)
- `PROD_ALERT_429_WINDOW_SECONDS` (default: `300`)
- `PROD_ALERT_TILE_MISS_THRESHOLD` (default: `25`)
- `PROD_ALERT_TILE_MISS_WINDOW_SECONDS` (default: `300`)
- `PROD_ALERT_TILE_ERROR_THRESHOLD` (default: `10`)
- `PROD_ALERT_TILE_ERROR_WINDOW_SECONDS` (default: `300`)
- `PROD_ALERT_COOLDOWN_SECONDS` (default: `300`)

## Real-Time Tile Farming Alerts

These run on tile request traffic and are intended to catch scraping or dataset farming behavior quickly.

- `TILE_FARM_ALERT_WINDOW_SECONDS` (default: `300`)
- `TILE_FARM_ALERT_USER_REQUEST_THRESHOLD` (default: `300`)
- `TILE_FARM_ALERT_IP_REQUEST_THRESHOLD` (default: `500`)
- `TILE_FARM_ALERT_UNIQUE_TILE_THRESHOLD` (default: `200`)
- `TILE_FARM_ALERT_UNTAGGED_MIN_REQUESTS` (default: `120`)
- `TILE_FARM_ALERT_UNTAGGED_PERCENT` (default: `90`)
- `TILE_FARM_ALERT_EMAIL_COOLDOWN_SECONDS` (default: `300`)
- `ABUSE_ALERT_WHITELIST_EMAILS` (default: empty)

Alert email is sent to `SECURITY_ALERT_EMAIL` when suspicious patterns are detected, including:
- high request velocity per account
- high request velocity per IP
- high new-unique tile velocity per account
- high untagged tile ratio (many requests without `X-Planetka-Resolve-Id`)

## Access Model

Worker-side access control should treat Preview as the default authenticated texture mode and Full Quality as entitlement/payment controlled.

Do not expose legacy Standard/Balanced, prepaid balance, monthly-billing, or unrestricted-quality flows unless they are deliberately reintroduced as public products.

## Monthly Cost Estimate Alerts

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

## Addon Auto-Update Manifest

These power the addon update manifest endpoint at `GET /addon/update-manifest`.

- `ADDON_UPDATE_VERSION` (prepared 0.8.2 value: `0.8.2`)
- `ADDON_UPDATE_DOWNLOAD_URL` (prepared 0.8.2 value: `https://api.planetka.io/addon/releases/Planetka_update_0.8.2.zip`)
- `ADDON_UPDATE_SHA256` (prepared 0.8.2 value: `b6d57f4d03308dfedb77366077015fe91d6cde81a91bb590aac5233c92c81df4`)
- `ADDON_UPDATE_RELEASE_NOTES_URL` (default: `https://www.planetka.io/blender/documentation/`)
- `ADDON_UPDATE_CHANNEL` (default: `stable`)
- `ADDON_UPDATE_MIN_BLENDER` (default: `4.5.7`)
- `ADDON_UPDATE_MANDATORY` (default: `false`)
- `ADDON_UPDATE_PUBLISHED_AT` (optional ISO timestamp)
- `ADDON_UPDATE_MANIFEST_MAX_AGE_SECONDS` (default: `300`)

## Related Test Scripts

Run:

```bash
python3 tools/worker_auth_integration_test.py
python3 tools/worker_abuse_simulation.py --base-url https://api.planetka.io --tile-requests 60
```
