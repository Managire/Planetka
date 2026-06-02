# Changelog

## [v0.8.3] - 2026-06-02

- Simplified Planetka to one runtime access path backed by anonymous install sessions and short-lived tile session tokens.
- Made `Resolve Planetka` the single manual data update action, with Create Earth allowed to run the initial resolve once.
- Kept Earth surface data, texture-based clouds, and VDB clouds on the same deterministic resolve path.
- Removed obsolete account-level feature gates and automatic background data-refresh workflows from the active add-on model.
- Removed render-time data recovery so rendering never triggers downloads.
- Simplified Data Control, General Settings, and Cloud panels for public beta review.
