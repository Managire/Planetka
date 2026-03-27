# Magic-Link Baseline (Stable)

Date: 2026-03-27  
Baseline type: Pre-auth-refactor checkpoint

This checkpoint is the known stable Planetka build using the current magic-link
authorization flow.

## Scope

- Magic-link authentication flow remains active and unchanged.
- Resolve pipeline is in the currently working state used in active testing.
- This baseline is intended as the rollback point before moving to API-key auth.

## Purpose

- Protect a known-good state before authorization-system changes.
- Provide a clear restore target if regressions appear during auth migration.

## Backup Artifacts

- Git commit marker in `main` (this document).
- Immutable git tag for this baseline.
- External git bundle backup saved in archive storage.

