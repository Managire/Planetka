# Cloudflare Setup: Planetka Data Allowance System

This repository contains addon-side integration only. The Cloudflare Worker/API
implementation is not present here, so this document defines the backend
contract required by the addon.

## 1) Product Model (Current)

Plans:
- `planetka` (Planetka): free, `100 GB/month`, personal/non-commercial use only.
- `planetka_pro` (Planetka Pro): `19 EUR/month`, commercial use included,
  `1000 GB/month` included, rollover bank up to `3000 GB`.
- `planetka_studio` (Planetka Studio): manual/custom entitlements for
  broadcasters/studios/special workflows.

No public self-serve top-up product:
- Do not expose a top-up checkout/action in addon or public API copy.
- Extra allowance is handled manually by Planetka (support-side adjustments).

Core metering rules:
- Meter by **fresh downloaded bytes** only.
- Cache hits must not consume allowance.
- Consumption order:
  1. single monthly allowance pool (included + any manual support grant folded in)

## 2) Worker Environment Variables

Set these on production Worker:

- `ALLOWANCE_FREE_INCLUDED_GB=100`
- `ALLOWANCE_PRO_INCLUDED_GB=1000`
- `ALLOWANCE_PRO_ROLLOVER_CAP_GB=3000`
- `ALLOWANCE_PERIOD_DAYS=30`
- `ALLOWANCE_COUNTING_RULE=Only newly downloaded data counts. Reused local cache does not consume allowance.`

Optional:
- `ALLOWANCE_LOW_WARNING_GB=10`
- `ALLOWANCE_LOW_WARNING_RATIO=0.10`
- `ALLOWANCE_SUPPORT_URL=https://www.planetka.io/contact-me` (or your preferred contact endpoint)

## 3) D1 Schema (Required)

Use your existing `users` table and add/maintain:

```sql
CREATE TABLE IF NOT EXISTS user_entitlements (
  user_id TEXT PRIMARY KEY,
  plan_code TEXT NOT NULL DEFAULT 'planetka',
  commercial_use_allowed INTEGER NOT NULL DEFAULT 0,
  included_limit_bytes INTEGER NOT NULL DEFAULT 0,
  included_remaining_bytes INTEGER NOT NULL DEFAULT 0,
  rollover_bank_bytes INTEGER NOT NULL DEFAULT 0,
  period_started_at TEXT NOT NULL,
  period_ends_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS manual_allowance_credits (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  bytes_total INTEGER NOT NULL,
  bytes_remaining INTEGER NOT NULL,
  granted_at TEXT NOT NULL,
  expires_at TEXT,
  source TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_manual_allowance_credits_user_expiry
ON manual_allowance_credits(user_id, expires_at, granted_at);

CREATE TABLE IF NOT EXISTS data_usage_ledger (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  request_path TEXT NOT NULL,
  bytes_charged INTEGER NOT NULL,
  charged_from TEXT NOT NULL,
  credit_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_data_usage_ledger_user_created
ON data_usage_ledger(user_id, created_at);
```

Compatibility note:
- If legacy `topup_credits` already exists, it can remain as an internal storage
  mechanism for manual credits. Do not expose it as a public top-up product.

## 4) Period Reset + Rollover Rules

On authenticated requests (or scheduled job), if `now >= period_ends_at`:

1. For `planetka`:
   - `included_limit_bytes = 100 GB`
   - `included_remaining_bytes = 100 GB`
   - `rollover_bank_bytes = 0`

2. For `planetka_pro`:
   - `unused_included = max(0, included_remaining_bytes)`
   - `rollover_bank_bytes = min(3000 GB, rollover_bank_bytes + unused_included)`
   - `included_limit_bytes = 1000 GB`
   - `included_remaining_bytes = included_limit_bytes + rollover_bank_bytes`

3. Expire manual credits:
   - set `bytes_remaining = 0` when `expires_at < now` (or skip during consumption).

4. Advance period by `ALLOWANCE_PERIOD_DAYS` (currently 30).

## 5) Stripe/Webhook Integration

Required behavior:
- New users default to `plan_code='planetka'`.
- Pro Hosted Streaming Access activation/upgrades set `plan_code='planetka_pro'`.
- Pro cancellation/downgrade follows your billing policy for next cycle.
- `commercial_use_allowed`:
  - `0` for `planetka`
  - `1` for `planetka_pro` and `planetka_studio`

No self-serve top-up webhook path is required in product UX.
Manual credit grants are performed by support/admin tooling (outside addon).

## 6) `/tiles/*` Enforcement (Critical)

In Worker tile streaming path:

1. Authenticate user.
2. Resolve allowance state (period reset + any manual grants folded into monthly pool).
3. For `HEAD`: do not charge.
4. For `GET` cache miss / streamed bytes:
   - compute `bytes_to_charge` from object size/content-length
   - consume from the single monthly allowance pool
   - if you keep legacy manual credits internally, they must be folded into the same pool
5. If no allowance remains, reject with `429` and return allowance payload.
6. On success, record in `data_usage_ledger`.

## 7) API Contract Required by Addon

Return these fields from:
- `POST /auth/verify`
- `POST /auth/refresh`
- `POST /device/poll` (completed)
- `GET /me`

```json
{
  "email": "user@example.com",
  "commercial_use_allowed": false,
  "plan": {
    "code": "planetka",
    "name": "Planetka"
  },
  "upgrade_url": "https://www.planetka.io/signup",
  "manage_hosted_streaming_access_url": "https://www.planetka.io/account",
  "contact_url": "https://www.planetka.io/contact-me",
  "billing_period_end": "2026-04-01T00:00:00Z",
  "data_allowance": {
    "period": "month",
    "period_end": "2026-04-01T00:00:00Z",
    "included_limit_bytes": 107374182400,
    "included_remaining_bytes": 84557168640,
    "topup_remaining_bytes": 0,
    "total_remaining_bytes": 84557168640,
    "downloaded_period_bytes": 22817013760,
    "warning_state": "ok",
    "exhausted": false,
    "counting_rule": "Only newly downloaded data counts. Reused local cache does not consume allowance."
  }
}
```

Notes:
- UI should treat this as one allowance pool. Keep
  `topup_remaining_bytes` at `0` and keep `total_remaining_bytes` equal to
  `included_remaining_bytes`.
- Keep `account_tier` (`free`/`pro`/`studio`) if already used elsewhere.

## 8) Addon Behavior (Implemented Here)

Addon shows:
- plan and license scope (free personal/non-commercial vs Pro commercial),
- one remaining data value,
- period end, period downloaded, and warning state.

Low/exhausted actions:
- No Buy Top-Up CTA.
- Free users: contact prompt (+ optional Pro upgrade prompt).
- Pro users: contact prompt for one-off boost or higher recurring allowance.

## 9) Manual Support Workflow

When user asks for more allowance:
1. Review plan and current usage.
2. Increase the user monthly allowance in backend for the active period.
3. Optional: if you keep legacy `manual_allowance_credits`, fold them into
   `included_remaining_bytes` in API responses so UI still sees one pool.
4. User refreshes session / next `/me` sync reflects updated allowance.

This supports:
- soft-limit handling for free users,
- special-case production needs for Pro users,
- no micropayment flow in addon UI.

## 10) Canonical Plan Copy

`Planetka`  
Free. Personal / non-commercial use. `100 GB/month`.  
If more data is needed, contact Planetka and briefly describe the project
(renders/screenshots/showcase material is helpful).

`Planetka Pro`  
`19 EUR/month`. Commercial use included. `1000 GB/month`. Rollover up to
`3000 GB`.  
If more data is needed for special workflows, contact Planetka.

`Planetka Studio`  
Custom/manual for broadcasters, studios, production houses, and other
high-demand workflows.
