# Account Access Integrity

Planetka no longer has customer account tiers. There are no internal `personal`, `commercial`, `standard`, Standard/Balanced, prepaid-balance, or monthly-billing account states in the active product model.

## Canonical Account State

`users.status` is an account access state, not a product tier.

Allowed values:

- `free`: normal account access. Preview access is available and paid/licenced Full Quality access is controlled by tile entitlements.
- `blocked`: account is blocked from normal authenticated access.

`api_keys.plan_code` is retained for compatibility with existing auth/session rows, but the only active value is `free`.

## Full Quality Access

Full Quality access is not granted by account tier. It is granted by one of these entitlement states:

- purchased/licenced tile rows
- purchased/licenced data pack coverage
- explicit world Full Quality unlock in `user_credit_accounts.world_full_quality_unlocked_at`
- beta full-world access flag, excluding the active purchase-testing account when configured

## Disallowed Legacy Logic

Do not reintroduce:

- account-tier pricing branches
- plan-based Full Quality access gates
- Standard/Balanced unlock handlers
- prepaid-balance account types
- monthly-billing account types
- analytics split by obsolete plan tier

## Audit Queries

Run against remote D1:

```sql
SELECT COUNT(*) AS old_user_status_rows
FROM users
WHERE LOWER(TRIM(COALESCE(status, ''))) IN ('personal', 'commercial');

SELECT COUNT(*) AS old_api_key_plan_rows
FROM api_keys
WHERE LOWER(TRIM(COALESCE(plan_code, ''))) IN ('personal', 'commercial');

SELECT COUNT(*) AS old_credit_account_type_rows
FROM user_credit_accounts
WHERE LOWER(TRIM(COALESCE(account_type, ''))) IN ('standard', 'credits', 'credit', 'unlimited');
```

Expected result for all counts: `0`.
