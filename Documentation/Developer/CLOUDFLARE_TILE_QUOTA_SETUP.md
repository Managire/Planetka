# Cloudflare Setup: Preview + Credits Model

## 1) Access Model

- One addon tier for all users (personal + commercial use).
- Preview quality is free.
- Full Quality consumes credits for newly downloaded data.
- Reused local cached data does not consume credits.
- New accounts receive `25 GB` starter credits (`TRIAL_INCLUDED_GB=25`).
- Additional credits are granted via Stripe checkout webhook mapping.
- Credits do not expire.

## 2) Enforcement Rules

- Tile requests with `X-Planetka-Quality-Mode: preview` do **not** consume
  credits.
- Tile requests with `X-Planetka-Quality-Mode: full` consume credits by served
  bytes.
- When Full Quality credits are depleted, tile API returns `402
  allowance_exhausted` with account state payload.

## 3) Stripe Credit Flow

1. User buys a credit package on Stripe.
2. Worker receives `checkout.session.completed`.
3. Worker fetches checkout line items.
4. Worker maps line items to credits with:
   - `STRIPE_CREDIT_PRICE_GB_MAP` (preferred), and/or
   - `STRIPE_CREDIT_PRODUCT_GB_MAP`.
5. Worker writes credit grant to `manual_allowance_credits`.
6. Credits are available immediately.

No client-side parameter may grant paid/full entitlement.

## 4) Required Worker Variables

- `TRIAL_INCLUDED_GB=25`
- `STRIPE_SECRET_KEY` (secret)
- `STRIPE_WEBHOOK_SECRET` (secret)
- `STRIPE_CREDIT_PRICE_GB_MAP` (e.g. `price_abc:10,price_def:100`)
- `STRIPE_CREDIT_PRODUCT_GB_MAP` (optional fallback)
- `STRIPE_DEFAULT_TOPUP_GB` (optional catch-all fallback)
- `TOPUP_URL` or `PURCHASE_TOPUP_URL`
- `PLANETKA_CONTACT_URL=https://www.planetka.io/contact-me`

Recommended:

- `DOWNLOAD_THROTTLE_FREE_DAILY_GB=0`
- `DOWNLOAD_THROTTLE_PRO_DAILY_GB=0`
- Keep real-time abuse detection enabled for scraping patterns.

## 5) API Contract Used by Addon

`/me` and auth responses should include:

- `data_allowance.included_remaining_bytes`
- `data_allowance.topup_remaining_bytes`
- `data_allowance.total_remaining_bytes`
- `data_allowance.counting_rule`
- `topup_url`
- `throttled_until` / `is_throttled`

## 6) Validation Checklist

- `/health` confirms DB/R2 bindings and production settings.
- `node --check cloudflare-api/src/index.js` passes.
- `tools/release_gate.py` passes.
- Stripe webhook test event grants credits for mapped price/product IDs.
- Preview mode tiles do not reduce `total_remaining_bytes`.
- Full Quality tiles reduce `total_remaining_bytes`.
