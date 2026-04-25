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
- `tools/worker_abuse_simulation.py --base-url https://api.planetka.io --tile-requests 60`
- `tools/worker_abuse_simulation.py --base-url https://api.planetka.io --tile-requests 60 --analytics-minutes 60` (authenticated; requires GitHub secret `PLANETKA_CI_BEARER_TOKEN`)

`tools/release_gate.py` hard-fails when any of these release-safety checks regress:
- public API-key request path does not force Free plan
- tile requests stop reading `X-Planetka-Quality-Mode`
- admin analytics query-token rejection is incomplete
- legacy magic-link/device-login routes reappear
- legacy download-throttle / claim-workflow markers reappear
- forbidden legacy vars reappear in `wrangler.toml`
- required fallback assets are missing or deprecated `red_pixel_20.exr` returns
- telemetry retention cleanup wiring is missing

## Optional (recommended) additional check group

Keep matrix coverage enabled for broader platform/version confidence:

- Workflow: `Blender Integration` (runs on `pull_request` and manual `workflow_dispatch`; skipped for docs/Markdown-only changes)

This workflow is intentionally broader and slower (OS/version matrix) and is best kept as advisory rather than required.
