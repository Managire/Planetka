"""
Planetka overnight stress test runner (personal-licence focused).

Flow:
1. Enable addon and verify existing logged-in account session.
2. Create Earth, set renderer (Cycles or EEVEE), set HD render output.
3. Run a long case set:
   - 500 random places from GeoNames database
   - Pole special locations (north/south at 30km and 3000km)
   - Capital-city sweep (from in-repo capitals pool), with altitude:
       > 3,000,000 population -> 60km
       <= 3,000,000 population -> 30km
4. For each case:
   - random heading/tilt/roll/focal length
   - random sunlight preset (10 presets)
   - resolve from camera scope
   - render HD PNG to /Volumes/SSDA/Renders
   - analyze output for pink/mostly-black issues
5. Write JSON report with all failures and per-case diagnostics.

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
    --python tools/planetka_overnight_stress_test.py

Optional env:
  PLANETKA_MODULE=<module-name>
  PLANETKA_RENDER_DIR=/Volumes/SSDA/Renders
  PLANETKA_STRESS_SEED=20260327
  PLANETKA_RANDOM_PLACE_COUNT=500
  PLANETKA_CAPITALS_MODE=all|none   (default: all)
  PLANETKA_RENDER_ENGINE=CYCLES|EEVEE   (default: CYCLES)
  PLANETKA_INCLUDE_POLES=1|0            (default: 1)
  PLANETKA_MAX_ALLOWED_TILES=12         (default: 12)
"""

import importlib
import json
import os
import random
import sqlite3
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


TAG = "[Planetka Overnight Stress]"
DEFAULT_RENDER_DIR = "/Volumes/SSDA/Renders"
DEFAULT_SEED = 20260327
DEFAULT_RANDOM_PLACE_COUNT = 500
DEFAULT_MAX_ALLOWED_TILES = 12

SUNLIGHT_PRESETS = (
    "DAWN",
    "DUSK",
    "SUNRISE",
    "SUNSET",
    "EARLY_MORNING",
    "LATE_AFTERNOON",
    "MID_MORNING",
    "MID_AFTERNOON",
    "NOON",
    "NIGHT",
)

NAV_PRESETS = ("MAX_PROXIMITY", "ISS_ORBIT", "GEOSYNCHRONOUS", "HIGH_ORBIT")

# Broad pool used by existing e2e script.
CAPITAL_QUERIES = [
    "Tokyo", "Seoul", "Beijing", "Bangkok", "Singapore", "Jakarta", "Kuala Lumpur", "Manila",
    "Hanoi", "Phnom Penh", "Vientiane", "Naypyidaw", "Kathmandu", "New Delhi", "Islamabad",
    "Dhaka", "Colombo", "Riyadh", "Abu Dhabi", "Doha", "Kuwait City", "Muscat", "Amman",
    "Jerusalem", "Ankara", "Athens", "Sofia", "Bucharest", "Belgrade", "Budapest", "Vienna",
    "Prague", "Warsaw", "Berlin", "Amsterdam", "Brussels", "Paris", "Madrid", "Lisbon",
    "Dublin", "London", "Oslo", "Stockholm", "Helsinki", "Copenhagen", "Reykjavik", "Bern",
    "Rome", "Zagreb", "Ljubljana", "Bratislava", "Vilnius", "Riga", "Tallinn", "Minsk",
    "Kyiv", "Moscow", "Tbilisi", "Yerevan", "Baku", "Cairo", "Algiers", "Tunis", "Tripoli",
    "Rabat", "Dakar", "Accra", "Lagos", "Abuja", "Nairobi", "Addis Ababa", "Kampala", "Kigali",
    "Dar es Salaam", "Dodoma", "Windhoek", "Gaborone", "Harare", "Lusaka", "Maputo", "Luanda",
    "Pretoria", "Cape Town", "Canberra", "Wellington", "Suva", "Port Moresby", "Ottawa",
    "Washington", "Mexico City", "Havana", "Santo Domingo", "San Jose", "Panama City", "Bogota",
    "Quito", "Lima", "Santiago", "Buenos Aires", "Montevideo", "Asuncion", "La Paz", "Brasilia",
]

COUNTRY_HINT_BY_CITY = {
    "Sofia": "BG",
    "Washington": "US",
    "London": "GB",
    "Vienna": "AT",
    "Bratislava": "SK",
    "Rome": "IT",
    "Cairo": "EG",
    "Accra": "GH",
    "Maputo": "MZ",
    "Pretoria": "ZA",
    "Cape Town": "ZA",
    "Canberra": "AU",
    "Ottawa": "CA",
    "Quito": "EC",
    "Santiago": "CL",
    "La Paz": "BO",
    "Hanoi": "VN",
    "Tbilisi": "GE",
    "Riyadh": "SA",
    "Baku": "AZ",
}


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


def _remove_existing_planetka_objects():
    for obj in list(bpy.data.objects):
        if obj.name.startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


def _remove_non_planetka_lights(scene):
    removed = []
    for obj in list(scene.objects):
        if str(getattr(obj, "type", "")) != "LIGHT":
            continue
        if str(getattr(obj, "name", "")).startswith("Planetka"):
            continue
        removed.append(str(obj.name))
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
    if removed:
        _log(f"Removed non-Planetka lights: {removed}")


def _ensure_active_camera(scene):
    current = getattr(scene, "camera", None)
    if current and getattr(current, "type", None) == "CAMERA":
        return current

    for obj in scene.objects:
        if obj.type == "CAMERA":
            scene.camera = obj
            return obj

    camera_data = bpy.data.cameras.new("Planetka Overnight Camera")
    camera_obj = bpy.data.objects.new("Planetka Overnight Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (1.5708, 0.0, 0.0)
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


def _wait_for_geonames_ready(geonames_module, timeout_sec=240.0):
    started = time.time()
    while True:
        geonames_module.load_geonames_database()
        status = str(geonames_module.get_search_status())
        if status == "ready":
            return True
        if status == "error":
            _fail(f"GeoNames index status=error: {geonames_module.get_search_status_text()}")
        if (time.time() - started) >= float(timeout_sec):
            _fail(f"GeoNames index did not reach ready state within {timeout_sec:.0f}s (status={status}).")
        time.sleep(0.5)


def _open_geonames_connection(geonames_module):
    db_path = str(getattr(geonames_module, "_INDEX_DB_PATH", "") or "").strip()
    if not db_path:
        _fail("GeoNames DB path is empty after ready state.")
    if not os.path.isfile(db_path):
        _fail(f"GeoNames DB path does not exist: {db_path}")
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    return connection, db_path


def _sample_random_places(connection, count, rng):
    cursor = connection.cursor()
    cursor.execute("SELECT MIN(geonameid), MAX(geonameid) FROM places")
    row = cursor.fetchone()
    if not row or row[0] is None or row[1] is None:
        _fail("GeoNames places table is empty.")
    min_id = int(row[0])
    max_id = int(row[1])

    sampled = []
    used_display = set()
    attempts = 0
    max_attempts = max(10000, int(count) * 40)

    while len(sampled) < int(count) and attempts < max_attempts:
        attempts += 1
        probe_id = rng.randint(min_id, max_id)
        cursor.execute(
            """
            SELECT geonameid, name, country_code
            FROM places
            WHERE geonameid >= ?
            ORDER BY geonameid ASC
            LIMIT 1
            """,
            (probe_id,),
        )
        candidate = cursor.fetchone()
        if not candidate:
            continue
        name = str(candidate[1] or "").strip()
        country = str(candidate[2] or "").strip().upper()
        if not name:
            continue
        display = f"{name}, {country}" if country else name
        if display in used_display:
            continue
        used_display.add(display)
        sampled.append(display)

    if len(sampled) < int(count):
        cursor.execute(
            """
            SELECT name, country_code
            FROM places
            ORDER BY population DESC
            LIMIT ?
            """,
            (int(count) * 3,),
        )
        for name, country in cursor.fetchall():
            if len(sampled) >= int(count):
                break
            name = str(name or "").strip()
            country = str(country or "").strip().upper()
            if not name:
                continue
            display = f"{name}, {country}" if country else name
            if display in used_display:
                continue
            used_display.add(display)
            sampled.append(display)

    return sampled[: int(count)]


def _pick_place_display(geonames_module, query_text, country_hint=None):
    options = geonames_module.search_places(query_text, max_results=20)
    if not options:
        return None
    hint = str(country_hint or "").strip().upper()
    if hint:
        for display_name, _place_id in options:
            normalized = str(display_name or "").strip().upper()
            if normalized.endswith(f", {hint}") or f", {hint}," in normalized:
                return str(display_name)
    lower_query = str(query_text).strip().lower()
    for display_name, _place_id in options:
        if str(display_name).strip().lower().startswith(lower_query):
            return str(display_name)
    return str(options[0][0])


def _apply_place_selection(props, geonames_module, state_module, place_display):
    props.nav_city_search = str(place_display)
    for _ in range(12):
        bpy.context.view_layer.update()
        selected_name = str(getattr(props, "nav_city_selected_name", "") or "").strip()
        if selected_name:
            return selected_name, None
        time.sleep(0.05)

    entry = geonames_module.get_place_by_display(place_display)
    if not isinstance(entry, dict):
        return "", "place_selection_failed"

    try:
        props.nav_longitude_deg = float(entry.get("longitude", 0.0))
        props.nav_latitude_deg = float(entry.get("latitude", 0.0))
        state_module.update_navigation_shot(props, bpy.context)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        return "", "place_fallback_nav_failed"
    return str(place_display), "fallback_direct_coords"


def _set_nav_values(props, state_module, altitude_km, azimuth_deg, tilt_deg, roll_deg, focal_mm):
    state_module.suspend_navigation_shot_updates()
    try:
        props.nav_altitude_km = float(altitude_km)
        props.nav_azimuth_deg = float(azimuth_deg)
        props.nav_tilt_deg = float(tilt_deg)
        props.nav_roll_deg = float(roll_deg)
        props.nav_focal_length_mm = float(focal_mm)
    finally:
        state_module.resume_navigation_shot_updates()
    state_module.update_navigation_shot(props, bpy.context)


def _camera_signature(camera):
    if camera is None:
        return None
    matrix = camera.matrix_world
    translation = matrix.translation
    quaternion = matrix.to_quaternion()
    lens = float(getattr(getattr(camera, "data", None), "lens", 0.0) or 0.0)
    return (
        round(float(translation.x), 8),
        round(float(translation.y), 8),
        round(float(translation.z), 8),
        round(float(quaternion.w), 8),
        round(float(quaternion.x), 8),
        round(float(quaternion.y), 8),
        round(float(quaternion.z), 8),
        round(float(lens), 6),
    )


def _wait_for_camera_update(scene, props, state_module, previous_signature, timeout_sec=2.0):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != "CAMERA":
        return previous_signature, False

    deadline = time.monotonic() + float(timeout_sec)
    while time.monotonic() < deadline:
        try:
            bpy.context.view_layer.update()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        current = _camera_signature(camera)
        if previous_signature is None:
            return current, True
        if current != previous_signature:
            return current, True
        # Force-apply shot again if still unchanged.
        try:
            bpy.ops.planetka.navigation_apply_shot()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        # Re-drive state update path too.
        try:
            state_module.update_navigation_shot(props, bpy.context)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        time.sleep(0.05)

    # Last read at timeout.
    return _camera_signature(camera), False


def _apply_sunlight_preset(preset_name):
    result = bpy.ops.planetka.sunlight_preset(preset=str(preset_name))
    return "FINISHED" in result


def _resolve_from_camera():
    result = bpy.ops.planetka.load_textures(scope_mode="CAMERA", skip_render_compatibility=True)
    return result


def _analyze_render_image(path):
    img = bpy.data.images.load(path, check_existing=False)
    try:
        width = int(img.size[0])
        height = int(img.size[1])
        pixel_count = max(1, width * height)
        sample_target = 30000
        step = max(1, pixel_count // sample_target)

        sampled = 0
        black_count = 0
        pink_count = 0
        lum_sum = 0.0
        max_lum = 0.0

        pixels = img.pixels
        for i in range(0, pixel_count, step):
            base = i * 4
            r = float(pixels[base])
            g = float(pixels[base + 1])
            b = float(pixels[base + 2])
            lum = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
            lum_sum += lum
            max_lum = max(max_lum, lum)
            if lum <= 0.01:
                black_count += 1
            if r >= 0.80 and b >= 0.80 and g <= 0.22 and abs(r - b) <= 0.20:
                pink_count += 1
            sampled += 1

        avg_lum = lum_sum / max(1, sampled)
        black_ratio = black_count / max(1, sampled)
        pink_ratio = pink_count / max(1, sampled)
        mostly_black = (avg_lum <= 0.02 and max_lum <= 0.08) or (black_ratio >= 0.995)
        pink_corrupt = pink_ratio >= 0.005
        return {
            "width": width,
            "height": height,
            "samples": sampled,
            "avg_luminance": round(avg_lum, 6),
            "max_luminance": round(max_lum, 6),
            "black_ratio": round(black_ratio, 6),
            "pink_ratio": round(pink_ratio, 6),
            "mostly_black": bool(mostly_black),
            "pink_corrupt": bool(pink_corrupt),
        }
    finally:
        try:
            bpy.data.images.remove(img)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass


def _run_case(
    case_index,
    case_kind,
    label,
    props,
    scene,
    rng,
    diagnostics_module,
    render_dir,
    render_prefix,
    state_module,
    geonames_module,
    max_allowed_tiles,
    fixed_altitude_km=None,
    direct_longitude_deg=None,
    direct_latitude_deg=None,
):
    started = time.perf_counter()
    warnings = []
    camera = getattr(scene, "camera", None)
    camera_before = _camera_signature(camera)

    if direct_longitude_deg is not None and direct_latitude_deg is not None:
        try:
            props.nav_longitude_deg = float(direct_longitude_deg)
            props.nav_latitude_deg = float(direct_latitude_deg)
            state_module.update_navigation_shot(props, bpy.context)
            selected_name = str(label)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            return {
                "case": int(case_index),
                "kind": str(case_kind),
                "label": str(label),
                "ok": False,
                "error": "direct_coordinate_apply_failed",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
    else:
        selected_name, select_warning = _apply_place_selection(props, geonames_module, state_module, label)
        if not selected_name:
            return {
                "case": int(case_index),
                "kind": str(case_kind),
                "label": str(label),
                "ok": False,
                "error": "place_selection_failed",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
        if select_warning:
            warnings.append(str(select_warning))

    altitude_km = float(fixed_altitude_km if fixed_altitude_km is not None else rng.uniform(30.0, 3000.0))
    azimuth = float(rng.uniform(0.0, 360.0))
    tilt = float(rng.uniform(-75.0, 75.0))
    roll = float(rng.uniform(-45.0, 45.0))
    focal = float(rng.uniform(30.0, 70.0))
    _set_nav_values(props, state_module, altitude_km, azimuth, tilt, roll, focal)
    camera_after_nav, camera_updated = _wait_for_camera_update(
        scene, props, state_module, previous_signature=camera_before, timeout_sec=2.0
    )
    if not camera_updated:
        # One deterministic nudge/retry to avoid stale transform reuse.
        azimuth = (azimuth + 0.37) % 360.0
        _set_nav_values(props, state_module, altitude_km, azimuth, tilt, roll, focal)
        camera_after_nav, camera_updated = _wait_for_camera_update(
            scene, props, state_module, previous_signature=camera_before, timeout_sec=2.0
        )
        if not camera_updated:
            return {
                "case": int(case_index),
                "kind": str(case_kind),
                "label": str(label),
                "selected_place": str(selected_name),
                "ok": False,
                "error": "camera_update_timeout",
                "altitude_km": round(altitude_km, 3),
                "azimuth_deg": round(azimuth, 3),
                "tilt_deg": round(tilt, 3),
                "roll_deg": round(roll, 3),
                "focal_mm": round(focal, 3),
                "warnings": warnings,
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }

    if case_index % 40 == 0:
        nav_result = bpy.ops.planetka.navigation_preset(preset=str(rng.choice(NAV_PRESETS)))
        if "FINISHED" not in nav_result:
            warnings.append("navigation_preset_failed")
        _set_nav_values(props, state_module, altitude_km, azimuth, tilt, roll, focal)
        camera_after_nav, camera_updated = _wait_for_camera_update(
            scene, props, state_module, previous_signature=camera_after_nav, timeout_sec=2.0
        )
        if not camera_updated:
            warnings.append("camera_update_slow_after_nav_preset")

    sunlight = str(rng.choice(SUNLIGHT_PRESETS))
    if not _apply_sunlight_preset(sunlight):
        warnings.append("sunlight_preset_failed")

    resolve_result = _resolve_from_camera()
    if "FINISHED" not in resolve_result:
        return {
            "case": int(case_index),
            "kind": str(case_kind),
            "label": str(label),
            "selected_place": str(selected_name),
            "ok": False,
            "error": f"resolve_failed_{resolve_result}",
            "altitude_km": round(altitude_km, 3),
            "azimuth_deg": round(azimuth, 3),
            "tilt_deg": round(tilt, 3),
            "roll_deg": round(roll, 3),
            "focal_mm": round(focal, 3),
            "sunlight_preset": sunlight,
            "warnings": warnings,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }

    render_path = os.path.join(render_dir, f"{render_prefix}_{int(case_index):04d}.png")
    scene.render.filepath = render_path
    bpy.ops.render.render(write_still=True)
    analysis = _analyze_render_image(render_path)

    diag = diagnostics_module.read_diagnostics(scene)
    try:
        resolved_tile_count = int(diag.get("last_tile_count", 0) or 0)
    except (TypeError, ValueError):
        resolved_tile_count = 0
    if int(resolved_tile_count) > int(max_allowed_tiles):
        return {
            "case": int(case_index),
            "kind": str(case_kind),
            "label": str(label),
            "selected_place": str(selected_name),
            "ok": False,
            "error": "tile_budget_exceeded",
            "resolve_tile_count": int(resolved_tile_count),
            "max_allowed_tiles": int(max_allowed_tiles),
            "warnings": warnings,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
    ok = (not analysis.get("mostly_black")) and (not analysis.get("pink_corrupt"))
    case_payload = {
        "case": int(case_index),
        "kind": str(case_kind),
        "label": str(label),
        "selected_place": str(selected_name),
        "ok": bool(ok),
        "altitude_km": round(altitude_km, 3),
        "azimuth_deg": round(azimuth, 3),
        "tilt_deg": round(tilt, 3),
        "roll_deg": round(roll, 3),
        "focal_mm": round(focal, 3),
        "sunlight_preset": sunlight,
        "camera_signature_before": camera_before,
        "camera_signature_after_nav": camera_after_nav,
        "render_path": render_path,
        "resolve_tile_count": int(resolved_tile_count),
        "resolve_downloaded_mb": diag.get("resolve_downloaded_mb"),
        "resolve_download_ms": diag.get("resolve_download_ms"),
        "resolve_stage": diag.get("resolve_stage"),
        "image_analysis": analysis,
        "warnings": warnings,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }
    if not ok:
        case_payload["error"] = "render_validation_failed"
    return case_payload


def main():
    started_at = time.time()
    render_dir = str(os.environ.get("PLANETKA_RENDER_DIR") or DEFAULT_RENDER_DIR).strip()
    run_seed = int(os.environ.get("PLANETKA_STRESS_SEED") or str(DEFAULT_SEED))
    random_place_count = max(1, int(os.environ.get("PLANETKA_RANDOM_PLACE_COUNT") or str(DEFAULT_RANDOM_PLACE_COUNT)))
    capitals_mode = str(os.environ.get("PLANETKA_CAPITALS_MODE") or "all").strip().lower()
    render_engine_mode = str(os.environ.get("PLANETKA_RENDER_ENGINE") or "CYCLES").strip().upper()
    include_poles = str(os.environ.get("PLANETKA_INCLUDE_POLES") or "1").strip().lower() not in {"0", "false", "no"}
    max_allowed_tiles = max(
        1,
        int(os.environ.get("PLANETKA_MAX_ALLOWED_TILES") or str(DEFAULT_MAX_ALLOWED_TILES)),
    )

    os.makedirs(render_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(render_dir, f"planetka_overnight_stress_report_{ts}.json")
    render_prefix = f"planetka_overnight_{ts}"

    rng = random.Random(run_seed)
    connection = None
    db_path = ""

    try:
        base_module_name = _enable_module()
        _assert(base_module_name is not None, "Could not enable Planetka extension module.")

        auth_module = _import_submodule(base_module_name, "auth")
        extension_prefs = _import_submodule(base_module_name, "extension_prefs")
        geonames_module = _import_submodule(base_module_name, "geonames_db")
        diagnostics_module = _import_submodule(base_module_name, "diagnostics")
        state_module = _import_submodule(base_module_name, "state")
        tile_utils_module = _import_submodule(base_module_name, "tile_utils")

        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")
        _assert(auth_module.is_authenticated(prefs), "Account not logged in. Log in before running overnight stress test.")
        auth_module.sync_account_profile(prefs)

        user_email = str(auth_module.get_connected_email(prefs) or "").strip().lower()
        plan_code = str(getattr(prefs, "auth_plan_code", "") or "").strip().lower()
        _log(f"Authenticated account: email={user_email or 'unknown'} plan={plan_code or 'unknown'}")

        scene = bpy.context.scene
        _ensure_active_camera(scene)
        _remove_existing_planetka_objects()
        _remove_non_planetka_lights(scene)

        prefs.texture_base_path = "planetka-remote"
        props = scene.planetka
        props.auto_resolve = False
        props.texture_quality_mode = "PREVIEW"
        props.show_earth_preview = False

        scene.render.resolution_x = 1920
        scene.render.resolution_y = 1080
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.film_transparent = False
        scene.render.use_simplify = True
        if render_engine_mode == "CYCLES":
            scene.cycles.samples = 24
            scene.cycles.preview_samples = 8
            scene.cycles.use_denoising = False
            scene.cycles.use_adaptive_sampling = True

        if tile_utils_module is not None:
            try:
                tile_utils_module.MAX_SHADER_TILE_BUDGET = int(max_allowed_tiles)
                _log(f"Tile budget cap forced to {int(max_allowed_tiles)}")
            except TOOL_RECOVERABLE_EXCEPTIONS:
                _log("WARN: failed to set tile budget cap in tile_utils module")

        create_result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in create_result, f"Create Earth failed: {create_result}")
        gpu_info = {}
        if render_engine_mode == "CYCLES":
            scene.render.engine = "CYCLES"
            _assert(str(scene.render.engine) == "CYCLES", f"Render engine is not CYCLES: {scene.render.engine}")
            gpu_info = _configure_cycles_gpu(scene)
            _assert(bool(gpu_info.get("gpu_enabled")), "Cycles GPU is not available/enabled.")
            _assert(str(gpu_info.get("scene_cycles_device")) == "GPU", "Cycles scene device is not GPU.")
            _log(f"Cycles GPU enabled: backend={gpu_info.get('backend')} devices={gpu_info.get('devices')}")
        elif render_engine_mode in {"EEVEE", "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"}:
            target = "BLENDER_EEVEE_NEXT"
            try:
                enum_items = scene.render.bl_rna.properties["engine"].enum_items.keys()
                if target not in enum_items:
                    target = "BLENDER_EEVEE"
            except TOOL_RECOVERABLE_EXCEPTIONS:
                target = "BLENDER_EEVEE"
            scene.render.engine = target
            _assert("EEVEE" in str(scene.render.engine), f"Render engine is not EEVEE: {scene.render.engine}")
            _log(f"EEVEE enabled: engine={scene.render.engine}")
        else:
            _fail(f"Unsupported PLANETKA_RENDER_ENGINE={render_engine_mode}. Use CYCLES or EEVEE.")

        _wait_for_geonames_ready(geonames_module)
        connection, db_path = _open_geonames_connection(geonames_module)
        random_places = _sample_random_places(connection, random_place_count, rng)
        _assert(len(random_places) > 0, "No random places could be sampled.")

        pole_cases = []
        if include_poles:
            pole_cases = [
                ("North Pole, 3000km", 0.0, 89.95, 3000.0),
                ("North Pole, 30km", 0.0, 89.95, 30.0),
                ("South Pole, 3000km", 0.0, -89.95, 3000.0),
                ("South Pole, 30km", 0.0, -89.95, 30.0),
            ]

        capital_cases = []
        if capitals_mode != "none":
            for city in CAPITAL_QUERIES:
                hint = COUNTRY_HINT_BY_CITY.get(city)
                display = _pick_place_display(geonames_module, city, country_hint=hint)
                if not display:
                    capital_cases.append({"query": city, "display": "", "population": 0, "altitude_km": 30.0, "lookup_error": "no_search_result"})
                    continue
                entry = geonames_module.get_place_by_display(display) or {}
                population = int(entry.get("population", 0) or 0)
                altitude_km = 60.0 if population > 3000000 else 30.0
                capital_cases.append(
                    {
                        "query": city,
                        "display": str(display),
                        "population": int(population),
                        "altitude_km": float(altitude_km),
                        "lookup_error": "",
                    }
                )

        failures = []
        cases = []
        case_index = 0

        _log(
            "Run plan: "
            f"random_places={len(random_places)}, poles={len(pole_cases)}, capitals={len(capital_cases)}"
        )

        for place_display in random_places:
            case_index += 1
            case_payload = _run_case(
                case_index=case_index,
                case_kind="random_place",
                label=place_display,
                props=props,
                scene=scene,
                rng=rng,
                diagnostics_module=diagnostics_module,
                render_dir=render_dir,
                render_prefix=render_prefix,
                state_module=state_module,
                geonames_module=geonames_module,
                max_allowed_tiles=max_allowed_tiles,
                fixed_altitude_km=None,
            )
            cases.append(case_payload)
            if not case_payload.get("ok"):
                failures.append(f"Case {case_index:04d} random_place {place_display}: {case_payload.get('error')}")
            _log(
                f"Case {case_index:04d}: kind=random_place ok={case_payload.get('ok')} "
                f"label={place_display}"
            )

        for pole_label, pole_lon, pole_lat, pole_altitude in pole_cases:
            case_index += 1
            case_payload = _run_case(
                case_index=case_index,
                case_kind="pole_special",
                label=pole_label,
                props=props,
                scene=scene,
                rng=rng,
                diagnostics_module=diagnostics_module,
                render_dir=render_dir,
                render_prefix=render_prefix,
                state_module=state_module,
                geonames_module=geonames_module,
                max_allowed_tiles=max_allowed_tiles,
                fixed_altitude_km=pole_altitude,
                direct_longitude_deg=pole_lon,
                direct_latitude_deg=pole_lat,
            )
            case_payload["pole_label"] = pole_label
            cases.append(case_payload)
            if not case_payload.get("ok"):
                failures.append(f"Case {case_index:04d} pole {pole_label}: {case_payload.get('error')}")
            _log(
                f"Case {case_index:04d}: kind=pole_special ok={case_payload.get('ok')} "
                f"label={pole_label}"
            )

        for cap in capital_cases:
            case_index += 1
            if cap.get("lookup_error"):
                case_payload = {
                    "case": int(case_index),
                    "kind": "capital_city",
                    "label": str(cap.get("query")),
                    "selected_place": "",
                    "ok": False,
                    "error": str(cap.get("lookup_error")),
                    "population": int(cap.get("population", 0)),
                    "altitude_km": float(cap.get("altitude_km", 30.0)),
                }
            else:
                case_payload = _run_case(
                    case_index=case_index,
                    case_kind="capital_city",
                    label=str(cap.get("display")),
                    props=props,
                    scene=scene,
                    rng=rng,
                    diagnostics_module=diagnostics_module,
                    render_dir=render_dir,
                    render_prefix=render_prefix,
                    state_module=state_module,
                    geonames_module=geonames_module,
                    max_allowed_tiles=max_allowed_tiles,
                    fixed_altitude_km=float(cap.get("altitude_km", 30.0)),
                )
                case_payload["capital_query"] = str(cap.get("query"))
                case_payload["population"] = int(cap.get("population", 0))
                case_payload["altitude_rule_km"] = float(cap.get("altitude_km", 30.0))

            cases.append(case_payload)
            if not case_payload.get("ok"):
                failures.append(
                    f"Case {case_index:04d} capital {cap.get('query')}: {case_payload.get('error')}"
                )
            _log(
                f"Case {case_index:04d}: kind=capital_city ok={case_payload.get('ok')} "
                f"query={cap.get('query')}"
            )

        report = {
            "ok": len(failures) == 0,
            "seed": int(run_seed),
            "account_email": user_email,
            "licence_code": plan_code,
            "render_dir": render_dir,
            "report_path": report_path,
            "geonames_index_db_path": db_path,
            "gpu_info": gpu_info,
            "render_engine_mode": render_engine_mode,
            "include_poles": bool(include_poles),
            "max_allowed_tiles": int(max_allowed_tiles),
            "counts": {
                "random_places_requested": int(random_place_count),
                "random_places_completed": len(random_places),
                "pole_cases": len(pole_cases),
                "capital_cases": len(capital_cases),
                "total_cases": len(cases),
                "total_failures": len(failures),
            },
            "failures": failures,
            "elapsed_sec": round(time.time() - started_at, 3),
            "cases": cases,
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=True)

        _log(f"Completed. total_cases={len(cases)} failures={len(failures)}")
        _log(f"Report: {report_path}")
        if failures:
            raise SystemExit(2)
    except SystemExit:
        raise
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        _log(f"Unhandled error: {exc}")
        traceback.print_exc()
        raise SystemExit(1)
    finally:
        if connection is not None:
            try:
                connection.close()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


if __name__ == "__main__":
    main()
