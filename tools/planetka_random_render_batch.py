"""
Planetka end-to-end random resolve/render batch.

Runs 10 random navigation shots, resolves textures from Cloud, renders PNGs,
and records resolve/render diagnostics per shot.

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
    --python tools/planetka_random_render_batch.py

Required env:
  PLANETKA_AUTH_PAYLOAD=/absolute/path/to/auth_verify_payload.json

Optional env:
  PLANETKA_MODULE=<module-name>
  PLANETKA_RANDOM_COUNT=10
  PLANETKA_RANDOM_SEED=20260323
  PLANETKA_RENDER_DIR=/Volumes/SSDA/Renders
"""

import importlib
import json
import math
import os
import random
import sys
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
from mathutils import Matrix, Quaternion, Vector


TAG = "[Planetka Random Batch]"
DEFAULT_RENDER_DIR = "/Volumes/SSDA/Renders"


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


def _ensure_active_camera(scene):
    current = getattr(scene, "camera", None)
    if current and getattr(current, "type", None) == "CAMERA":
        return current

    for obj in scene.objects:
        if obj.type == "CAMERA":
            scene.camera = obj
            return obj

    camera_data = bpy.data.cameras.new("Planetka Batch Camera")
    camera_obj = bpy.data.objects.new("Planetka Batch Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def _configure_cycles_gpu(scene):
    backend_selected = ""
    gpu_enabled = False
    gpu_devices = []

    try:
        prefs = bpy.context.preferences
        cycles_addon = prefs.addons.get("cycles")
        if cycles_addon and hasattr(cycles_addon, "preferences"):
            cprefs = cycles_addon.preferences
            for backend in ("METAL", "CUDA", "OPTIX", "HIP", "ONEAPI"):
                try:
                    cprefs.compute_device_type = backend
                    cprefs.get_devices()
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    continue
                devices = list(getattr(cprefs, "devices", []))
                non_cpu = [d for d in devices if str(getattr(d, "type", "")).upper() != "CPU"]
                if non_cpu:
                    for device in devices:
                        try:
                            device.use = True
                        except TOOL_RECOVERABLE_EXCEPTIONS:
                            pass
                    backend_selected = backend
                    gpu_enabled = True
                    gpu_devices = [str(getattr(d, "name", "GPU")) for d in non_cpu]
                    break
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass

    try:
        scene.cycles.device = "GPU" if gpu_enabled else "CPU"
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass

    return {
        "gpu_enabled": bool(gpu_enabled),
        "backend": backend_selected,
        "devices": gpu_devices,
        "scene_cycles_device": str(getattr(scene.cycles, "device", "")),
    }


def _load_auth_payload(path):
    if not path:
        _fail("PLANETKA_AUTH_PAYLOAD is missing.")
    if not os.path.isfile(path):
        _fail(f"Auth payload file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not payload.get("access_token") or not payload.get("refresh_token"):
        _fail("Auth payload is invalid (missing access_token/refresh_token).")
    return payload


def _set_navigation(props, state_module, lon, lat, alt, azimuth, tilt, roll):
    state_module.suspend_navigation_shot_updates()
    try:
        props.nav_longitude_deg = float(lon)
        props.nav_latitude_deg = float(lat)
        props.nav_altitude_km = float(alt)
        props.nav_azimuth_deg = float(azimuth)
        props.nav_tilt_deg = float(tilt)
        props.nav_roll_deg = float(roll)
    finally:
        state_module.resume_navigation_shot_updates()


def _earth_radius_bu(earth_obj):
    try:
        stored = float(earth_obj.get("planetka_surface_local_radius", 0.0))
    except TOOL_RECOVERABLE_EXCEPTIONS:
        stored = 0.0
    if stored > 1e-9:
        try:
            max_scale = max(abs(float(v)) for v in earth_obj.scale)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            max_scale = 1.0
        return float(stored) * float(max_scale)
    try:
        values = [Vector(corner).length for corner in earth_obj.bound_box]
        if values:
            return max(values)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    return 1.0


def _set_camera_direct(scene, camera, earth_obj, lon_deg, lat_deg, altitude_km, azimuth_deg, tilt_deg, roll_deg):
    lon = math.radians(float(lon_deg))
    lat = math.radians(float(lat_deg))
    az = math.radians(float(azimuth_deg))
    tilt = math.radians(float(tilt_deg))
    roll = math.radians(float(roll_deg))

    center = earth_obj.matrix_world.translation.copy()
    radius = max(1e-6, float(_earth_radius_bu(earth_obj)))
    altitude_bu = (max(0.0, float(altitude_km)) / 6371.0) * radius

    normal = Vector((
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    ))
    if normal.length_squared <= 1e-12:
        normal = Vector((0.0, 0.0, 1.0))
    normal.normalize()

    world_up = Vector((0.0, 0.0, 1.0))
    east = world_up.cross(normal)
    if east.length_squared <= 1e-12:
        east = Vector((0.0, 1.0, 0.0))
    east.normalize()
    north = normal.cross(east)
    if north.length_squared <= 1e-12:
        north = Vector((1.0, 0.0, 0.0))
    north.normalize()

    tangent = (north * math.cos(az)) + (east * math.sin(az))
    if tangent.length_squared <= 1e-12:
        tangent = north
    tangent.normalize()

    cam_pos = center + normal * (radius + altitude_bu)
    look_dir = ((-normal) * math.cos(tilt)) + (tangent * math.sin(tilt))
    if look_dir.length_squared <= 1e-12:
        look_dir = -normal
    look_dir.normalize()

    rotation = look_dir.to_track_quat("-Z", "Y")
    if abs(roll) > 1e-9:
        rotation = Quaternion(look_dir, roll) @ rotation

    location, _rot, scale = camera.matrix_world.decompose()
    del location
    camera.matrix_world = Matrix.LocRotScale(cam_pos, rotation, scale)


def _bytes_to_mb(value):
    return float(value) / (1024.0 * 1024.0)


def _remove_existing_planetka_objects():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


def main():
    started_at = time.time()
    render_dir = str(os.environ.get("PLANETKA_RENDER_DIR") or DEFAULT_RENDER_DIR).strip()
    random_count = max(1, int(os.environ.get("PLANETKA_RANDOM_COUNT") or "10"))
    random_seed = int(os.environ.get("PLANETKA_RANDOM_SEED") or "20260323")
    auth_payload_path = str(os.environ.get("PLANETKA_AUTH_PAYLOAD") or "").strip()

    os.makedirs(render_dir, exist_ok=True)
    report_path = os.path.join(
        render_dir,
        f"planetka_random_batch_report_{time.strftime('%Y%m%d_%H%M%S')}.json",
    )
    render_prefix = f"planetka_random_{time.strftime('%Y%m%d_%H%M%S')}"

    rng = random.Random(random_seed)

    try:
        base_module_name = _enable_module()
        _assert(base_module_name is not None, "Could not enable Planetka extension module.")

        auth_module = _import_submodule(base_module_name, "auth")
        extension_prefs = _import_submodule(base_module_name, "extension_prefs")
        diagnostics = _import_submodule(base_module_name, "diagnostics")
        state_module = _import_submodule(base_module_name, "state")

        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")

        auth_payload = _load_auth_payload(auth_payload_path)
        auth_module._apply_auth_payload(prefs, auth_payload, login_state="authenticated")  # noqa: SLF001
        _assert(auth_module.is_authenticated(prefs), "Planetka account is not authenticated after payload apply.")
        auth_module.sync_account_profile(prefs)

        scene = bpy.context.scene
        camera = _ensure_active_camera(scene)
        _remove_existing_planetka_objects()

        prefs.texture_base_path = "planetka-remote"
        props = scene.planetka
        props.auto_resolve = False
        props.texture_quality_mode = "FULL"
        props.show_earth_preview = False
        scene.render.engine = "CYCLES"

        scene.render.resolution_x = 1920
        scene.render.resolution_y = 1080
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.film_transparent = False

        gpu_info = _configure_cycles_gpu(scene)
        _log(f"Cycles device: {gpu_info.get('scene_cycles_device')} backend={gpu_info.get('backend')} devices={gpu_info.get('devices')}")

        create_result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in create_result, f"Create Earth failed: {create_result}")
        _assert(extension_prefs.get_earth_object() is not None, "Planetka Earth object is missing after Create Earth.")

        results = []

        altitude_options_km = [5, 12, 20, 40, 80, 150, 300, 600, 1200, 2500]
        for index in range(1, random_count + 1):
            lon = rng.uniform(-180.0, 180.0)
            lat = rng.uniform(-80.0, 80.0)
            alt = float(rng.choice(altitude_options_km))
            azimuth = rng.uniform(0.0, 360.0)
            tilt = rng.uniform(8.0, 82.0)
            roll = rng.uniform(-22.0, 22.0)

            earth_obj = extension_prefs.get_earth_object()
            _assert(earth_obj is not None, f"Planetka Earth object missing before case {index}.")
            _set_navigation(props, state_module, lon, lat, alt, azimuth, tilt, roll)
            _set_camera_direct(scene, camera, earth_obj, lon, lat, alt, azimuth, tilt, roll)

            resolve_result = bpy.ops.planetka.load_textures(scope_mode="CAMERA", skip_render_compatibility=True)
            _assert("FINISHED" in resolve_result, f"Resolve failed at case {index}: {resolve_result}")

            render_path = os.path.join(render_dir, f"{render_prefix}_{index:02d}.png")
            scene.render.filepath = render_path
            render_start = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            render_ms = (time.perf_counter() - render_start) * 1000.0

            diag = diagnostics.read_diagnostics(scene)
            case_payload = {
                "case": index,
                "longitude_deg": round(lon, 6),
                "latitude_deg": round(lat, 6),
                "altitude_km": round(alt, 3),
                "azimuth_deg": round(azimuth, 3),
                "tilt_deg": round(tilt, 3),
                "roll_deg": round(roll, 3),
                "render_path": render_path,
                "render_ms": round(render_ms, 3),
                "resolve_downloaded_mb_local": diag.get("resolve_downloaded_mb"),
                "resolve_download_ms_local": diag.get("resolve_download_ms"),
                "resolve_tile_count": diag.get("last_tile_count"),
                "resolve_textures_mb": diag.get("resolve_textures_mb"),
                "camera_location": [round(float(v), 6) for v in camera.matrix_world.translation],
                "camera_rotation_euler_deg": [
                    round(math.degrees(float(v)), 6) for v in camera.matrix_world.to_euler()
                ],
            }
            results.append(case_payload)
            _log(
                f"Case {index:02d}: download={float(case_payload.get('resolve_downloaded_mb_local') or 0.0):.3f} MB, "
                f"tiles={case_payload.get('resolve_tile_count')}, render={render_path}"
            )

        report = {
            "ok": True,
            "seed": random_seed,
            "count": random_count,
            "render_dir": render_dir,
            "gpu_info": gpu_info,
            "elapsed_sec": round(time.time() - started_at, 3),
            "cases": results,
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=True)

        _log(f"Batch completed: {random_count} renders")
        _log(f"Report: {report_path}")
    except SystemExit:
        raise
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        _log(f"Unhandled error: {exc}")
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
