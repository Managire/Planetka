# Stable Release: Hosted Data Access (Yearly)

Date: 2026-03-29
Status: Stable

## Model

- Single fully functional addon tier.
- New accounts receive a 25 GB trial allowance.
- After trial is exhausted, users buy Hosted Data Access.
- Hosted Data Access is granted automatically from Stripe webhooks.
- Hosted Data Access validity is one year per successful payment event.
- Repeated successful payments extend access from current expiry.

## Product/UI

- API key login flow remains active.
- Trial users see "Buy Unlimited Data Access" call to action.
- Active hosted-access users do not see tier-lock UI.
- Texture quality pipeline is fixed to Full in production model.
- Animation rendering is not tier-locked.

## Worker/API

- Public API key request path always starts trial access.
- Client-side plan tampering cannot grant paid hosted access.
- Entitlement active state requires valid future hosted-access expiry.
- Trial allowance and hosted-access period are configurable via:
  - `TRIAL_INCLUDED_GB`
  - `HOSTED_ACCESS_DURATION_DAYS`

## Default Ops Thresholds

- Trial daily high-volume threshold: `DOWNLOAD_THROTTLE_FREE_DAILY_GB=25`
- Active hosted-access threshold: disabled by default (`DOWNLOAD_THROTTLE_PRO_DAILY_GB=0`)

## Validation

- Python compile checks: pass.
- Worker syntax check: pass.
- `tools/release_gate.py`: pass.
