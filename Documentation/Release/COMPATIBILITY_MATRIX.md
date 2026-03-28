# Planetka Compatibility Matrix

Current extension release candidate: `v0.2.0`
Last matrix update: `2026-03-28`

| Blender Version | Status | Automated Tests | Notes |
| --- | --- | --- | --- |
| 3.6+ | Supported baseline | Smoke + Schema migration + Regression | Public support floor. Versions below 3.6 are unsupported. |
| 3.6.0 | CI target | Smoke + Schema migration + Regression | Added to CI matrix for compatibility coverage. |
| 4.2.0 | CI target | Smoke + Schema migration + Regression | Added to CI matrix for compatibility coverage. |
| 5.0.0 | Verified | Smoke + Schema migration + Regression | Core workflows validated. |
| 5.0.1 | Verified (CI) | Smoke + Schema migration + Regression | Keep renderer/GPU caveat checks in manual QA. |
| 5.1.0 | Verified (local) + CI target | Smoke + Schema migration + Regression | Verified locally on macOS on release day; required gate updated to 5.1.0. |
| Other 3.x/4.x | Expected supported | Not in CI | Re-test recommended before release sign-off. |

## Extension Release Validation

| Extension Version | Blender Versions Verified | Release Gate | Rollback Test | Notes |
| --- | --- | --- | --- | --- |
| v0.2.0 | 5.0.0, 5.1.0 | Pass | Pass | Initial public release candidate; rollback-safe update flow A -> B -> A executed on 2026-03-28 without blocker errors. |

## Hardware / Renderer Notes

| Component | Status | Notes |
| --- | --- | --- |
| EEVEE (Rendered viewport) | Unsupported / Unstable | Known limitation for this release. EEVEE can produce corrupted frames (missing/pink/solid tiles), especially on macOS/Metal at higher tile counts. Use Cycles for reliable output. |
| Solid viewport | Verified | Resolve workflow validated. |
| OpenGL/Cycles preview | Verified by user reports | Stable in reported scenarios. |

## Pre-Publish Requirement

Before publishing:

1. Update this matrix with exact tested Blender patch versions.
2. Record pass/fail for smoke and schema migration scripts.
3. Include any renderer/GPU caveats discovered during QA.
