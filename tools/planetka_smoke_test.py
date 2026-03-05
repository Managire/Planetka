"""
Planetka smoke harness for Blender background runs.

Usage:
    /Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_smoke_test.py

Optional env vars:
    PLANETKA_MODULE=<module-name>  (default autodetects extension module names)
"""

import importlib
import math
import os
import shutil
import sys
import tempfile
import traceback

import addon_utils
import bpy


TAG = "[Planetka Smoke Test]"


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
            if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
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
        if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
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


def _driver_count(id_data):
    anim = getattr(id_data, "animation_data", None)
    drivers = getattr(anim, "drivers", None) if anim else None
    return len(drivers) if drivers else 0


def _planetka_driver_count():
    total = 0
    for obj in bpy.data.objects:
        if not obj.name.startswith("Planetka"):
            continue
        total += _driver_count(obj)
        data = getattr(obj, "data", None)
        if data is not None:
            total += _driver_count(data)

    for material in bpy.data.materials:
        if material.name.startswith("Planetka"):
            total += _driver_count(material)

    for node_group in bpy.data.node_groups:
        if node_group.name.startswith("Planetka"):
            total += _driver_count(node_group)

    return total


def _purge_existing_planetka_data():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass

    for coll in list(bpy.data.collections):
        if not coll.name.startswith("Planetka"):
            continue
        for scene in bpy.data.scenes:
            try:
                if coll in scene.collection.children:
                    scene.collection.children.unlink(coll)
            except Exception:
                pass
        try:
            bpy.data.collections.remove(coll)
        except Exception:
            pass

    for material in list(bpy.data.materials):
        if material.name.startswith("Planetka"):
            try:
                bpy.data.materials.remove(material, do_unlink=True)
            except Exception:
                pass

    for node_group in list(bpy.data.node_groups):
        if node_group.name.startswith("Planetka"):
            try:
                bpy.data.node_groups.remove(node_group, do_unlink=True)
            except Exception:
                pass


def _make_texture_source_tree(base_dir):
    os.makedirs(base_dir, exist_ok=True)
    basic = os.path.join(_addon_root(), "Resources", "Basic Textures")

    rules = (
        ("S2", "S2_", ".exr", "S2_x000_y000_z360_d360.exr"),
        ("EL", "EL_", ".exr", "EL_x000_y000_z360_d360.exr"),
        ("WT", "WT_", ".exr", "WT_x000_y000_z360_d360.exr"),
        ("PO", "PO_", ".tif", "PO_x000_y000_z360_d360.tif"),
    )
    for folder_name, prefix, ext, source_name in rules:
        source = os.path.join(basic, source_name)
        _assert(os.path.isfile(source), f"Missing bundled texture sample: {source}")
        folder = os.path.join(base_dir, folder_name)
        os.makedirs(folder, exist_ok=True)
        shutil.copyfile(source, os.path.join(folder, f"{prefix}x000_y000_z360_d360{ext}"))
        shutil.copyfile(source, os.path.join(folder, f"{prefix}x180_y000_z180_d180{ext}"))


def _ensure_active_camera(scene):
    current = getattr(scene, "camera", None)
    if current and getattr(current, "type", None) == "CAMERA":
        return current

    for obj in scene.objects:
        if obj.type == "CAMERA":
            scene.camera = obj
            return obj

    camera_data = bpy.data.cameras.new("Planetka Smoke Camera")
    camera_obj = bpy.data.objects.new("Planetka Smoke Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def _get_subsurf_modifier(surface):
    for modifier in surface.modifiers:
        if modifier.type == "SUBSURF":
            return modifier
    return None


def main():
    temp_dirs = []
    try:
        base_module_name = _enable_module()
        _assert(base_module_name is not None, "Could not enable Planetka extension module.")
        extension_prefs = _import_submodule(base_module_name, "extension_prefs")

        _purge_existing_planetka_data()

        _log("1/4 Configure texture source and camera")
        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")
        valid_path = tempfile.mkdtemp(prefix="planetka_smoke_valid_")
        temp_dirs.append(valid_path)
        _make_texture_source_tree(valid_path)
        prefs.texture_base_path = valid_path

        scene = bpy.context.scene
        _ensure_active_camera(scene)

        _log("2/4 Create Earth then Resolve Earth")
        result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in result, f"Create Earth failed with result: {result}")

        result = bpy.ops.planetka.load_textures()
        _assert("FINISHED" in result, f"Resolve Earth failed with result: {result}")

        surface = bpy.data.objects.get("Planetka Earth Surface")
        _assert(surface is not None, "Planetka Earth Surface is missing after Resolve Earth.")
        _assert(surface.parent is None, "Resolved Earth surface unexpectedly has a parent.")
        _assert(surface.data and len(surface.data.materials) > 0, "Resolved Earth surface has no material assigned.")
        _assert(surface.data.materials[0].name == "Planetka Earth Material", "Resolved Earth material is incorrect.")
        _assert(
            bpy.data.collections.get("Planetka - Earth Surface Collection") is not None,
            "Expected Earth surface collection is missing.",
        )

        subsurf = _get_subsurf_modifier(surface)
        _assert(subsurf is not None, "Adaptive Subdivision modifier is missing.")
        if hasattr(subsurf, "subdivision_type"):
            _assert(
                subsurf.subdivision_type == "CATMULL_CLARK",
                f"Adaptive Subdivision type is {subsurf.subdivision_type}, expected CATMULL_CLARK.",
            )
        adaptive_enabled = bool(getattr(subsurf, "use_adaptive_subdivision", False))
        surface_cycles = getattr(surface, "cycles", None)
        if surface_cycles is not None:
            adaptive_enabled = adaptive_enabled or bool(
                getattr(surface_cycles, "use_adaptive_subdivision", False)
            )
        _assert(adaptive_enabled, "Adaptive subdivision is not enabled on modifier or object.")

        _log("3/4 Validate driver-free state and viewport subdivision")
        _assert(_planetka_driver_count() == 0, "Planetka datablocks still contain drivers.")
        _assert(bool(subsurf.show_viewport), "Adaptive subdivision viewport display must always stay enabled.")

        _log("PASS: simplified smoke checks passed.")
    except SystemExit:
        raise
    except Exception as exc:
        _log(f"FAIL: unexpected exception: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
    finally:
        for path in temp_dirs:
            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()
