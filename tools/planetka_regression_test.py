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
import time
import traceback
import os
import sys
from types import SimpleNamespace

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

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
        except TOOL_RECOVERABLE_EXCEPTIONS:
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
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            module.register()
        if hasattr(bpy.ops, "planetka") and hasattr(bpy.ops.planetka, "add_earth"):
            _log(f"Enabled addon module via local import: {package_name}")
            return package_name
    except TOOL_RECOVERABLE_EXCEPTIONS:
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
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    _fail(f"Could not import submodule '{submodule_name}'. Tried: {', '.join(candidates)}")


def _purge_existing_planetka_data():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for coll in list(bpy.data.collections):
        if not (coll.name.startswith("Planetka") or coll.name.startswith("Regression ")):
            continue
        for scene in bpy.data.scenes:
            try:
                if coll in scene.collection.children:
                    scene.collection.children.unlink(coll)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
        try:
            bpy.data.collections.remove(coll)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass

    for material in list(bpy.data.materials):
        if material.name.startswith("Planetka"):
            try:
                bpy.data.materials.remove(material, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

    for node_group in list(bpy.data.node_groups):
        if node_group.name.startswith("Planetka"):
            try:
                bpy.data.node_groups.remove(node_group, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


def _make_texture_source_tree(base_dir, include_supporting=True):
    os.makedirs(base_dir, exist_ok=True)
    fallback = os.path.join(_addon_root(), "Resources", "Fallback Images")
    s2_source = os.path.join(fallback, "ocean_pixel_final_20.exr")
    _assert(os.path.isfile(s2_source), f"Missing bundled fallback S2 sample: {s2_source}")
    s2_folder = os.path.join(base_dir, "S2")
    os.makedirs(s2_folder, exist_ok=True)
    shutil.copyfile(s2_source, os.path.join(s2_folder, "S2_x000_y000_z360_d360.exr"))
    shutil.copyfile(s2_source, os.path.join(s2_folder, "S2_x180_y000_z180_d180.exr"))
    os.makedirs(os.path.join(base_dir, "PO"), exist_ok=True)

    if not include_supporting:
        return

    rules = (
        ("EL", "EL_", ".exr", "black_pixel_20.exr"),
        ("WT", "WT_", ".exr", "blue_pixel_20.exr"),
    )
    for folder_name, prefix, ext, source_name in rules:
        source = os.path.join(fallback, source_name)
        _assert(os.path.isfile(source), f"Missing bundled fallback texture sample: {source}")
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
    except TOOL_RECOVERABLE_EXCEPTIONS:
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


def _drain_queued_resolve(state_module, scene, timeout_sec=8.0):
    runtime_status_fn = getattr(state_module, "get_resolve_runtime_status", None)
    pump_fn = getattr(state_module, "_auto_resolve_download_pump_timer", None)
    stop_fn = getattr(state_module, "stop_auto_resolve_download_pipeline", None)
    start = time.monotonic()
    last_status = {}
    while True:
        if callable(pump_fn):
            try:
                pump_fn()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                _fail("Queued resolve pump raised an unexpected exception.")
        if callable(runtime_status_fn):
            try:
                last_status = dict(runtime_status_fn(scene) or {})
            except TOOL_RECOVERABLE_EXCEPTIONS:
                last_status = {}
        running = bool(last_status.get("running", False))
        pending_count = int(last_status.get("pending_count", 0) or 0)
        code = str(last_status.get("code", "") or "")
        if not running and pending_count <= 0 and code in {"", "IDLE"}:
            return
        if time.monotonic() - start > float(timeout_sec):
            if callable(stop_fn):
                try:
                    stop_fn()
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass
            _fail(f"Queued Create Earth resolve did not complete in time: {last_status}")
        time.sleep(0.05)


def main():
    temp_dirs = []
    try:
        base_module_name = _enable_module()
        _assert(base_module_name is not None, "Could not enable Planetka extension module.")

        extension_prefs = _import_submodule(base_module_name, "extension_prefs")
        state = _import_submodule(base_module_name, "state")
        animation_tools = _import_submodule(base_module_name, "animation_tools")
        navigation_runtime = _import_submodule(base_module_name, "planetka_runtime.navigation_runtime")

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
        _drain_queued_resolve(state, scene)
        status_after_create = dict(state.get_resolve_runtime_status(scene) or {})
        _assert(
            str(status_after_create.get("code", "") or "IDLE") == "IDLE",
            f"Queued Create Earth resolve did not return to IDLE: {status_after_create}",
        )

        surface = bpy.data.objects.get(SURFACE_OBJECT_NAME)
        _assert(surface is not None, "Planetka Earth Surface missing after Create Earth.")
        _assert(
            _surface_collection_names(surface) == [SURFACE_COLLECTION_NAME],
            "Create Earth did not place surface only in the surface collection.",
        )

        baseline_radius = _surface_local_radius(surface)
        baseline_scale = tuple(surface.scale)
        # Current runtime keeps Earth mesh radius directly in local geometry and
        # keeps object scale neutral.
        _assert_close(baseline_radius, 2.0, 0.02, "Baseline local radius")
        _assert_close(baseline_scale[0], 1.0, 0.01, "Baseline scale X")
        _assert_close(baseline_scale[1], 1.0, 0.01, "Baseline scale Y")
        _assert_close(baseline_scale[2], 1.0, 0.01, "Baseline scale Z")

        _log("Scenario 2: external camera move syncs Navigation controls")
        props = getattr(scene, "planetka", None)
        _assert(props is not None, "Planetka scene properties are missing.")
        camera = scene.camera
        _assert(camera is not None and getattr(camera, "type", None) == "CAMERA", "Active camera is missing.")
        before_nav = (
            float(getattr(props, "nav_latitude_deg", 0.0)),
            float(getattr(props, "nav_longitude_deg", 0.0)),
            float(getattr(props, "nav_altitude_km", 0.0)),
            float(getattr(props, "nav_azimuth_deg", 0.0)),
            float(getattr(props, "nav_tilt_deg", 0.0)),
            float(getattr(props, "nav_roll_deg", 0.0)),
        )
        camera.location.x += 4.0
        camera.location.y += 3.0
        camera.location.z += 2.0
        camera.rotation_euler.z += math.radians(20.0)
        bpy.context.view_layer.update()
        state._sync_navigation_controls_from_scene_camera(scene)
        after_nav = (
            float(getattr(props, "nav_latitude_deg", 0.0)),
            float(getattr(props, "nav_longitude_deg", 0.0)),
            float(getattr(props, "nav_altitude_km", 0.0)),
            float(getattr(props, "nav_azimuth_deg", 0.0)),
            float(getattr(props, "nav_tilt_deg", 0.0)),
            float(getattr(props, "nav_roll_deg", 0.0)),
        )
        _assert(
            any(abs(float(after_nav[i]) - float(before_nav[i])) > 1e-5 for i in range(len(before_nav))),
            "Navigation controls did not update after external camera move.",
        )

        _log("Scenario 3: Earth radius change preserves generic scene-camera altitude")
        generic_camera = scene.camera
        _assert(generic_camera is not None and getattr(generic_camera, "type", None) == "CAMERA", "Generic scene camera missing.")
        _assert(
            "planetka" not in str(getattr(generic_camera, "name", "") or "").strip().lower()
            or str(getattr(generic_camera, "name", "") or "").strip() == "Planetka Regression Camera",
            "Regression scenario expects a normal scene camera.",
        )
        props.nav_latitude_deg = -33.9249
        props.nav_longitude_deg = 18.4241
        props.nav_altitude_km = 120.0
        props.nav_azimuth_deg = 48.0
        props.nav_tilt_deg = 40.0
        props.nav_roll_deg = -4.0
        result = bpy.ops.planetka.navigation_apply_shot()
        _assert("FINISHED" in result, f"navigation_apply_shot failed before radius change: {result}")
        props.earth_radius_bu = 2.6
        bpy.context.view_layer.update()
        altitude_info = dict(state._resolve_scope_altitude_info(scene, scope_mode="CAMERA") or {})
        _assert(not bool(altitude_info.get("inside_earth", False)), f"Earth radius change pushed generic camera below surface: {altitude_info}")
        result = bpy.ops.planetka.load_textures()
        _assert("FINISHED" in result, f"Resolve Earth failed after radius change on generic camera: {result}")
        warning = str(state.get_camera_inside_earth_warning(scene) or "").strip()
        _assert(not warning, f"Inside-Earth warning should stay clear after radius change, got: {warning}")
        props.earth_radius_bu = baseline_radius
        bpy.context.view_layer.update()

        _log("Scenario 4: resolve preserves old collection placement")
        surface = bpy.data.objects.get(SURFACE_OBJECT_NAME)
        _assert(surface is not None, "Planetka Earth Surface missing before collection-placement regression check.")
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

        _log("Scenario 5: cinematic circle keeps stable altitude")
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

        _log("Scenario 6: repeated close-range rebuilds do not shrink surface")
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

        _log("Scenario 7: S2-only source resolves using support fallbacks")
        s2_only_source = tempfile.mkdtemp(prefix="planetka_regression_s2_only_")
        temp_dirs.append(s2_only_source)
        _make_texture_source_tree(s2_only_source, include_supporting=False)
        prefs.texture_base_path = s2_only_source
        result = bpy.ops.planetka.load_textures()
        _assert("FINISHED" in result, f"Resolve Earth failed for S2-only source: {result}")

        _log("Scenario 8: silent navigation apply skips operator when Earth is missing")
        scene.camera = _ensure_active_camera(scene)
        operator_called = {"value": False}

        def _unexpected_navigation_apply_shot(**_kwargs):
            operator_called["value"] = True
            return {"FINISHED"}

        fake_bpy = SimpleNamespace(
            context=SimpleNamespace(scene=scene),
            ops=SimpleNamespace(
                planetka=SimpleNamespace(
                    navigation_apply_shot=_unexpected_navigation_apply_shot,
                )
            ),
        )
        runtime = SimpleNamespace(
            deps=SimpleNamespace(
                bpy=fake_bpy,
                logger=state.logger,
                recoverable_exceptions=TOOL_RECOVERABLE_EXCEPTIONS,
                get_earth_object=lambda: None,
                nav_force_camera_once_key="planetka_nav_force_camera_once",
                nav_sync_active_view_once_key="planetka_nav_sync_active_view_once",
            ),
            state=SimpleNamespace(
                navigation_shot_update_reentrant=False,
            ),
        )
        skipped = navigation_runtime.apply_navigation_shot_now(
            runtime,
        )
        _assert(skipped is False, "Silent navigation apply should return False when Earth is missing.")
        _assert(not operator_called["value"], "Silent navigation apply should not invoke the operator when Earth is missing.")

        _log("Scenario 9: saved startup profile restores cleanly on Create Earth")
        expected = {
            "nav_altitude_km": 234.0,
            "nav_azimuth_deg": 57.0,
            "nav_tilt_deg": 39.0,
            "sunlight_longitude_deg": 77.0,
            "sunlight_strength": 17.0,
            "sunlight_seasonal_tilt_deg": 12.0,
            "earth_radius_bu": 3.5,
            "texture_quality_mode": "BALANCED",
            "auto_resolve": False,
            "show_earth_preview": False,
            "anim_camera_preset": "ZOOM",
        }
        props.nav_altitude_km = expected["nav_altitude_km"]
        props.nav_azimuth_deg = expected["nav_azimuth_deg"]
        props.nav_tilt_deg = expected["nav_tilt_deg"]
        props.nav_roll_deg = 0.0
        props.sunlight_longitude_deg = expected["sunlight_longitude_deg"]
        props.sunlight_strength = expected["sunlight_strength"]
        props.sunlight_seasonal_tilt_deg = expected["sunlight_seasonal_tilt_deg"]
        props.earth_radius_bu = expected["earth_radius_bu"]
        props.texture_quality_mode = expected["texture_quality_mode"]
        props.auto_resolve = expected["auto_resolve"]
        props.show_earth_preview = expected["show_earth_preview"]
        props.anim_camera_preset = expected["anim_camera_preset"]
        result = bpy.ops.planetka.save_startup_setup()
        _assert("FINISHED" in result, f"Save Startup Setup failed with result: {result}")

        _purge_existing_planetka_data()
        _ensure_active_camera(scene)
        props = getattr(scene, "planetka", None)
        _assert(props is not None, "Planetka scene properties disappeared after purge.")
        props.nav_altitude_km = 50.0
        props.texture_quality_mode = "PREVIEW"
        props.anim_camera_preset = "NONE"

        result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in result, f"Create Earth with saved startup setup failed with result: {result}")
        _drain_queued_resolve(state, scene)
        _assert_close(float(getattr(props, "nav_altitude_km", 0.0)), expected["nav_altitude_km"], 1e-4, "Restored startup altitude")
        _assert_close(float(getattr(props, "nav_azimuth_deg", 0.0)), expected["nav_azimuth_deg"], 1e-4, "Restored startup azimuth")
        _assert_close(float(getattr(props, "nav_tilt_deg", 0.0)), expected["nav_tilt_deg"], 1e-4, "Restored startup tilt")
        _assert_close(float(getattr(props, "sunlight_longitude_deg", 0.0)), expected["sunlight_longitude_deg"], 1e-4, "Restored startup sunlight longitude")
        _assert_close(float(getattr(props, "sunlight_strength", 0.0)), expected["sunlight_strength"], 1e-4, "Restored startup sunlight strength")
        _assert_close(float(getattr(props, "earth_radius_bu", 0.0)), expected["earth_radius_bu"], 1e-4, "Restored startup Earth radius")
        _assert(str(getattr(props, "texture_quality_mode", "")) == "PREVIEW", "Create Earth should still force Preview texture quality after startup restore.")
        _assert(str(getattr(props, "anim_camera_preset", "")) == "NONE", "Create Earth should still force animation preset back to NONE.")
        result = bpy.ops.planetka.reset_startup_setup_factory()
        _assert("FINISHED" in result, f"Reset Startup Setup failed with result: {result}")

        _log("PASS: regression checks passed.")
    except SystemExit:
        raise
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        _log(f"FAIL: unexpected exception: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
    finally:
        for path in temp_dirs:
            try:
                shutil.rmtree(path, ignore_errors=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


if __name__ == "__main__":
    main()
