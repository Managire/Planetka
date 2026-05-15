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
- `tools/planetka_full_release_gate.py --profile release` or an equivalent bounded release profile

The bounded release profile includes:

- regular static/package checks
- Blender core user-flow checks
- Blender UI state regression checks
- stale-auth recovery checks
- bounded live health checks only: 10 scene purchases, 5 country packs, and 2 regions at ordinary pacing

`tools/release_gate.py` hard-fails when any of these release-safety checks regress:
- public API-key request path does not force Free plan
- tile requests stop reading `X-Planetka-Quality-Mode`
- admin analytics query-token rejection is incomplete
- legacy magic-link/device-login routes reappear
- legacy download-throttle / claim-workflow markers reappear
- forbidden legacy vars reappear in `wrangler.toml`
- required fallback assets are missing or deprecated `red_pixel_20.exr` returns
- telemetry retention cleanup wiring is missing

## Maintenance-only stress checks

Do not configure stress checks as required branch-protection checks.

Stress and abuse tests can intentionally push the production Worker into Cloudflare 1102/503 resource-limit responses. During that window, Blender Full Quality price calculation can fail for real users because it depends on the same live commerce endpoints.

Run stress tests only manually, during a controlled maintenance window or against an isolated Worker/database:

- `PLANETKA_ALLOW_LIVE_STRESS=1 python3 tools/planetka_full_release_gate.py --profile stress`
- `python3 tools/worker_abuse_simulation.py --base-url https://api.planetka.io ...`

## Optional (recommended) additional check group

Keep matrix coverage enabled for broader platform/version confidence:

- Workflow: `Blender Integration` (runs on `pull_request` and manual `workflow_dispatch`; skipped for docs/Markdown-only changes)

This workflow is intentionally broader and slower (OS/version matrix) and is best kept as advisory rather than required.
