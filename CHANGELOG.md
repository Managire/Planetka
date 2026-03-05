# Changelog

All notable changes to Planetka are documented in this file.

## [Unreleased]

### Added
- Added `tools/planetka_regression_test.py` to validate collection behavior, size stability, and S2-only support fallback.

### Changed
- Updated release QA docs to match the simplified Create/Resolve-only workflow.
- Improved Earth surface shading with procedural forest and rock detail (bump, optional micro-displacement) driven by satellite color/slope masks.

### Fixed
- Removed outdated release-checklist references to preview parenting.

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
