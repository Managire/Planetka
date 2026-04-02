# Planetka Compatibility Matrix

Current extension release candidate: `v0.3.0`
Last matrix update: `2026-04-02`

| Blender Version | Status | Automated Tests | Notes |
| --- | --- | --- | --- |
| 4.5.7+ | Supported baseline | Smoke + Schema migration + Regression | Public support floor. Versions below 4.5.7 are unsupported. |
| 4.5.7 | Verified (local) | Smoke + Schema migration + Regression | Adaptive subdivision requires Experimental features on pre-5.0 Blender and is enabled automatically by Planetka where needed. |
| 5.0.0 | Verified | Smoke + Schema migration + Regression | Core workflows validated. |
| 5.0.1 | Verified (CI) | Smoke + Schema migration + Regression | Keep renderer/GPU caveat checks in manual QA. |
| 5.1.0 | Verified (local) + CI target | Smoke + Schema migration + Regression | Verified locally on macOS on release day; required gate updated to 5.1.0. |
| 4.2.x / 3.6.x | Unsupported | Not in CI | Material library compatibility is not guaranteed; no release support target for these versions. |

## Extension Release Validation

| Extension Version | Blender Versions Verified | Release Gate | Rollback Test | Notes |
| --- | --- | --- | --- | --- |
| v0.3.0 | 5.0.0, 5.1.0 | Pass | Pass | First public beta release candidate; rollback-safe update flow A -> B -> A executed on 2026-03-28 without blocker errors. |

## Hardware / Renderer Notes

| Component | Status | Notes |
| --- | --- | --- |
| EEVEE (Rendered viewport) | Supported | EEVEE is supported for Planetka workflows in this release. |
| Cycles/EEVEE dynamic tile window | Mitigated | Planetka enforces a pre-shader dynamic tile window of `0..12` tiles (real tiles only, no synthetic floor padding) to avoid EEVEE sampler overflow and Cycles SVM overflow in heavy views. See `Documentation/Developer/CYCLES_SVM_TILE_LIMIT.md`. |
| Solid viewport | Verified | Resolve workflow validated. |
| OpenGL/Cycles/EEVEE preview | Verified by user reports | Stable in reported scenarios. |

## Pre-Publish Requirement

Before publishing:

1. Update this matrix with exact tested Blender patch versions.
2. Record pass/fail for smoke and schema migration scripts.
3. Include any renderer/GPU caveats discovered during QA.
