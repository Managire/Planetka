# Required Status Checks

Use this file when configuring GitHub branch protection for the default branch.

## Required check

Set these checks as **required**:

- `Blender Required Gate / Required Gate (Ubuntu / Blender 5.1.0)`

This gate runs:

- `tools/release_gate.py`
- `tools/planetka_smoke_test.py`
- `tools/planetka_schema_migration_test.py`
- `tools/planetka_regression_test.py`

`tools/release_gate.py` now also hard-fails on release-safety guards:
- paid-claim elevation safeguards present
- admin analytics query-token rejection present
- legacy magic-link auth default-off in production
- required fallback assets present and deprecated `red_pixel_20.exr` absent
- telemetry retention cleanup wiring present

## Optional (recommended) additional check group

Keep matrix coverage enabled for broader platform/version confidence:

- Workflow: `Blender Integration` (runs on `pull_request` and manual `workflow_dispatch`; skipped for docs/Markdown-only changes)

This workflow is intentionally broader and slower (OS/version matrix) and is best kept as advisory rather than required.
