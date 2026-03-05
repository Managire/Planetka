# Planetka Scene Schema Migration

## Purpose

Keep scene data upgrades deterministic and versioned for the simplified public extension.

## Schema Key

- Scene custom property key: `planetka_scene_version`
- Current schema version: `1`
- Source of truth: `/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka/scene_schema.py`

## Migration Steps

1. `v1` bootstrap:
   - Sync current `Scene.planetka` PropertyGroup values into scene idprops.
   - Persist `planetka_scene_version = 1`.

There are no legacy atmosphere/camera-rig migrations in the simplified extension.

## Runtime Integration

- Runtime entry point: `migrate_scene(scene)` in:
  - `/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka/state.py`
- Delegates to:
  - `migrate_scene_schema(scene, sync_idprops_fn, logger)` in `scene_schema.py`

## Backward-Compat Test

- Test script:
  - `/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka/tools/planetka_schema_migration_test.py`
- Covers bootstrap migration and idempotence for schema version `1`.
- Included in CI workflow:
  - `/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka/.github/workflows/blender-integration.yml`
