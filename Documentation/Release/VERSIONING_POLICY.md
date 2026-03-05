# Planetka Versioning Policy

Planetka uses semantic versioning for extension releases:

- `MAJOR.MINOR.PATCH`
- Source of truth: `version` in `blender_manifest.toml`

## Bump Rules

1. `PATCH` (`0.2.0` -> `0.2.1`)
- Bug fixes, stability fixes, docs-only changes, test/process improvements.
- No intentional user-facing behavior change.

2. `MINOR` (`0.2.0` -> `0.3.0`)
- New user-facing functionality or meaningful workflow expansion.
- Backward compatible for existing scenes unless explicitly documented.

3. `MAJOR` (`0.x.y` -> `1.0.0` or `1.y.z` -> `2.0.0`)
- Breaking behavior, incompatible data flow, or removed public features.

## Release Requirements

Before release:

1. Update `blender_manifest.toml` version.
2. Add matching top changelog entry in `CHANGELOG.md`.
3. Update `Documentation/Release/COMPATIBILITY_MATRIX.md`.
4. Run `python3 tools/release_gate.py`.
