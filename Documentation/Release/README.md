# Planetka Release Pack

This folder contains release-process documents for public extension builds:

- `VERSIONING_POLICY.md`
- `CHANGELOG_DISCIPLINE.md`
- `QA_CHECKLIST.md`
- `FREE_TEST_GROUP_RELEASE_CHECKLIST.md`
- `SYSTEM_REQUIREMENTS.md`
- `RELEASE_NOTES_TEMPLATE.md`
- `COMPATIBILITY_MATRIX.md`
- `ROLLBACK_SAFE_UPDATE_TESTING.md`

## Current Release State

Planetka is currently in **Public Beta**.

- Beta distribution is for tester feedback and stability validation.
- Current `v0.7.0` beta access mode is `unrestricted`, so beta users receive Commercial-equivalent hosted-service access during testing regardless of stored account tier.
- The long-term product model still defines `Free`, `Personal`, and `Commercial` tiers, but that broader tier rollout is not the current beta-onboarding behavior.
- EEVEE and Cycles are both supported in the current beta candidate.
- Terms for beta access are in `Documentation/Licencing/TERMS_OF_SERVICE.md`.

## Required Release Gate

Run this before publishing:

```bash
python3 tools/release_gate.py
```

The gate validates:

1. Manifest version follows semantic versioning (`MAJOR.MINOR.PATCH`).
2. Changelog has a top release entry for current manifest version.
3. Compatibility matrix references current extension version.
4. Release checklist includes rollback-safe update testing.
