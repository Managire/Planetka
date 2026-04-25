# Planetka Compatibility Matrix

Current extension release candidate: `v0.7.0`
Public update channel remains on: `v0.5.3`
Last matrix update: `2026-04-25`

| Blender Version | Status | Automated Tests | Notes |
| --- | --- | --- | --- |
| 4.5.7+ | Supported baseline | Smoke + Regression baseline | Public support floor. Versions below 4.5.7 are unsupported. |
| 4.5.7 | Verified (carry-forward baseline) | Smoke + Regression baseline | Adaptive subdivision requires Experimental features on pre-5.0 Blender and is enabled automatically by Planetka where needed. |
| 5.0.0 | Verified | Smoke + Regression + active long stress run | Current release candidate validated locally on macOS. |
| 5.0.1 | Supported target | Manual QA recommended | Keep renderer/GPU caveat checks in manual QA. |
| 5.1.0 | Verified (carry-forward baseline) | Smoke + Regression baseline | Carry-forward target for release readiness; rerun local confirmation before public update upload. |
| 4.2.x / 3.6.x | Unsupported | Not in CI | Material library compatibility is not guaranteed; no release support target for these versions. |

## Extension Release Validation

| Extension Version | Blender Versions Verified | Release Gate | Rollback Test | Notes |
| --- | --- | --- | --- | --- |
| v0.7.0 | 5.0.0 current, 4.5.7/5.1.0 carry-forward baseline | Pass | Pending final soak completion | Package/docs aligned to `0.7.0`; release gate, smoke, and regression pass; long supervised 4K stress run is in progress. Newly issued beta accounts are currently provisioned as `Commercial` by default. This candidate is not uploaded to the public update channel yet. |
| v0.5.3 | 4.5.7, 5.0.0, 5.1.0 | Pass | Pass | Added cache write-path validation, safer earth-surface parent assignment during replacement, and scene-safe background/clipping automation notices. |
| v0.5.1 | 4.5.7, 5.0.0, 5.1.0 | Pass | Pass | Added user-selectable/persistent cache folder and tightened cache limit defaults for public update channel. |
| v0.5.0 | 4.5.7, 5.0.0, 5.1.0 | Pass | Pass | Version bump for current beta branch; compatibility baseline unchanged from v0.4.1. |
| v0.4.1 | 4.5.7, 5.0.0, 5.1.0 | Pass | Pass | Status Check layout stabilized during download progress, adaptive subdivision suspend toggle restore fix, and auto-resolve idle default set to 0.5s. |
| v0.3.0 | 5.0.0, 5.1.0 | Pass | Pass | First public beta release candidate; rollback-safe update flow A -> B -> A executed on 2026-03-28 without blocker errors. |

## Hardware / Renderer Notes

| Component | Status | Notes |
| --- | --- | --- |
| EEVEE (Rendered viewport / segmented animation render) | Supported | EEVEE is supported for Planetka stills, quick previews, and segmented animation rendering in this candidate. Continue manual QA for heavy scenes and long segmented renders. |
| Cycles (GPU/CPU segmented render) | Supported | Cycles is supported for Planetka stills and segmented animation rendering in this candidate. |
| Cycles/EEVEE dynamic tile window | Mitigated | Planetka enforces a pre-shader dynamic tile window of `0..12` tiles (real tiles only, no synthetic floor padding) to avoid EEVEE sampler overflow and Cycles SVM overflow in heavy views. See `Documentation/Developer/CYCLES_SVM_TILE_LIMIT.md`. |
| Adaptive subdivision mode | Locked | Planetka Earth Surface uses `Catmull-Clark` adaptive subdivision (with `Simple` fallback only for enum compatibility). Keep dicing values in the recommended range for final Cycles renders. |
| Solid viewport | Verified | Resolve workflow validated. |
| OpenGL/Cycles/EEVEE preview | Verified by user reports | Stable in reported scenarios. |

## Pre-Publish Requirement

Before publishing:

1. Finish the long 4K still/animation stress run and update this matrix with final pass/fail notes.
2. Re-run exact smoke/regression checks on the final release commit.
3. Keep worker deploy and `tools/release_gate.py` green on the final release commit.
4. Keep the public update channel on `v0.5.3` until the explicit publish decision for `v0.7.0`.
