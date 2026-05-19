# Account Tier Integrity

Last updated: 2026-05-19

Planetka 0.8.1 uses two active add-on account tiers: `personal` and `professional`.

## Canonical Account State

`users.status` is an account access state and may be normalised by backend code for compatibility.

Active add-on access tiers:

- `personal`: free account access limited to selected free locations.
- `professional`: worldwide Planetka streaming access.

Compatibility aliases:

- legacy `free` is treated as `personal`.
- legacy commercial/pro/unlimited labels must normalise to `professional` only where explicitly supported by backend compatibility code.

## Personal Access

Personal accounts can stream only the selected free locations:

- New Zealand
- Iceland

Personal access is enforced in the backend, not only in Blender UI. Enforcement occurs at:

- tile-session start, using the navigation latitude/longitude sent by the add-on;
- tile request, using the requested tile's geographic coverage and the free-region claim stored in the tile session.

If the requested area is outside the selected free locations, the backend must deny the session/request with clear user-facing wording.

## Professional Access

Professional accounts can stream worldwide in all active quality modes:

- Preview
- Balanced
- Full Quality

Professional access is still subject to fair-usage, anti-abuse, authentication, and service-protection controls.

## Beta Default

During beta, all existing users and newly requested access keys default to `professional`.
This is a temporary release policy so testers can verify worldwide streaming without payment.

The Analytics All Users page may still manually switch any account between:

- `personal`
- `professional`

The switch updates the user account row and all active access keys for that user. Existing short-lived access tokens may keep their previous tier until the next auth refresh.

## Removed Add-on Concepts

The active 0.8.1 add-on model must not rely on:

- tile purchase entitlements for add-on access;
- scene-specific tile purchases;
- animation tile purchases;
- data-pack purchases inside Blender;
- purchase-history UI;
- licenced-data download/archive UI;
- prepaid balance;
- monthly billing;
- Standard/Balanced paid unlock handlers.

The website data-pack/catalog system may remain in Cloudflare for future or separate data products, but it must not be the authority for 0.8.1 Blender add-on streaming access.

## Required Tests

Run against the live or staging backend before release:

```bash
/Applications/Blender5.0.app/Contents/MacOS/Blender --background --factory-startup --python tools/planetka_account_tier_gate.py
```

Expected result:

- Personal account allows New Zealand and Iceland in Preview, Balanced, and Full Quality.
- Personal account blocks other locations clearly.
- Professional account allows tested worldwide locations in Preview, Balanced, and Full Quality.

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

Expected active result: account states normalise to `personal` or `professional` for add-on access decisions.
