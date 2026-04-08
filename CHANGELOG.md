# Changelog

All notable changes to Planetka are documented in this file.

## [Unreleased]

### Added
- Added `tools/planetka_regression_test.py` to validate collection behavior, size stability, and S2-only support fallback.

### Changed
- Removed hidden scene/view/render mutations from `Create Earth` and `Prepare Animation Render` flows:
  - no default-scene object deletion on Create Earth
  - no automatic viewport mode switches in Create Earth/animation confirm
  - no automatic Persistent Data/dicing/display-mode/lock-interface overrides when confirming animation render
- Navigation now uses explicit `Bring Camera to View` behavior: Planetka Camera is activated and aligned only when user clicks that action.
- Earth Transform now exposes `Earth Radius` (mesh-radius control) instead of object scale controls.
- Updated default Earth grading values:
  - `Surface Saturation` default to `1.0`
  - `Roughness` default to `0.4`
- Default material displacement mode is now `Displacement` (instead of `Displacement and Bump`), and user displacement-mode edits are preserved across Resolve.
- Preserved user Earth-surface material edits across Resolve by applying default normalization/migration only once per material.
- Updated release QA docs to match the simplified Create/Resolve-only workflow.
- Improved Earth surface shading with procedural forest and rock detail (bump, optional micro-displacement) driven by satellite color/slope masks.
- Marked EEVEE as unsupported/unstable for Planetka rendering in release documentation and UI warnings; Cycles is now auto-selected on `Create Earth`.
- Increased user-editable tile cache limit range to `1–100 GB`.
- Exposed `Data Cache Limit (GB)` in the Settings panel so users can edit it directly in UI.

### Fixed
- Removed outdated release-checklist references to preview parenting.

## [v0.5.0] - 2026-04-08

### Changed
- Bumped addon package/update version to `0.5.0`.

## [v0.4.1] - 2026-04-06

### Changed
- Status Check now keeps a stable layout while downloading by rendering progress inline in the status text.
- Status label text shortened from `Downloading Data` to `Downloading`.
- Auto Resolve Idle Delay default set to `0.5s`.

### Fixed
- Adaptive subdivision navigation suspension now force-restores immediately when:
  - `Suspend Adaptive Subdivision While Navigating` is turned off, or
  - render engine is not Cycles.
- Prevented stale suspended state from persisting after toggle/engine changes.

## [v0.4.0] - 2026-04-06

### Changed
- Removed hidden scene/view/render mutations from Create Earth and Prepare Animation Render confirmation.
- Create Earth no longer deletes Blender default scene objects/collection.
- Navigation now uses explicit `Bring Camera to View` action to activate/move Planetka Camera.
- Replaced Earth Transform scale controls with `Earth Radius` control.
- Updated Earth grading defaults: `Surface Saturation = 1.0`, `Roughness = 0.4`.
- Default Earth material displacement mode is now `Displacement` (not `Displacement and Bump`).

### Fixed
- Preserved user-edited displacement mode and grading values across Resolve by avoiding repeated default overrides.

## [v0.3.0] - 2026-04-02

### Added
- Marked this build as the first public beta release.
- Added beta-focused legal/release documentation updates for tester distribution.

### Changed
- Set extension manifest version to `0.3.0` for the public beta package.
- Updated compatibility/release docs to reflect the public beta state.

## [v0.2.0] - 2026-02-20

### Added
- Strict preflight validation for core actions (`Create Earth`, `Resolve Earth`, `Prepare for Render`).
- Role-based rig object resolution to reduce name-coupling.
- Telemetry-friendly JSON debug report export.

### Changed
- Driver setup and node traversal performance improved with scan caps and caching.
- Release documentation expanded with compatibility and rollback-safe testing guidance.

### Fixed
- Multiple driver rebuild and rig-binding reliability issues across renamed objects and imported scenes.
