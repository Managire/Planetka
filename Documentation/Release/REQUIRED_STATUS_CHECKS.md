# Required Status Checks

Use this file when configuring GitHub branch protection for the default branch.

## Required check

Set these checks as **required**:

- `Blender Required Gate / Required Gate (Ubuntu / Blender 5.0.1)`

This gate runs:

- `tools/release_gate.py`
- `tools/planetka_smoke_test.py`
- `tools/planetka_schema_migration_test.py`
- `tools/planetka_regression_test.py`

## Optional (recommended) additional check group

Keep matrix coverage enabled for broader platform/version confidence:

- Workflow: `Blender Integration` (runs on `pull_request` and manual `workflow_dispatch`; skipped for docs/Markdown-only changes)

This workflow is intentionally broader and slower (OS/version matrix) and is best kept as advisory rather than required.
