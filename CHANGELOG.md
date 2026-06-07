# Changelog

## [v0.9.1] - 2026-06-07

- Restored the in-add-on update checker and installer.
- Update installation now writes the downloaded package immediately, then asks for Blender restart to load the new code.
- Added startup safety handling for any pending staged update left by older beta builds.

## [v0.9.0] - 2026-06-07

- Rebuilt the public beta package from the current simplified Planetka runtime.
- Requires users to update from older beta builds; 0.8.3 backwards compatibility is not maintained.
- Keeps anonymous Planetka Cloud connection and manual Resolve Planetka workflow as the supported runtime path.

## [v0.8.3] - 2026-06-02

- Simplified Planetka to one runtime access path backed by anonymous install sessions and short-lived tile session tokens.
- Made `Resolve Planetka` the single manual data update action, with Create Earth allowed to run the initial resolve once.
- Kept Earth surface data, texture-based clouds, and VDB clouds on the same deterministic resolve path.
- Removed obsolete account-level feature gates and automatic background data-refresh workflows from the active add-on model.
- Removed render-time data recovery so rendering never triggers downloads.
- Simplified Data Control, General Settings, and Cloud panels for public beta review.
