# Production Alert Runbook

This runbook covers automated Worker alerts sent from scheduled production checks.

## Alert Signals

The Worker checks these metrics and sends email to `SECURITY_ALERT_EMAIL` when threshold is exceeded:

- `HTTP 403 spike`
- `HTTP 429 spike`
- `Tile miss burst` (`tile_not_found`)
- `Tile error burst` (`status_code >= 500` or `internal_error`)
- `Claim rejection burst` (repeated paid-claim rejections/fallbacks)

Alert controls are defined in [CLOUD_API_ENV_VARS.md](/Users/tomasgriger/Library/Application%20Support/Blender/5.0/extensions/user_default/Planetka/Documentation/Developer/CLOUD_API_ENV_VARS.md).

## Immediate Response

1. Confirm alert freshness:
`tail Worker logs` and verify timestamp/window in the alert email.
2. Open analytics dashboard:
[https://api.planetka.io/admin/analytics](https://api.planetka.io/admin/analytics)
3. Check blast radius:
top users, top tiles, and recent failures for the same window.
4. Classify:
platform issue, abusive traffic, or data gap.

## Metric-Specific Actions

### HTTP 403 spike

1. Verify account blocks and auth failures in recent failures table.
2. Check if failures cluster by one email/IP/device.
3. If abusive, keep account blocked or tighten policy/rate limits.
4. If legitimate users are affected, inspect auth key/device-policy changes.

### HTTP 429 spike

1. Identify route + scope (IP/email/device) from logs.
2. Confirm whether traffic is expected (new launch, tutorial, render event).
3. For abuse, keep limits and monitor.
4. For legitimate burst, temporarily raise affected limit/window and monitor error drop.

### Tile miss burst

1. Extract missing `tile_key` examples from analytics.
2. Verify existence in source dataset and R2 key path.
3. If true missing asset, repair source tile and sync to R2.
4. If false miss, inspect path normalization/cache behavior.

### Tile error burst

1. Review Worker exceptions around the same time.
2. Check R2 availability/status and cache behavior.
3. Confirm DB health and auth middleware behavior.
4. Roll back recent Worker deploy if regression suspected.

### Claim rejection burst

1. Inspect `provisional_claim_audit` trend and repeated identifiers.
2. Check if abuse pattern is same IP/device/order ID format.
3. Keep cooldown/rate limits active; block egregious abuse manually.
4. If false positives, adjust rejection threshold/window.

## Escalation

Escalate immediately if any condition holds:

- 3 consecutive alerts for the same metric within 30 minutes.
- Any tile error burst with `status_code >= 500` sustained for >10 minutes.
- Repeated rejection burst from many distinct IPs/devices (possible coordinated abuse).

## Post-Incident Checklist

1. Record incident summary in release notes/changelog.
2. Capture root cause and exact mitigation applied.
3. Update thresholds if signal was too noisy or too late.
4. Add/adjust regression tests when issue came from a code change.
