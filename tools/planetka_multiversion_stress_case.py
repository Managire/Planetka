"""
Planetka multiversion stress case runner (single Blender process/run).

Per run:
- open default scene
- Create Earth
- switch background to black
- sample random places from GeoNames
- for each place:
  - set requested nav ranges
  - apply MID_MORNING light
  - resolve in Full Quality
  - render HD OPEN_EXR (ZIP, half-float)

Designed to be launched repeatedly by an external shell orchestrator for:
- Blender versions: 4.5, 5.0, 5.1, 5.2
- Earth radius: 2 and 6000
- Engines: EEVEE and CYCLES
"""

import importlib
import json
import os
import random
import sqlite3
import sys
import time
import traceback

import addon_utils
import bpy


TAG = "[Planetka MultiVersion Stress]"
DEFAULT_RENDER_DIR = "/Volumes/SSDA/Renders"
DEFAULT_TEXTURE_BASE_PATH = "planetka-remote"


def _log(message):
    print(f"{TAG} {message}")


def _fail(message):
    _log(f"FAIL: {message}")
    raise SystemExit(1)


def _unique(values):
    seen = set()
    out = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _addon_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _enable_module():
    force_local = str(os.environ.get("PLANETKA_FORCE_LOCAL") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    addon_root = _addon_root()
    parent_dir = os.path.dirname(addon_root)
    package_name = os.path.basename(addon_root)

    if force_local:
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
                _log(f"Enabled addon module via forced local import: {package_name}")
                return package_name
        except Exception:
            pass

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


def _open_geonames_connection(geonames_module, timeout_sec=240.0):
    started = time.time()
    while True:
        geonames_module.load_geonames_database()
        status = str(geonames_module.get_search_status())
        if status == "ready":
            break
        if status == "error":
            _fail(f"GeoNames index status=error: {geonames_module.get_search_status_text()}")
        if (time.time() - started) >= float(timeout_sec):
            _fail(f"GeoNames index did not reach ready within {timeout_sec:.0f}s (status={status})")
        time.sleep(0.5)

    db_path = str(getattr(geonames_module, "_INDEX_DB_PATH", "") or "").strip()
    if not db_path or not os.path.isfile(db_path):
        _fail(f"GeoNames DB path missing: {db_path}")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0), db_path


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
    max_attempts = max(5000, int(count) * 50)
    while len(sampled) < int(count) and attempts < max_attempts:
        attempts += 1
        probe = rng.randint(min_id, max_id)
        cursor.execute(
            """
            SELECT geonameid, name, country_code, latitude, longitude
            FROM places
            WHERE geonameid >= ?
            ORDER BY geonameid ASC
            LIMIT 1
            """,
            (probe,),
        )
        item = cursor.fetchone()
        if not item:
            continue
        name = str(item[1] or "").strip()
        country = str(item[2] or "").strip().upper()
        try:
            lat = float(item[3])
            lon = float(item[4])
        except Exception:
            continue
        if not name:
            continue
        display = f"{name}, {country}" if country else name
        if display in used:
            continue
        used.add(display)
        sampled.append(
            {
                "display": display,
                "name": name,
                "country": country,
                "latitude": lat,
                "longitude": lon,
            }
        )
    return sampled


def _camera_signature(camera):
    if camera is None:
        return None
    matrix = camera.matrix_world
    t = matrix.translation
    q = matrix.to_quaternion()
    lens = float(getattr(getattr(camera, "data", None), "lens", 0.0) or 0.0)
    return (
        round(float(t.x), 7),
        round(float(t.y), 7),
        round(float(t.z), 7),
        round(float(q.w), 7),
        round(float(q.x), 7),
        round(float(q.y), 7),
        round(float(q.z), 7),
        round(float(lens), 6),
    )


def _wait_for_camera_update(scene, props, state_module, previous_signature, timeout_sec=2.5):
    camera = getattr(scene, "camera", None)
    if camera is None or getattr(camera, "type", None) != "CAMERA":
        return previous_signature, False
    deadline = time.monotonic() + float(timeout_sec)
    while time.monotonic() < deadline:
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        sig = _camera_signature(camera)
        if previous_signature is None or sig != previous_signature:
            return sig, True
        time.sleep(0.05)
    return _camera_signature(camera), False


def _apply_place_selection(props, geonames_module, state_module, place_record):
    place_display = str((place_record or {}).get("display", "") or "").strip()
    if not place_display:
        return "", 0.0, 0.0, "place_selection_failed"

    props.nav_city_search = place_display
    selected_name = ""
    for _ in range(16):
        try:
            bpy.context.view_layer.update()
        except Exception:
            pass
        selected_name = str(getattr(props, "nav_city_selected_name", "") or "").strip()
        if selected_name:
            # Do not trust async callback coordinates in long background runs.
            # Force deterministic lon/lat from sampled DB row.
            try:
                forced_lon = float((place_record or {}).get("longitude", 0.0))
                forced_lat = float((place_record or {}).get("latitude", 0.0))
            except Exception:
                return "", 0.0, 0.0, "place_selection_failed"
            return selected_name, forced_lon, forced_lat, None
        time.sleep(0.05)

    try:
        # Some names containing locale-specific characters may not round-trip through
        # the search callback in background mode. Always fall back to sampled DB coords.
        props.nav_longitude_deg = float((place_record or {}).get("longitude", 0.0))
        props.nav_latitude_deg = float((place_record or {}).get("latitude", 0.0))
        state_module.update_navigation_shot(props, bpy.context)
    except Exception:
        return "", 0.0, 0.0, "place_fallback_nav_failed"
    fallback_name = selected_name or place_display
    return str(fallback_name), float(props.nav_longitude_deg), float(props.nav_latitude_deg), "fallback_direct_coords"


def _configure_render(scene, render_engine):
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.use_simplify = True

    image_settings = scene.render.image_settings
    image_settings.file_format = "OPEN_EXR"
    image_settings.color_depth = "16"
    image_settings.exr_codec = "ZIP"

    mode = str(render_engine or "CYCLES").upper()
    if mode == "CYCLES":
        try:
            bpy.ops.planetka.switch_to_cycles()
        except Exception:
            scene.render.engine = "CYCLES"
        if "CYCLES" not in str(scene.render.engine):
            _fail(f"Failed to switch to Cycles, current engine={scene.render.engine}")
        try:
            scene.cycles.samples = 16
            scene.cycles.preview_samples = 8
            scene.cycles.use_adaptive_sampling = True
            scene.cycles.use_denoising = False
        except Exception:
            pass
        return "CYCLES"

    target = "BLENDER_EEVEE_NEXT"
    try:
        enum_items = scene.render.bl_rna.properties["engine"].enum_items.keys()
        if target not in enum_items:
            target = "BLENDER_EEVEE"
    except Exception:
        target = "BLENDER_EEVEE"
    scene.render.engine = target
    if "EEVEE" not in str(scene.render.engine):
        _fail(f"Failed to switch to EEVEE, current engine={scene.render.engine}")
    return str(scene.render.engine)


def _set_reasonable_clipping(scene):
    camera = getattr(scene, "camera", None)
    earth = None
    try:
        earth = bpy.data.objects.get("Planetka Earth Surface")
    except Exception:
        earth = None
    if camera is None or getattr(camera, "type", None) != "CAMERA":
        return
    cam_data = getattr(camera, "data", None)
    if cam_data is None:
        return
    if earth is None:
        try:
            cam_data.clip_start = min(float(getattr(cam_data, "clip_start", 0.1)), 0.01)
            cam_data.clip_end = max(float(getattr(cam_data, "clip_end", 1000.0)), 100000.0)
        except Exception:
            pass
        return

    try:
        distance = float((camera.matrix_world.translation - earth.matrix_world.translation).length)
    except Exception:
        distance = 1000.0
    clip_start = max(1e-6, distance / 1_000_000.0)
    clip_end = max(distance * 10.0, clip_start * 100.0)
    max_ratio = 10_000_000.0
    if clip_end / max(clip_start, 1e-9) > max_ratio:
        clip_end = clip_start * max_ratio
    try:
        cam_data.clip_start = clip_start
        cam_data.clip_end = clip_end
    except Exception:
        pass


def main():
    render_dir = str(os.environ.get("PLANETKA_RENDER_DIR") or DEFAULT_RENDER_DIR).strip()
    run_seed = int(os.environ.get("PLANETKA_STRESS_SEED") or "20260408")
    random_count = max(1, int(os.environ.get("PLANETKA_RANDOM_PLACE_COUNT") or "100"))
    render_engine = str(os.environ.get("PLANETKA_RENDER_ENGINE") or "CYCLES").strip().upper()
    earth_radius = float(os.environ.get("PLANETKA_EARTH_RADIUS_BU") or "2.0")
    texture_base_path = str(os.environ.get("PLANETKA_TEXTURE_BASE_PATH") or DEFAULT_TEXTURE_BASE_PATH).strip()
    auth_api_key = str(os.environ.get("PLANETKA_AUTH_API_KEY") or "").strip()
    auth_device_id = str(os.environ.get("PLANETKA_AUTH_DEVICE_ID") or "").strip()
    run_tag = str(os.environ.get("PLANETKA_RUN_TAG") or f"run_{int(time.time())}").strip()

    os.makedirs(render_dir, exist_ok=True)
    report_path = os.path.join(render_dir, f"planetka_multiversion_stress_report_{run_tag}.json")
    render_prefix = f"planetka_multiversion_{run_tag}"
    rng = random.Random(run_seed)
    conn = None
    db_path = ""

    failures = []
    cases = []
    started_at = time.time()
    resolved_engine = ""

    try:
        base_module_name = _enable_module()
        if not base_module_name:
            _fail("Could not enable Planetka module.")

        extension_prefs = _import_submodule(base_module_name, "extension_prefs")
        auth_module = _import_submodule(base_module_name, "auth")
        geonames_module = _import_submodule(base_module_name, "geonames_db")
        diagnostics_module = _import_submodule(base_module_name, "diagnostics")
        state_module = _import_submodule(base_module_name, "state")

        prefs = extension_prefs.get_prefs()
        if prefs is None:
            _fail("Planetka preferences unavailable.")
        if auth_device_id:
            try:
                prefs.auth_device_id = auth_device_id
            except Exception:
                _log("WARN: failed to set explicit auth device id")
        if not bool(auth_module.is_authenticated(prefs)):
            if not auth_api_key:
                _fail("Account not authenticated and PLANETKA_AUTH_API_KEY is missing.")
            auth_module.connect_with_api_key(auth_api_key, prefs=prefs)
            _log(f"Authenticated via API key: email={auth_module.get_connected_email(prefs)}")
        prefs.texture_base_path = texture_base_path

        scene = bpy.context.scene
        props = scene.planetka
        props.auto_resolve = False
        props.show_earth_preview = True

        create_result = bpy.ops.planetka.add_earth()
        if "FINISHED" not in create_result:
            _fail(f"Create Earth failed: {create_result}")
        try:
            props.texture_quality_mode = "FULL"
        except Exception:
            _log("WARN: failed forcing Full Quality mode")

        try:
            bpy.ops.planetka.set_background_black()
        except Exception:
            pass

        try:
            props.earth_radius_bu = float(max(1e-6, earth_radius))
        except Exception:
            _fail(f"Failed setting Earth Radius to {earth_radius}")

        resolved_engine = _configure_render(scene, render_engine)
        _set_reasonable_clipping(scene)
        _log(
            "Configured run: "
            f"engine={resolved_engine} radius={earth_radius} quality={props.texture_quality_mode} "
            f"output={render_dir}"
        )

        conn, db_path = _open_geonames_connection(geonames_module)
        places = _sample_random_places(conn, random_count, rng)
        if len(places) < random_count:
            _log(f"WARN: sampled {len(places)} places (requested {random_count})")
        if not places:
            _fail("No random places sampled.")

        camera = getattr(scene, "camera", None)
        camera_sig = _camera_signature(camera)

        for idx, place_record in enumerate(places, start=1):
            case_start = time.perf_counter()
            warnings = []
            place_display = str((place_record or {}).get("display", "") or "").strip()

            selected_place, forced_lon, forced_lat, select_warning = _apply_place_selection(
                props,
                geonames_module,
                state_module,
                place_record,
            )
            if not selected_place:
                selected_place = place_display
                warnings.append("place_selection_fallback_label")
            if select_warning:
                warnings.append(str(select_warning))

            altitude = float(rng.uniform(60.0, 600.0))
            heading = float(rng.uniform(-45.0, 45.0))
            tilt = float(rng.uniform(25.0, 65.0))
            roll = float(rng.uniform(-15.0, 15.0))
            focal = float(rng.choice((30.0, 40.0, 50.0, 60.0, 70.0)))

            try:
                state_module.suspend_navigation_shot_updates()
                props.texture_quality_mode = "FULL"
                props.nav_longitude_deg = float(forced_lon)
                props.nav_latitude_deg = float(forced_lat)
                props.nav_altitude_km = altitude
                props.nav_azimuth_deg = heading
                props.nav_tilt_deg = tilt
                props.nav_roll_deg = roll
                props.nav_focal_length_mm = focal
            finally:
                state_module.resume_navigation_shot_updates()
            apply_result = bpy.ops.planetka.navigation_apply_shot(silent=True)
            if "FINISHED" not in apply_result:
                warnings.append(f"navigation_apply_failed_{apply_result}")
            camera_sig, cam_ok = _wait_for_camera_update(scene, props, state_module, camera_sig, timeout_sec=2.5)
            if not cam_ok:
                warnings.append("camera_update_timeout")

            try:
                sun_result = bpy.ops.planetka.sunlight_preset(preset="MID_MORNING")
                if "FINISHED" not in sun_result:
                    warnings.append("sunlight_preset_failed")
            except Exception:
                warnings.append("sunlight_preset_exception")

            _set_reasonable_clipping(scene)

            resolve_result = bpy.ops.planetka.load_textures(scope_mode="CAMERA", skip_render_compatibility=True)
            if "FINISHED" not in resolve_result:
                payload = {
                    "case": idx,
                    "ok": False,
                    "label": str(place_display),
                    "selected_place": str(selected_place),
                    "error": f"resolve_failed_{resolve_result}",
                    "altitude_km": round(altitude, 3),
                    "heading_deg": round(heading, 3),
                    "tilt_deg": round(tilt, 3),
                    "roll_deg": round(roll, 3),
                    "focal_mm": round(focal, 3),
                    "warnings": warnings,
                    "elapsed_ms": round((time.perf_counter() - case_start) * 1000.0, 3),
                }
                cases.append(payload)
                failures.append(payload)
                _log(f"Case {idx:03d}: FAIL resolve label={selected_place}")
                continue

            diag = diagnostics_module.read_diagnostics(scene)
            tile_count = int(diag.get("last_tile_count", 0) or 0)

            # Radius=6000 stress can occasionally produce camera orientations that miss Earth.
            # Enforce Earth-visible cases by retrying once with conservative framing.
            if tile_count <= 0:
                warnings.append("zero_tiles_retry")
                conservative_tilt = 35.0
                conservative_roll = 0.0
                conservative_heading = 0.0
                conservative_altitude = max(120.0, float(altitude))
                try:
                    state_module.suspend_navigation_shot_updates()
                    props.nav_altitude_km = conservative_altitude
                    props.nav_azimuth_deg = conservative_heading
                    props.nav_tilt_deg = conservative_tilt
                    props.nav_roll_deg = conservative_roll
                finally:
                    state_module.resume_navigation_shot_updates()
                retry_apply_result = bpy.ops.planetka.navigation_apply_shot(silent=True)
                if "FINISHED" not in retry_apply_result:
                    warnings.append(f"retry_navigation_apply_failed_{retry_apply_result}")
                _set_reasonable_clipping(scene)
                retry_resolve_result = bpy.ops.planetka.load_textures(
                    scope_mode="CAMERA",
                    skip_render_compatibility=True,
                )
                if "FINISHED" in retry_resolve_result:
                    diag = diagnostics_module.read_diagnostics(scene)
                    tile_count = int(diag.get("last_tile_count", 0) or 0)
                    if tile_count > 0:
                        altitude = conservative_altitude
                        heading = conservative_heading
                        tilt = conservative_tilt
                        roll = conservative_roll
                else:
                    warnings.append(f"retry_resolve_failed_{retry_resolve_result}")

            if tile_count <= 0:
                payload = {
                    "case": idx,
                    "ok": False,
                    "label": str(place_display),
                    "selected_place": str(selected_place),
                    "error": "zero_tiles_after_retry",
                    "altitude_km": round(altitude, 3),
                    "heading_deg": round(heading, 3),
                    "tilt_deg": round(tilt, 3),
                    "roll_deg": round(roll, 3),
                    "focal_mm": round(focal, 3),
                    "warnings": warnings,
                    "elapsed_ms": round((time.perf_counter() - case_start) * 1000.0, 3),
                }
                cases.append(payload)
                failures.append(payload)
                _log(f"Case {idx:03d}: FAIL zero_tiles_after_retry label={selected_place}")
                continue

            render_path = os.path.join(render_dir, f"{render_prefix}_{idx:04d}.exr")
            scene.render.filepath = render_path
            bpy.ops.render.render(write_still=True)

            diag = diagnostics_module.read_diagnostics(scene)
            payload = {
                "case": idx,
                "ok": True,
                "label": str(place_display),
                "selected_place": str(selected_place),
                "altitude_km": round(altitude, 3),
                "heading_deg": round(heading, 3),
                "tilt_deg": round(tilt, 3),
                "roll_deg": round(roll, 3),
                "focal_mm": round(focal, 3),
                "sunlight_preset": "MID_MORNING",
                "render_path": render_path,
                "resolve_tile_count": int(diag.get("last_tile_count", 0) or 0),
                "resolve_downloaded_mb": diag.get("resolve_downloaded_mb"),
                "resolve_download_ms": diag.get("resolve_download_ms"),
                "warnings": warnings,
                "elapsed_ms": round((time.perf_counter() - case_start) * 1000.0, 3),
            }
            cases.append(payload)
            _log(
                f"Case {idx:03d}: ok place={selected_place} "
                f"tiles={payload.get('resolve_tile_count')} render={os.path.basename(render_path)}"
            )

    except SystemExit:
        raise
    except Exception as exc:
        failures.append({"fatal": str(exc), "traceback": traceback.format_exc()})
        _log(f"FATAL: {exc}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

        elapsed_sec = round(time.time() - started_at, 3)
        success_count = sum(1 for c in cases if c.get("ok"))
        summary = {
            "ok": len(failures) == 0,
            "run_tag": run_tag,
            "seed": run_seed,
            "engine_requested": render_engine,
            "engine_resolved": resolved_engine,
            "earth_radius_bu": earth_radius,
            "texture_base_path": texture_base_path,
            "random_place_count_requested": random_count,
            "random_place_count_used": len(cases),
            "success_count": success_count,
            "failure_count": len(failures),
            "elapsed_seconds": elapsed_sec,
            "render_dir": render_dir,
            "report_path": report_path,
            "geonames_db_path": db_path,
            "cases": cases,
            "failures": failures,
        }
        with open(report_path, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
        _log(
            f"Completed run_tag={run_tag} ok={summary['ok']} success={success_count}/{len(cases)} "
            f"failures={len(failures)} report={report_path}"
        )

        if failures:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
