# Production Alert Runbook

This runbook covers automated Worker alerts sent from production monitoring.

## Alert Signals

The Worker checks these metrics and sends email to `SECURITY_ALERT_EMAIL` when threshold is exceeded:

- `HTTP 403 spike`
- `HTTP 429 spike`
- `Tile miss burst` (`tile_not_found`)
- `Tile error burst` (`status_code >= 500` or `internal_error`)

Alert controls are defined in [CLOUD_API_ENV_VARS.md](/Installs/tomasgriger/Library/Application%20Support/Blender/5.0/extensions/user_default/Planetka/Documentation/Developer/CLOUD_API_ENV_VARS.md).

## Immediate Response

1. Confirm alert freshness:
   `tail Worker logs` and verify timestamp/window in the alert email.
2. Open analytics dashboard:
   [https://api.planetka.io/admin/analytics](https://api.planetka.io/admin/analytics)
3. Check blast radius:
   top cloud_installs, top tiles, and recent failures for the same window.
4. Classify:
   platform issue, abusive traffic, or data gap.

## Metric-Specific Actions

### HTTP 403 spike

1. Verify session blocks and session failures in recent failures table.
2. Check if failures cluster by one email/IP/device.
3. If abusive, keep session blocked or tighten policy/rate limits.
4. If legitimate cloud_installs are affected, inspect API-key/auth changes.

### HTTP 429 spike

1. Identify route + scope (IP/email/device) from logs.
2. Confirm whether traffic is expected.
3. For abuse, keep limits and monitor.
4. For legitimate burst, temporarily raise affected limit/window and monitor error drop.

### Tile miss burst

1. Extract missing `tile_key` examples from analytics.
2. Verify existence in source dataset and object key path.
3. If true missing asset, repair source tile and sync it.
4. If false miss, inspect path normalization/cache behavior.

### Tile error burst

1. Review Worker exceptions around the same time.
2. Check R2 availability/status and cache behavior.
3. Confirm DB health and auth/session middleware behavior.
4. Roll back recent Worker deploy if regression is suspected.

## Escalation

Escalate immediately if any condition holds:

- 3 consecutive alerts for the same metric within 30 minutes.
- Any tile error burst with `status_code >= 500` sustained for more than 10 minutes.
- Repeated 403/429 bursts from many distinct IPs/devices, indicating coordinated abuse.

## Post-Incident Checklist

1. Record incident summary in release notes/changelog.
2. Capture root cause and exact mitigation applied.
3. Update thresholds if the signal was too noisy or too late.
4. Add or adjust regression tests when the issue came from a code change.
