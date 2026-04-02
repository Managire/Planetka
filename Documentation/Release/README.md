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
