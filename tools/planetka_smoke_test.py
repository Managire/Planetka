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
import time
import traceback
import os
import sys

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_TOOLS_DIR)
for _path in (_TOOLS_DIR, _REPO_ROOT):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tool_error_utils import TOOL_OPTIONAL_IMPORT_EXCEPTIONS, TOOL_RECOVERABLE_EXCEPTIONS

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
            "bl_ext.user_default.planetka",
            "Planetka",
            "planetka",
        ]
    )
    for mod in candidates:
        try:
            addon_utils.enable(mod)
            loaded, _loaded_default = addon_utils.check(mod)
            if not bool(loaded):
                continue
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
            f"bl_ext.user_default.planetka.{submodule_name}",
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
        if not coll.name.startswith("Planetka"):
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


def _make_texture_source_tree(base_dir):
    os.makedirs(base_dir, exist_ok=True)
    fallback = os.path.join(_addon_root(), "Resources", "Fallback Images")

    rules = (
        ("S2", "S2_", ".exr", "ocean_pixel_final_20.exr"),
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

    # Create Earth validation requires the PO folder to exist, even when no PO tiles are present.
    os.makedirs(os.path.join(base_dir, "PO"), exist_ok=True)


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
        _drain_queued_resolve(state, scene)
        status_after_create = dict(state.get_resolve_runtime_status(scene) or {})
        _assert(
            str(status_after_create.get("code", "") or "IDLE") == "IDLE",
            f"Queued Create Earth resolve did not return to IDLE: {status_after_create}",
        )

        result = bpy.ops.planetka.load_textures()
        _assert("FINISHED" in result, f"Resolve Earth failed with result: {result}")

        surface = bpy.data.objects.get("Planetka Earth Surface")
        _assert(surface is not None, "Planetka Earth Surface is missing after Resolve Earth.")
        if surface.parent is not None:
            parent_name = str(getattr(surface.parent, "name", "") or "")
            _assert(
                parent_name.startswith("Planetka"),
                f"Resolved Earth surface has unexpected non-Planetka parent: {parent_name}",
            )
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

        _log("3/4 Validate viewport subdivision and sunlight wiring")
        _assert(bool(subsurf.show_viewport), "Adaptive subdivision viewport display must always stay enabled.")
        sunlight = bpy.data.objects.get("Planetka Sunlight")
        _assert(sunlight is not None, "Planetka Sunlight is missing after Create Earth.")
        _assert(str(getattr(sunlight, "type", "")) == "LIGHT", "Planetka Sunlight object type must be LIGHT.")
        light_data = getattr(sunlight, "data", None)
        _assert(light_data is not None and str(getattr(light_data, "type", "")) == "SUN", "Planetka Sunlight data type must be SUN.")
        props = getattr(scene, "planetka", None)
        _assert(props is not None, "Planetka scene properties are unavailable for sunlight checks.")
        props.sunlight_strength = 14.0
        state.update_sunlight_strength(props, bpy.context)
        energy = float(getattr(light_data, "energy", 0.0) or 0.0)
        _assert(abs(energy - 14.0) <= 1e-4, f"Sunlight strength callback did not apply to light energy (got {energy}).")

        _log("PASS: simplified smoke checks passed.")
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
