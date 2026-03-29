# Cloudflare Setup: Planetka Hosted Data Access (Current Model)

This document reflects the current production access model.

## 1) Access Model (Current)

- Single addon tier for all users (full functionality always enabled).
- New users start with a `25 GB` trial allowance.
- After trial is exhausted, user must buy Hosted Data Access to continue tile streaming.
- Hosted Data Access is granted automatically from Stripe webhook events.
- Hosted Data Access is valid for one year per successful payment event.
- Repeated payment events extend the active end date.

Terminology:
- User-facing text should use **Hosted Data Access** (or **Hosted Streaming Access** for compatibility labels).
- Avoid user-facing “subscription” wording where possible.

## 2) Plan Enforcement

- Trial and paid accounts both have the same full functional feature set.
- Daily high-volume thresholds:
  - Trial account: `25 GB / rolling 24h`
  - Active Hosted Data Access account: disabled by default (`DOWNLOAD_THROTTLE_PRO_DAILY_GB=0`)
    and configurable if needed.

When threshold is exceeded:
- account is auto-throttled for `24h`
- user receives notification email
- ops/security receives alert email

## 3) Stripe Entitlement Flow

Required behavior in Worker:

1. User purchases on Stripe checkout.
2. Stripe webhook (`checkout.session.completed` / `invoice.paid`) is verified.
3. Allowed product/price IDs are matched.
4. User hosted-access state is set to active immediately.
5. Access validity end date is set/extended by one year.

Public API key request path must always start in trial mode:
- `/auth/api-key/request` ignores any client paid-plan tampering.
- Paid elevation is server-side only via Stripe webhook entitlement.

## 4) Required Worker Variables

Core:
- `STRIPE_ALLOWED_PRICE_IDS`
- `STRIPE_ALLOWED_PRODUCT_IDS`
- `TRIAL_INCLUDED_GB=25`
- `HOSTED_ACCESS_DURATION_DAYS=365`
- `EMAIL_API_KEY`
- `EMAIL_FROM`
- `SECURITY_ALERT_EMAIL`

Rate/security:
- `DOWNLOAD_THROTTLE_FREE_DAILY_GB=25`
- `DOWNLOAD_THROTTLE_PRO_DAILY_GB=0` (disabled by default)
- `DOWNLOAD_THROTTLE_DURATION_MINUTES=1440`
- `DOWNLOAD_THROTTLED_DELAY_MS=30000`
- `DOWNLOAD_ALERT_EMAIL_COOLDOWN_SECONDS=300`
- `PROD_ALERT_COOLDOWN_SECONDS=300`

Contact endpoint:
- `PLANETKA_CONTACT_URL=https://www.planetka.io/contact-me`

## 5) API Contract Expected by Addon

Auth/profile endpoints should expose:

- `plan.code`
- `commercial_use_allowed`
- `upgrade_url`
- `contact_url`
- `data_allowance` object
- `throttled_until` (when active)
- `is_throttled` (boolean)

Used by addon for:
- account panel status
- trial vs active hosted-access messaging
- throttled status visibility in Status Check

## 6) Abuse and Telemetry Notes

- Raw tile telemetry retention is enforced by scheduled cleanup.
- Rollups are used for analytics longevity.
- Admin analytics query-token access is disabled.
- Legacy magic-link auth is disabled in production.

## 7) Operational Validation Checklist

- `/health` reports:
  - `magic_link_auth_enabled=false`
  - `db_bound=true`
  - `r2_bound=true`
- `release_gate.py` passes.
- `worker_abuse_simulation.py` passes.
- `worker_auth_integration_test.py` passes.

## 8) User-Facing Contact Path

Use only:
- `https://www.planetka.io/contact-me`

Do not use:
- `/contact`
