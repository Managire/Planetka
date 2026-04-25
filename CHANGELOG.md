# Changelog

All notable changes to Planetka are documented in this file.

## [Unreleased]

- No unreleased changes recorded yet.

## [v0.7.0] - 2026-04-25

### Added
- Added `Remove Default Cube Scene` for pristine default Blender scenes before `Create Earth`.
- Added dedicated `Planetka Camera` creation so `Create Earth` no longer needs to repurpose the user's existing camera.
- Added `Rebuild Earth` flow that preserves Earth settings and camera state while recreating Planetka-managed objects.
- Added `Quick Preview` build for animations so users can prepare preview-only segment visibility directly in the scene.
- Added `Scene Health Check` and detailed report output for common scene, shader, camera, and render-state failures.
- Added inline `Below Earth's surface` and `Low altitude` warnings to stop invalid auto-resolve states without pushing users into rebuild flow.
- Added `tools/planetka_regression_test.py` to validate collection behavior, size stability, camera sync, and S2-only support fallback.

### Changed
- `Create Earth` no longer mutates the user's active camera or view unexpectedly.
- `Create Earth` now builds Planetka-owned scene objects only and keeps non-Planetka objects untouched.
- Navigation and animation presets now rebuild around the current Planetka location/camera state instead of relying on stale hidden references.
- `Data Control` now reports live resolve size estimates, last resolve summary, and simplified status messaging in MB.
- `Final Animation Render` now uses the segmented Planetka render path with full-quality tiles, while `Quick Preview` remains preview-only.
- Account UI now shows current account type, inline API-key connection state, and upgrade action for non-Commercial tiers.
- Resolve success path no longer refreshes account profile on every resolve; account sync is kept for real auth/throttle error paths only.
- Tile streaming hot path was simplified with cached lightweight auth claims and tile session tokens to reduce per-tile overhead.
- Public build profile keeps clouds and legacy-only runtime surface disabled by default.
- Release documentation now treats `v0.7.0` as the current private beta candidate while leaving the public update channel unchanged.
- Beta-facing docs now state explicitly that `v0.7.0` currently runs in `unrestricted` beta access mode, giving testers Commercial-equivalent hosted-service access during beta.
- EEVEE is documented as supported for stills, quick previews, and segmented animation rendering in `v0.7.0`.

### Fixed
- Fixed repeated hidden UI/view side effects in `Create Earth`, resolve, and animation confirmation flows.
- Fixed render-engine warning flow so invalid inside-Earth navigation shows a simple warning instead of a false rebuild failure.
- Fixed unresolved hidden resolve overhead caused by success-path account-profile sync after every resolve.
- Fixed documentation drift between package version, compatibility notes, and beta checklist.

## [v0.5.3] - 2026-04-12

### Changed
- Default texture quality after `Create Earth` is now `Preview`.
- Added cache-folder write validation before applying user-selected cache directory.
- Added scene-safe clipping auto-adjust flow and status notices for supported scenes.
- Added automatic default-world gray-to-black background normalization with status notice.

### Fixed
- Hardened Earth-surface parenting to reduce rare orphan surface outcomes during mesh replacement.
- Improved staging-mesh cleanup on unexpected resolve replacement exceptions.
- Added safeguards around cache-folder persistence fallback when selected path is not writable.

## [v0.5.1] - 2026-04-09

### Added
- Added `Data Cache Folder` setting in `Advanced Settings -> Data Cache` so users can choose cache location.

### Changed
- Cache folder selection now persists globally (outside Blender version folders) and is auto-applied as startup default.
- Data cache size defaults/limits changed to:
  - default: `1 GB`
  - range: `1..25 GB`
- Animation Checklist now warns in both `Preview` and `Balanced` quality modes with `Full Quality mode recommended.`

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
