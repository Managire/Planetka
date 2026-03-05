"""
Planetka regression harness for simplified Earth workflows.

Usage:
    /Applications/Blender.app/Contents/MacOS/Blender --background --python tools/planetka_regression_test.py

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


TAG = "[Planetka Regression Test]"
SURFACE_COLLECTION_NAME = "Planetka - Earth Surface Collection"
SURFACE_OBJECT_NAME = "Planetka Earth Surface"


def _log(message):
    print(f"{TAG} {message}")


def _fail(message):
    _log(f"FAIL: {message}")
    raise SystemExit(1)


def _assert(condition, message):
    if not condition:
        _fail(message)


def _assert_close(value, expected, eps, label):
    if abs(float(value) - float(expected)) > float(eps):
        _fail(f"{label} expected {expected}, got {value}")


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


def _purge_existing_planetka_data():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except Exception:
                pass

    for coll in list(bpy.data.collections):
        if not (coll.name.startswith("Planetka") or coll.name.startswith("Regression ")):
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


def _make_texture_source_tree(base_dir, include_supporting=True):
    os.makedirs(base_dir, exist_ok=True)
    basic = os.path.join(_addon_root(), "Resources", "Basic Textures")
    s2_source = os.path.join(basic, "S2_x000_y000_z360_d360.exr")
    _assert(os.path.isfile(s2_source), f"Missing bundled S2 sample: {s2_source}")
    s2_folder = os.path.join(base_dir, "S2")
    os.makedirs(s2_folder, exist_ok=True)
    shutil.copyfile(s2_source, os.path.join(s2_folder, "S2_x000_y000_z360_d360.exr"))
    shutil.copyfile(s2_source, os.path.join(s2_folder, "S2_x180_y000_z180_d180.exr"))

    if not include_supporting:
        return

    rules = (
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

    camera_data = bpy.data.cameras.new("Planetka Regression Camera")
    camera_obj = bpy.data.objects.new("Planetka Regression Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def _surface_local_radius(surface_obj):
    try:
        stored = float(surface_obj.get("planetka_surface_local_radius", 0.0))
    except Exception:
        stored = 0.0
    if stored > 0.0:
        return stored

    mesh_data = getattr(surface_obj, "data", None)
    vertices = getattr(mesh_data, "vertices", None)
    if not vertices:
        return 0.0
    return max(v.co.length for v in vertices)


def _surface_collection_names(surface_obj):
    return sorted(col.name for col in surface_obj.users_collection)


def main():
    temp_dirs = []
    try:
        base_module_name = _enable_module()
        _assert(base_module_name is not None, "Could not enable Planetka extension module.")

        extension_prefs = _import_submodule(base_module_name, "extension_prefs")
        state = _import_submodule(base_module_name, "state")
        animation_tools = _import_submodule(base_module_name, "animation_tools")

        _purge_existing_planetka_data()

        scene = bpy.context.scene
        _ensure_active_camera(scene)
        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")

        _log("Scenario 1: create earth baseline")
        full_source = tempfile.mkdtemp(prefix="planetka_regression_full_")
        temp_dirs.append(full_source)
        _make_texture_source_tree(full_source, include_supporting=True)
        prefs.texture_base_path = full_source

        result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in result, f"Create Earth failed with result: {result}")

        surface = bpy.data.objects.get(SURFACE_OBJECT_NAME)
        _assert(surface is not None, "Planetka Earth Surface missing after Create Earth.")
        _assert(
            _surface_collection_names(surface) == [SURFACE_COLLECTION_NAME],
            "Create Earth did not place surface only in the surface collection.",
        )

        baseline_radius = _surface_local_radius(surface)
        baseline_scale = tuple(surface.scale)
        _assert_close(baseline_radius, 1.0, 0.02, "Baseline local radius")
        _assert_close(baseline_scale[0], 2.0, 0.01, "Baseline scale X")
        _assert_close(baseline_scale[1], 2.0, 0.01, "Baseline scale Y")
        _assert_close(baseline_scale[2], 2.0, 0.01, "Baseline scale Z")

        _log("Scenario 2: resolve preserves old collection placement")
        custom_collection = bpy.data.collections.new("Regression Custom Surface")
        scene.collection.children.link(custom_collection)
        for col in list(surface.users_collection):
            col.objects.unlink(surface)
        custom_collection.objects.link(surface)

        result = bpy.ops.planetka.load_textures()
        _assert("FINISHED" in result, f"Resolve Earth failed with result: {result}")
        surface = bpy.data.objects.get(SURFACE_OBJECT_NAME)
        _assert(surface is not None, "Planetka Earth Surface missing after Resolve Earth.")
        _assert(
            _surface_collection_names(surface) == ["Regression Custom Surface"],
            "Resolve Earth did not preserve old mesh collection placement.",
        )

        _log("Scenario 3: cinematic circle keeps stable altitude")
        props = getattr(scene, "planetka", None)
        _assert(props is not None, "Planetka scene properties are missing.")
        props.anim_camera_preset = "ORBIT"
        props.anim_frame_start = 1
        props.anim_frame_end = 20
        props.anim_orbit_degrees = 270.0
        props.anim_motion_curve = "LINEAR"
        props.nav_altitude_km = 400.0
        props.nav_tilt_deg = 25.0
        props.nav_roll_deg = 0.0

        start_frame, end_frame = animation_tools.apply_cinematic_preview(scene, props)
        earth = bpy.data.objects.get(SURFACE_OBJECT_NAME)
        _assert(earth is not None, "Earth surface object is missing.")
        center = earth.matrix_world.translation.copy()
        camera = scene.camera
        distances = []
        for frame in range(int(start_frame), int(end_frame) + 1):
            scene.frame_set(int(frame))
            dist = float((camera.matrix_world.translation - center).length)
            distances.append(dist)
        drift = max(distances) - min(distances) if distances else 0.0
        _assert(drift < 1e-6, f"Camera altitude drift too high: {drift}")

        _log("Scenario 4: repeated close-range rebuilds do not shrink surface")
        close_tiles = ["x000_y000_z030_d030", "x030_y000_z030_d030"]
        for _ in range(3):
            new_obj = state.create_temp_mesh(
                close_tiles,
                name="Planetka Earth Surface (New)",
                collection_policy="inherit_old",
            )
            _assert(new_obj is not None, "create_temp_mesh returned no object for close-range tiles.")
            state.delete_temp_meshes(keep_obj=new_obj)
            new_obj.name = SURFACE_OBJECT_NAME

        surface = bpy.data.objects.get(SURFACE_OBJECT_NAME)
        _assert(surface is not None, "Planetka Earth Surface missing after close-range rebuilds.")
        final_radius = _surface_local_radius(surface)
        final_scale = tuple(surface.scale)
        _assert_close(final_radius, baseline_radius, 0.02, "Radius after close-range rebuilds")
        _assert_close(final_scale[0], baseline_scale[0], 0.01, "Scale X after close-range rebuilds")
        _assert_close(final_scale[1], baseline_scale[1], 0.01, "Scale Y after close-range rebuilds")
        _assert_close(final_scale[2], baseline_scale[2], 0.01, "Scale Z after close-range rebuilds")

        _log("Scenario 5: S2-only source resolves using support fallbacks")
        s2_only_source = tempfile.mkdtemp(prefix="planetka_regression_s2_only_")
        temp_dirs.append(s2_only_source)
        _make_texture_source_tree(s2_only_source, include_supporting=False)
        prefs.texture_base_path = s2_only_source
        result = bpy.ops.planetka.load_textures()
        _assert("FINISHED" in result, f"Resolve Earth failed for S2-only source: {result}")

        _log("PASS: regression checks passed.")
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
