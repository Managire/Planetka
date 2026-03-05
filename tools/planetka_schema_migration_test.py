"""
Planetka schema migration test.

Usage:
    /Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_schema_migration_test.py

Optional env vars:
    PLANETKA_MODULE=<module-name>  (default autodetects extension module names)
"""

import importlib
import os
import sys
import traceback

import addon_utils
import bpy


TAG = "[Planetka Schema Migration Test]"


def _log(message):
    print(f"{TAG} {message}")


def _fail(message):
    _log(f"FAIL: {message}")
    raise SystemExit(1)


def _assert(condition, message):
    if not condition:
        _fail(message)


def _addon_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _unique(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _enable_module():
    candidates = _unique(
        [
            os.environ.get("PLANETKA_MODULE"),
            "bl_ext.user_default.Planetka",
            "Planetka",
            "planetka",
        ]
    )
    for mod in candidates:
        try:
            addon_utils.enable(mod)
            if hasattr(bpy.types.Scene, "planetka"):
                _log(f"Enabled addon module: {mod}")
                return mod
        except Exception:
            continue

    addon_root = _addon_root()
    parent_dir = os.path.dirname(addon_root)
    package_name = os.path.basename(addon_root)
    if parent_dir and parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    try:
        module = importlib.import_module(package_name)
        if hasattr(module, "register"):
            try:
                module.unregister()
            except Exception:
                pass
            module.register()
        if hasattr(bpy.types.Scene, "planetka"):
            _log(f"Enabled addon module via local import: {package_name}")
            return package_name
    except Exception:
        pass
    return None


def _import_submodule(base_module_name, submodule_name):
    candidates = _unique(
        [
            f"{base_module_name}.{submodule_name}" if base_module_name else None,
            f"bl_ext.user_default.Planetka.{submodule_name}",
            f"Planetka.{submodule_name}",
            f"planetka.{submodule_name}",
        ]
    )
    for mod in candidates:
        try:
            return importlib.import_module(mod)
        except Exception:
            continue
    _fail(f"Could not import submodule '{submodule_name}'. Tried: {', '.join(candidates)}")


def _scenario_bootstrap_migration(state, scene_schema):
    _log("Scenario 1: v0 bootstrap migration")
    scene = bpy.data.scenes.new("PlanetkaSchemaBootstrap")
    try:
        key = scene_schema.SCENE_SCHEMA_KEY
        if key in scene:
            del scene[key]

        props = scene.planetka
        props.auto_resolve = True
        props.debug_logging = True

        state.migrate_scene(scene)
        _assert(
            int(scene.get(key, 0)) == scene_schema.SCENE_SCHEMA_VERSION,
            "bootstrap migration did not reach latest schema version",
        )
        _assert(bool(scene["planetka_auto_resolve"]) is True, "auto_resolve idprop mismatch")
        _assert(bool(scene["planetka_debug_logging"]) is True, "debug_logging idprop mismatch")
    finally:
        bpy.data.scenes.remove(scene)


def _scenario_idempotence(state, scene_schema):
    _log("Scenario 2: idempotent migration")
    scene = bpy.data.scenes.new("PlanetkaSchemaIdempotence")
    try:
        key = scene_schema.SCENE_SCHEMA_KEY
        scene[key] = scene_schema.SCENE_SCHEMA_VERSION
        scene["planetka_auto_resolve"] = False
        scene["planetka_debug_logging"] = False

        snapshot = (
            int(scene.get(key, 0)),
            bool(scene["planetka_auto_resolve"]),
            bool(scene["planetka_debug_logging"]),
        )

        state.migrate_scene(scene)

        current = (
            int(scene.get(key, 0)),
            bool(scene["planetka_auto_resolve"]),
            bool(scene["planetka_debug_logging"]),
        )
        _assert(current == snapshot, "migration changed idprops when schema version was already current")
    finally:
        bpy.data.scenes.remove(scene)


def main():
    try:
        base_module_name = _enable_module()
        _assert(base_module_name is not None, "Could not enable Planetka extension module.")

        state = _import_submodule(base_module_name, "state")
        scene_schema = _import_submodule(base_module_name, "scene_schema")

        _scenario_bootstrap_migration(state, scene_schema)
        _scenario_idempotence(state, scene_schema)

        _log("PASS: schema migration checks passed.")
    except SystemExit:
        raise
    except Exception as exc:
        _log(f"FAIL: unexpected exception: {exc}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
