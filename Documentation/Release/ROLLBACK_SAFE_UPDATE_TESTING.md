# Rollback-Safe Update Testing

Goal: ensure users can upgrade and downgrade without blocking production.

## Test Flow

Use two extension builds:
- `A`: last stable release
- `B`: release candidate

Run on representative scene files.

1. Baseline on `A`
- Open scene.
- Run `Create Earth` (if needed) and `Resolve Earth`.
- Save as baseline snapshot.

2. Upgrade to `B`
- Open same scene.
- Run `Create Earth`/`Resolve Earth` as needed.
- Save and reopen to verify no load-time errors.

3. Roll back to `A`
- Reopen scene saved in step 2.
- Confirm no blocker errors on open.
- Re-run `Resolve Earth`.

4. Validate outputs
- Compare render sample or viewport key frame for visible regressions.
- Confirm Create/Resolve Earth controls remain operational.

## Pass Criteria

- No blocker errors on open after downgrade.
- Core operators still execute.
- No silent data loss in key Planetka controls.

## If Failing

- Mark release as rollback-unsafe.
- Document exact failure mode and workaround in release notes.
- Delay publish unless risk is explicitly accepted.
