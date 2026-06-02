"""
Planetka resolve soak test (no rendering).

Runs repeated real resolves from randomized navigation shots and verifies:
1) Resolve completes.
2) Earth surface/material are present.
3) Active tile image nodes have assigned images on disk (fallbacks allowed).

Usage:
  /Applications/Blender.app/Contents/MacOS/Blender --background \
    --python tools/planetka_resolve_soak_test.py

Optional env:
  PLANETKA_MODULE=<module-name>
  PLANETKA_SOAK_CASES=1000
  PLANETKA_SOAK_SEED=20260328
  PLANETKA_SOAK_REPORT_DIR=/Volumes/SSDA/Renders
    PLANETKA_DEVICE_ID=<device-id>        # optional: force stable device id for this run
  PLANETKA_EXPECTED_EMAIL=tom.griger@gmail.com
  PLANETKA_SOAK_RENDER=1                # render PNG after each resolve
  PLANETKA_SOAK_RENDER_MODE=dual        # dual|cycles|eevee
  PLANETKA_SOAK_RENDER_PREFIX=planetka_soak_render
  PLANETKA_SOAK_RENDER_NOISE_THRESHOLD=0.05
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


TAG = "[Planetka Resolve Soak]"
DEFAULT_CASES = 1000
DEFAULT_SEED = 20260328
DEFAULT_REPORT_DIR = "/Volumes/SSDA/Renders"
EXPECTED_ADMIN_EMAIL = "tom.griger@gmail.com"

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

CAPITAL_QUERIES = (
    "Tokyo", "Seoul", "Beijing", "Bangkok", "Singapore", "Jakarta", "Kuala Lumpur", "Manila",
    "Hanoi", "New Delhi", "Islamabad", "Dhaka", "Riyadh", "Abu Dhabi", "Doha", "Ankara",
    "Athens", "Sofia", "Bucharest", "Belgrade", "Budapest", "Vienna", "Prague", "Warsaw",
    "Berlin", "Amsterdam", "Brussels", "Paris", "Madrid", "Lisbon", "Dublin", "London",
    "Oslo", "Stockholm", "Helsinki", "Copenhagen", "Reykjavik", "Bern", "Rome", "Zagreb",
    "Bratislava", "Vilnius", "Riga", "Tallinn", "Kyiv", "Moscow", "Tbilisi", "Yerevan",
    "Baku", "Cairo", "Algiers", "Tunis", "Rabat", "Dakar", "Accra", "Lagos", "Abuja",
    "Nairobi", "Addis Ababa", "Kampala", "Dar es Salaam", "Luanda", "Pretoria", "Cape Town",
    "Canberra", "Wellington", "Ottawa", "Washington", "Mexico City", "Havana", "San Jose",
    "Panama City", "Bogota", "Quito", "Lima", "Santiago", "Buenos Aires", "Montevideo",
    "Asuncion", "La Paz", "Brasilia",
)

POLE_CASES = (
    ("North Pole", 0.0, 89.95),
    ("South Pole", 0.0, -89.95),
)


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
    camera_data = bpy.data.cameras.new("Planetka Soak Camera")
    camera_obj = bpy.data.objects.new("Planetka Soak Camera", camera_data)
    scene.collection.objects.link(camera_obj)
    camera_obj.location = (0.0, -8.0, 0.0)
    camera_obj.rotation_euler = (1.5708, 0.0, 0.0)
    scene.camera = camera_obj
    return camera_obj


def _remove_existing_planetka_objects():
    for obj in list(bpy.data.objects):
        if str(obj.name).startswith("Planetka"):
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


def _remove_non_planetka_lights(scene):
    for obj in list(scene.objects):
        if str(getattr(obj, "type", "")) != "LIGHT":
            continue
        if str(getattr(obj, "name", "")).startswith("Planetka"):
            continue
        try:
            bpy.data.objects.remove(obj, do_unlink=True)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass


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


def _configure_render_output(scene, noise_threshold=0.05):
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    try:
        scene.cycles.use_adaptive_sampling = True
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    try:
        scene.cycles.adaptive_threshold = float(noise_threshold)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    try:
        scene.cycles.noise_threshold = float(noise_threshold)
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass


def _eevee_engine_id():
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            bpy.context.scene.render.engine = candidate
            return candidate
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
    return ""


def _render_case(scene, render_dir, render_prefix, case_index, render_mode="dual"):
    rendered = []
    cycles_engine = "CYCLES"
    eevee_engine = _eevee_engine_id()
    mode = str(render_mode or "dual").strip().lower()
    # Always switch back to Cycles for the next resolve loop.
    try:
        scene.render.engine = cycles_engine
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    if mode == "cycles":
        targets = ((cycles_engine, "cycles"),)
    elif mode == "eevee":
        targets = ((eevee_engine, "eevee"),)
    else:
        targets = ((cycles_engine, "cycles"), (eevee_engine, "eevee"))
    for engine_id, suffix in targets:
        if not engine_id:
            continue
        try:
            scene.render.engine = engine_id
        except TOOL_RECOVERABLE_EXCEPTIONS:
            continue
        render_path = os.path.join(str(render_dir), f"{render_prefix}_{int(case_index):04d}_{suffix}.png")
        scene.render.filepath = render_path
        render_started = time.perf_counter()
        bpy.ops.render.render(write_still=True)
        render_ms = (time.perf_counter() - render_started) * 1000.0
        rendered.append(
            {
                "engine": engine_id,
                "path": render_path,
                "render_ms": round(render_ms, 3),
            }
        )
    try:
        scene.render.engine = cycles_engine
    except TOOL_RECOVERABLE_EXCEPTIONS:
        pass
    return rendered


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
            _fail(f"GeoNames index not ready within {timeout_sec:.0f}s (status={status}).")
        time.sleep(0.5)


def _open_geonames_connection(geonames_module):
    db_path = str(getattr(geonames_module, "_INDEX_DB_PATH", "") or "").strip()
    if not db_path or not os.path.isfile(db_path):
        _fail(f"GeoNames DB path missing: {db_path}")
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
    used = set()
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
        if display in used:
            continue
        used.add(display)
        sampled.append(display)
    return sampled[: int(count)]


def _pick_place_display(geonames_module, query_text):
    options = geonames_module.search_places(query_text, max_results=20)
    if not options:
        return None
    lower_query = str(query_text).strip().lower()
    for display_name, _place_id in options:
        if str(display_name).strip().lower().startswith(lower_query):
            return str(display_name)
    return str(options[0][0])


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
        try:
            bpy.ops.planetka.navigation_apply_shot()
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        try:
            state_module.update_navigation_shot(props, bpy.context)
        except TOOL_RECOVERABLE_EXCEPTIONS:
            pass
        time.sleep(0.05)
    return _camera_signature(camera), False


def _active_loading_tile_nodes(material_name="Planetka Earth Material"):
    material = bpy.data.materials.get(str(material_name))
    if material is None or getattr(material, "node_tree", None) is None:
        return []
    nodes = material.node_tree.nodes
    loading_group_node = nodes.get("Planetka Textures Loading")
    loading_group = getattr(loading_group_node, "node_tree", None) if loading_group_node else None
    if loading_group is None:
        return []
    out = []
    for node in loading_group.nodes:
        if str(getattr(node, "type", "")) != "GROUP":
            continue
        node_name = str(getattr(node, "name", "") or "")
        if not node_name.startswith(("Tile_", "Planetka Tile_")):
            continue
        if bool(getattr(node, "mute", False)):
            continue
        out.append(node)
    return out


def _validate_resolve_integrity(render_prep_module):
    errors = []
    earth = bpy.data.objects.get("Planetka Earth Surface")
    if earth is None or str(getattr(earth, "type", "")) != "MESH":
        errors.append("earth_surface_missing")
    material = bpy.data.materials.get("Planetka Earth Material")
    if material is None:
        errors.append("earth_material_missing")
    elif earth is not None and getattr(earth.data, "materials", None):
        assigned = [str(getattr(m, "name", "")) for m in earth.data.materials if m is not None]
        if "Planetka Earth Material" not in assigned:
            errors.append("earth_material_not_assigned")

    missing_count = int(render_prep_module._count_missing_tile_loading_images("Planetka Earth Material"))
    if missing_count > 0:
        errors.append(f"missing_tile_node_images:{missing_count}")

    active_groups = _active_loading_tile_nodes("Planetka Earth Material")
    if not active_groups:
        errors.append("no_active_tile_groups")
    material = bpy.data.materials.get("Planetka Earth Material")
    group_nodes = None
    testing_mode = False
    if material is not None and getattr(material, "node_tree", None) is not None:
        nodes = getattr(material.node_tree, "nodes", None)
        loading_group_node = nodes.get("Planetka Textures Loading") if nodes else None
        loading_group = getattr(loading_group_node, "node_tree", None) if loading_group_node else None
        group_nodes = getattr(loading_group, "nodes", None) if loading_group else None
        group_name = str(getattr(loading_group, "name", "") or "").strip() if loading_group else ""
        testing_mode = group_name in {
            "Planetka Textures Loading Group",
            "Planetka Textures Loading Group - Testing",
        }
    for group_node in active_groups:
        if testing_mode and group_nodes is not None:
            suffix = str(getattr(group_node, "name", "") or "").split("_", 1)[1] if "_" in str(getattr(group_node, "name", "") or "") else ""
            if not suffix.isdigit():
                errors.append(f"invalid_testing_tile_node_name:{group_node.name}")
                continue
            index = int(suffix)
            for image_type in ("S2", "EL", "WT", "PO"):
                image_node = group_nodes.get(f"TileImg_{index:03d}_{image_type}")
                if image_node is None:
                    errors.append(f"missing_image_node:{group_node.name}:{image_type}")
                    continue
                image = getattr(image_node, "image", None)
                if image is None:
                    errors.append(f"missing_image_ref:{group_node.name}:{image_type}")
                    continue
                image_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "")).strip()
                if not image_path:
                    errors.append(f"missing_image_path:{group_node.name}:{image_type}")
                    continue
                abs_path = bpy.path.abspath(image_path)
                if not abs_path or not os.path.isfile(abs_path):
                    errors.append(f"missing_image_file:{group_node.name}:{image_type}:{abs_path}")
            continue
        group_tree = getattr(group_node, "node_tree", None)
        group_nodes = getattr(group_tree, "nodes", None) if group_tree else None
        if group_nodes is None:
            errors.append(f"missing_group_tree:{group_node.name}")
            continue
        for image_type in ("S2", "EL", "WT", "PO"):
            image_node = group_nodes.get(image_type)
            if image_node is None:
                errors.append(f"missing_image_node:{group_node.name}:{image_type}")
                continue
            image = getattr(image_node, "image", None)
            if image is None:
                errors.append(f"missing_image_ref:{group_node.name}:{image_type}")
                continue
            image_path = str(getattr(image, "filepath_raw", "") or getattr(image, "filepath", "")).strip()
            if not image_path:
                errors.append(f"missing_image_path:{group_node.name}:{image_type}")
                continue
            abs_path = bpy.path.abspath(image_path)
            if not abs_path or not os.path.isfile(abs_path):
                errors.append(f"missing_image_file:{group_node.name}:{image_type}:{abs_path}")
    return errors


def _build_cases(total_cases, random_places, capital_displays, rng):
    cases = []
    # Pole stress points.
    while len(cases) < min(40, max(4, total_cases // 20)):
        pole_name, lon, lat = POLE_CASES[len(cases) % len(POLE_CASES)]
        altitude_km = 3000.0 if (len(cases) % 2 == 0) else 30.0
        cases.append(
            {
                "kind": "pole",
                "label": f"{pole_name} {int(altitude_km)}km",
                "direct_lon": float(lon),
                "direct_lat": float(lat),
                "altitude_km": float(altitude_km),
            }
        )

    # Capital sweeps.
    for display in capital_displays:
        if len(cases) >= total_cases:
            break
        cases.append({"kind": "capital", "label": str(display), "place_display": str(display)})

    # Random places fill.
    for display in random_places:
        if len(cases) >= total_cases:
            break
        cases.append({"kind": "random_place", "label": str(display), "place_display": str(display)})

    # If still short, random direct coordinates.
    while len(cases) < total_cases:
        cases.append(
            {
                "kind": "random_coords",
                "label": "Random Coordinates",
                "direct_lon": float(rng.uniform(-180.0, 180.0)),
                "direct_lat": float(rng.uniform(-85.0, 85.0)),
            }
        )

    rng.shuffle(cases)
    return cases[:total_cases]


def _run_case(
    case_index,
    case_data,
    scene,
    props,
    state_module,
    geonames_module,
    diagnostics_module,
    render_prep_module,
    rng,
    render_enabled=False,
    render_dir="",
    render_prefix="",
    render_mode="dual",
):
    started = time.perf_counter()
    warnings = []
    camera = getattr(scene, "camera", None)
    camera_before = _camera_signature(camera)
    selected_name = ""

    if "place_display" in case_data:
        place_display = str(case_data.get("place_display", "")).strip()
        props.nav_city_search = place_display
        for _ in range(12):
            try:
                bpy.context.view_layer.update()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            selected_name = str(getattr(props, "nav_city_selected_name", "") or "").strip()
            if selected_name:
                break
            time.sleep(0.05)
        if not selected_name:
            entry = geonames_module.get_place_by_display(place_display)
            if isinstance(entry, dict):
                try:
                    props.nav_longitude_deg = float(entry.get("longitude", 0.0))
                    props.nav_latitude_deg = float(entry.get("latitude", 0.0))
                    state_module.update_navigation_shot(props, bpy.context)
                    selected_name = place_display
                    warnings.append("place_selected_via_direct_coords")
                except TOOL_RECOVERABLE_EXCEPTIONS:
                    pass
        if not selected_name:
            return {
                "case": case_index,
                "ok": False,
                "kind": str(case_data.get("kind", "")),
                "label": str(case_data.get("label", "")),
                "error": "place_selection_failed",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }
    else:
        try:
            props.nav_longitude_deg = float(case_data.get("direct_lon", 0.0))
            props.nav_latitude_deg = float(case_data.get("direct_lat", 0.0))
            state_module.update_navigation_shot(props, bpy.context)
            selected_name = str(case_data.get("label", "Direct Coordinates"))
        except TOOL_RECOVERABLE_EXCEPTIONS:
            return {
                "case": case_index,
                "ok": False,
                "kind": str(case_data.get("kind", "")),
                "label": str(case_data.get("label", "")),
                "error": "direct_coordinate_apply_failed",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            }

    altitude_km = float(case_data.get("altitude_km", rng.uniform(30.0, 3000.0)))
    azimuth = float(rng.uniform(0.0, 360.0))
    tilt = float(rng.uniform(-75.0, 75.0))
    roll = float(rng.uniform(-45.0, 45.0))
    focal = float(rng.uniform(30.0, 70.0))
    _set_nav_values(props, state_module, altitude_km, azimuth, tilt, roll, focal)

    camera_after_nav, camera_updated = _wait_for_camera_update(
        scene, props, state_module, previous_signature=camera_before, timeout_sec=2.0
    )
    if not camera_updated:
        return {
            "case": case_index,
            "ok": False,
            "kind": str(case_data.get("kind", "")),
            "label": str(case_data.get("label", "")),
            "selected_place": selected_name,
            "error": "camera_update_timeout",
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }

    sunlight = str(rng.choice(SUNLIGHT_PRESETS))
    sunlight_result = bpy.ops.planetka.sunlight_preset(preset=sunlight)
    if "FINISHED" not in sunlight_result:
        warnings.append("sunlight_preset_failed")

    resolve_start = time.perf_counter()
    resolve_result = bpy.ops.planetka.load_textures(scope_mode="CAMERA", skip_render_compatibility=True)
    resolve_wall_ms = (time.perf_counter() - resolve_start) * 1000.0
    if "FINISHED" not in resolve_result:
        return {
            "case": case_index,
            "ok": False,
            "kind": str(case_data.get("kind", "")),
            "label": str(case_data.get("label", "")),
            "selected_place": selected_name,
            "error": f"resolve_failed_{resolve_result}",
            "resolve_wall_ms": round(resolve_wall_ms, 3),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }

    integrity_errors = _validate_resolve_integrity(render_prep_module)
    diag = diagnostics_module.read_diagnostics(scene)

    payload = {
        "case": case_index,
        "ok": len(integrity_errors) == 0,
        "kind": str(case_data.get("kind", "")),
        "label": str(case_data.get("label", "")),
        "selected_place": selected_name,
        "altitude_km": round(altitude_km, 3),
        "azimuth_deg": round(azimuth, 3),
        "tilt_deg": round(tilt, 3),
        "roll_deg": round(roll, 3),
        "focal_mm": round(focal, 3),
        "sunlight_preset": sunlight,
        "camera_signature_before": camera_before,
        "camera_signature_after_nav": camera_after_nav,
        "resolve_wall_ms": round(resolve_wall_ms, 3),
        "resolve_tile_count": diag.get("last_tile_count"),
        "resolve_downloaded_mb": diag.get("resolve_downloaded_mb"),
        "resolve_download_ms": diag.get("resolve_download_ms"),
        "resolve_assets_ms": diag.get("resolve_assets_ms"),
        "resolve_tile_select_ms": diag.get("resolve_tile_select_ms"),
        "resolve_stream_ms": diag.get("resolve_stream_ms"),
        "resolve_mesh_ms": diag.get("resolve_mesh_ms"),
        "resolve_shader_ms": diag.get("resolve_shader_ms"),
        "resolve_post_ms": diag.get("resolve_post_ms"),
        "resolve_post_delete_ms": diag.get("resolve_post_delete_ms"),
        "resolve_post_mark_ms": diag.get("resolve_post_mark_ms"),
        "resolve_post_preview_ms": diag.get("resolve_post_preview_ms"),
        "resolve_unaccounted_ms": diag.get("resolve_unaccounted_ms"),
        "resolve_download_thread_ms": diag.get("resolve_download_thread_ms"),
        "resolve_stage": diag.get("resolve_stage"),
        "resolve_error": diag.get("resolve_error"),
        "integrity_errors": integrity_errors,
        "warnings": warnings,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }
    if render_enabled:
        renders = _render_case(scene, render_dir, render_prefix, case_index, render_mode=render_mode)
        payload["renders"] = renders
        if renders:
            payload["render_path"] = str(renders[0].get("path", ""))
            payload["render_ms"] = renders[0].get("render_ms")
    if integrity_errors:
        payload["error"] = "integrity_validation_failed"
    return payload


def main():
    started_at = time.time()
    seed = int(os.environ.get("PLANETKA_SOAK_SEED") or str(DEFAULT_SEED))
    total_cases = max(1, int(os.environ.get("PLANETKA_SOAK_CASES") or str(DEFAULT_CASES)))
    report_dir = str(os.environ.get("PLANETKA_SOAK_REPORT_DIR") or DEFAULT_REPORT_DIR).strip()
    render_enabled = str(os.environ.get("PLANETKA_SOAK_RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}
    render_mode = str(os.environ.get("PLANETKA_SOAK_RENDER_MODE") or "dual").strip().lower()
    render_prefix = str(os.environ.get("PLANETKA_SOAK_RENDER_PREFIX") or "planetka_soak_render").strip() or "planetka_soak_render"
    render_noise_threshold = float(os.environ.get("PLANETKA_SOAK_RENDER_NOISE_THRESHOLD") or "0.05")
    expected_email = str(os.environ.get("PLANETKA_EXPECTED_EMAIL") or EXPECTED_ADMIN_EMAIL).strip().lower()
    forced_device_id = str(os.environ.get("PLANETKA_DEVICE_ID") or "").strip()
    os.makedirs(report_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(report_dir, f"planetka_resolve_soak_report_{ts}.json")

    rng = random.Random(seed)
    failures = []
    results = []
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
        render_prep_module = _import_submodule(base_module_name, "render_prep")

        prefs = extension_prefs.get_prefs()
        _assert(prefs is not None, "Planetka preferences unavailable.")
        if forced_device_id:
            prefs.cloud_install_id = forced_device_id
        auth_module.ensure_authenticated_session(prefs)
        _assert(auth_module.is_authenticated(prefs), "Planetka session is not active.")
        device_id = str(getattr(prefs, "cloud_install_id", "") or "").strip()
        if expected_email:
            _log("Ignoring expected email; Planetka uses anonymous cloud sessions.")
        _log(f"Planetka session active: device_id={device_id or 'unknown'}")

        scene = bpy.context.scene
        _ensure_active_camera(scene)
        _remove_existing_planetka_objects()
        _remove_non_planetka_lights(scene)

        prefs.texture_base_path = "planetka-remote"
        props = scene.planetka
        props.show_earth_preview = False

        create_result = bpy.ops.planetka.add_earth()
        _assert("FINISHED" in create_result, f"Create Earth failed: {create_result}")
        scene.render.engine = "CYCLES"
        _assert(str(scene.render.engine) == "CYCLES", f"Render engine is not CYCLES: {scene.render.engine}")
        gpu_info = _configure_cycles_gpu(scene)
        _log(f"Cycles backend={gpu_info.get('backend')} gpu_enabled={gpu_info.get('gpu_enabled')} devices={gpu_info.get('devices')}")
        if render_enabled:
            _configure_render_output(scene, noise_threshold=render_noise_threshold)
            _log(
                f"Render mode enabled: HD PNG, Cycles device={gpu_info.get('scene_cycles_device')}, "
                f"noise_threshold={render_noise_threshold}, mode={render_mode}"
            )

        _wait_for_geonames_ready(geonames_module)
        connection, db_path = _open_geonames_connection(geonames_module)
        random_places = _sample_random_places(connection, max(total_cases, 1200), rng)
        capital_displays = []
        for city in CAPITAL_QUERIES:
            display = _pick_place_display(geonames_module, city)
            if display:
                capital_displays.append(display)
        cases = _build_cases(total_cases, random_places, capital_displays, rng)
        _assert(len(cases) == total_cases, f"Case build mismatch: expected={total_cases} got={len(cases)}")

        _log(f"Starting resolve soak: cases={total_cases} seed={seed}")
        for index, case_data in enumerate(cases, start=1):
            payload = _run_case(
                case_index=index,
                case_data=case_data,
                scene=scene,
                props=props,
                state_module=state_module,
                geonames_module=geonames_module,
                diagnostics_module=diagnostics_module,
                render_prep_module=render_prep_module,
                rng=rng,
                render_enabled=render_enabled,
                render_dir=report_dir,
                render_prefix=render_prefix,
                render_mode=render_mode,
            )
            results.append(payload)
            if not bool(payload.get("ok")):
                failures.append(f"Case {index:04d} {payload.get('kind')} {payload.get('label')}: {payload.get('error')}")
            if index % 25 == 0 or not bool(payload.get("ok")):
                _log(
                    f"Case {index:04d}/{total_cases}: ok={payload.get('ok')} "
                    f"kind={payload.get('kind')} label={payload.get('label')} "
                    f"tiles={payload.get('resolve_tile_count')} dl_mb={payload.get('resolve_downloaded_mb')} "
                    f"render={payload.get('render_path', '')}"
                )

        total_downloaded_mb = 0.0
        total_resolve_ms = 0.0
        total_tiles = 0
        for row in results:
            try:
                total_downloaded_mb += float(row.get("resolve_downloaded_mb") or 0.0)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            try:
                total_resolve_ms += float(row.get("resolve_wall_ms") or 0.0)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass
            try:
                total_tiles += int(row.get("resolve_tile_count") or 0)
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass

        report = {
            "tag": TAG,
            "seed": seed,
            "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)),
            "ended_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": round(time.time() - started_at, 3),
            "cases_total": total_cases,
            "cases_passed": total_cases - len(failures),
            "cases_failed": len(failures),
            "summary": {
                "total_downloaded_mb": round(total_downloaded_mb, 6),
                "total_resolve_wall_ms": round(total_resolve_ms, 6),
                "total_resolved_tiles": int(total_tiles),
                "avg_downloaded_mb_per_case": round(total_downloaded_mb / max(1, total_cases), 6),
                "avg_resolve_wall_ms_per_case": round(total_resolve_ms / max(1, total_cases), 6),
            },
            "cloud_session": {
                "device_id": device_id,
            },
            "geonames_db_path": db_path,
            "failures": failures,
            "results": results,
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        if failures:
            _log(f"Completed with failures={len(failures)}. Report: {report_path}")
            raise SystemExit(2)
        _log(f"Completed successfully. Report: {report_path}")
    except SystemExit:
        raise
    except TOOL_RECOVERABLE_EXCEPTIONS as exc:
        crash_report = {
            "tag": TAG,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "partial_results_count": len(results),
            "partial_failures_count": len(failures),
            "results": results[-25:],
            "failures": failures[-50:],
        }
        try:
            with open(report_path, "w", encoding="utf-8") as handle:
                json.dump(crash_report, handle, indent=2)
            _log(f"Crash report written: {report_path}")
        except TOOL_RECOVERABLE_EXCEPTIONS:
            _log("Failed writing crash report.")
        raise
    finally:
        if connection is not None:
            try:
                connection.close()
            except TOOL_RECOVERABLE_EXCEPTIONS:
                pass


if __name__ == "__main__":
    main()
