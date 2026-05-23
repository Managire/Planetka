# Account Tier Integrity

Last updated: 2026-05-19

Planetka uses two active add-on account tiers: `free` and `pro`.

## Canonical Account State

`users.status` is an account access state and may be normalised by backend code for compatibility.

Active add-on access tiers:

- `free`: worldwide Preview and Balanced texture-quality streaming for personal use.
- `pro`: worldwide Preview, Balanced, and Full texture-quality streaming.

Compatibility aliases:

- legacy `personal` is treated as `free`.
- legacy `professional`, commercial, paid, or unlimited labels normalise to `pro` only where explicitly supported by backend compatibility code.

## Free Access

Free accounts can stream worldwide in Preview and Balanced texture quality.

Free access is enforced in the backend, not only in Blender UI. Enforcement occurs at tile-session start, before a short-lived tile token is issued for the requested texture quality.

If Free requests Full, the backend must deny the session with clear user-facing wording.

## Pro Access

Pro accounts can stream worldwide in all active quality modes:

- Preview
- Balanced
- Full

Pro access remain subject to fair-usage, anti-abuse, authentication, and service-protection controls.

## Beta Default

During public beta, newly requested access keys default to `pro`. This is controlled by `PLANETKA_BETA_DEFAULT_PRO=1` on the auth worker.

When beta ends, set `PLANETKA_BETA_DEFAULT_PRO=0` so newly requested access keys default to `free`.

The beta backfill policy is: all existing non-blocked accounts are promoted to canonical `pro` once. This does not remove the ability to manually test `free`; manual Analytics tier switches remain authoritative after the backfill.

The Analytics All Users page may still manually switch any account between:

- `free`
- `pro`

The switch updates the user account row and all active access keys for that user. Existing short-lived access tokens may keep their previous tier until the next auth refresh.

## Removed Add-on Concepts

The active 0.8.2 add-on model must not rely on:

- tile purchase entitlements for add-on access;
- scene-specific tile purchases;
- animation tile purchases;
- data-pack purchases inside Blender;
- purchase-history UI;
- licenced-data download/archive UI;
- prepaid balance;
- monthly billing;
- Standard/Balanced paid unlock handlers.

The website data-pack/catalog system may remain in Cloudflare for future or separate data products, but it must not be the authority for 0.8.2 Blender add-on streaming access.

## Required Tests

Run against the live or staging backend before release:

```bash
/Applications/Blender5.0.app/Contents/MacOS/Blender --background --factory-startup --python tools/planetka_account_tier_gate.py
```

Expected result:

- Free account allows worldwide Preview and Balanced and blocks Full clearly.
- Pro account allows tested worldwide locations in Preview, Balanced, and Full.

## Audit Queries

Run against remote D1 when cleaning legacy data:

```sql
SELECT LOWER(TRIM(COALESCE(status, ''))) AS status, COUNT(*) AS count
FROM users
GROUP BY LOWER(TRIM(COALESCE(status, '')))
ORDER BY count DESC;

SELECT LOWER(TRIM(COALESCE(plan_code, ''))) AS plan_code, COUNT(*) AS count
FROM api_keys
GROUP BY LOWER(TRIM(COALESCE(plan_code, '')))
ORDER BY count DESC;
```

Expected active result: account states normalise to `free` or `pro` for add-on access decisions.
